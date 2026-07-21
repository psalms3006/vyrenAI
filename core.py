import logging
import os
import sys
import time
from pathlib import Path

# Make sure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config

from event_bus import EventBus, Event, VYREN_STARTED, VYREN_TOOL_CALLED, VYREN_TOOL_RESULT, VYREN_MEMORY_UPDATED, VYREN_ERROR
from knowledge_graph import KnowledgeGraph
from world_model import WorldModel
from scheduler import Scheduler
from memory import MemoryStore
from memory_v2 import MemoryManager, MemoryLayer
from audit import AuditLog
from heartbeat import Heartbeat, NoticeStore
from reliability import CircuitBreaker, HealthMonitor, setup_logging, Watchdog
from tools import ToolRegistry, create_registry

# --- V2 subsystems (merged from v2) ---
from planner import Planner, PlanStore
from learning import Learner, LessonStore
from security import SecurityManager
from context import ContextManager, ContextBudget
from execution import CheckpointManager
from reflection import Reflector, ReflectionStore
from monitoring import get_system_snapshot

logger = logging.getLogger("vyren.core")


class VYRENCtx:
    """Shared context object passed to all subsystems.

    One of these is created at startup. Every module gets a reference
    so they can talk to each other through shared state, never by
    reaching into each other's internals.
    """

    def __init__(self):
        # --- Config ---
        config.load()
        self.config = config

        # --- Logging ---
        log_path = config.get("audit.path", "~/.vyren/vyren.log").replace(
            "audit.log", "vyren.log"
        )
        setup_logging(
            level=config.get("log.level", "INFO"),
            log_file=log_path,
        )

        # --- Audit ---
        self.audit = AuditLog(config.get("audit.path"))

        # --- Event Bus ---
        self.event_bus = EventBus()
        self.event_bus.subscribe("*", self._global_event_handler)

        # --- Memory (v1 flat, kept for backward compat) ---
        self.memory = MemoryStore(config.get("memory.path"))

        # --- Memory v2 (6-layer) ---
        self.memory_v2 = MemoryManager()

        # --- Knowledge Graph ---
        self.knowledge_graph = KnowledgeGraph()

        # --- World Model ---
        self.world_model = WorldModel()

        # --- Scheduler ---
        self.scheduler = Scheduler()
        self._register_scheduler_handlers()

        # --- Planner ---
        self.plan_store = PlanStore()
        self.planner = Planner(self.plan_store, ctx=self)

        # --- Learning ---
        self.lesson_store = LessonStore()
        self.learner = Learner(self.lesson_store)

        # --- Security ---
        self.security = SecurityManager()

        # --- Context Manager ---
        self.context_manager = ContextManager()

        # --- Execution ---
        self.checkpoints = CheckpointManager()

        # --- Reflection ---
        self.reflection_store = ReflectionStore()
        self.reflector = Reflector(self.reflection_store)

        # --- Reliability ---
        self.gemini_breaker = CircuitBreaker(
            "gemini_api", failure_threshold=5, recovery_timeout=60
        )
        self.health = HealthMonitor()
        self.watchdog = Watchdog(default_timeout=60)
        self._register_health_checks()

        # --- Heartbeat ---
        self.notice_store = NoticeStore(
            config.get("audit.path", "~/.vyren/notices.json").replace(
                "audit.log", "notices.json"
            )
        )
        self.heartbeat = Heartbeat(
            notice_store=self.notice_store,
            config=config.get("heartbeat", {"enabled": False, "interval_seconds": 300, "checks": []}),
            on_notice=self._on_heartbeat_notice,
        )

        # --- Tool Registry (built last, depends on above) ---
        self.registry = self._build_registry()

        # --- System Prompt ---
        self.system_prompt = self._build_system_prompt()
        self.gemini_tools = self.registry.to_gemini_tools()

        # --- Brain ---
        from brain import Brain
        self.brain = Brain(self)

        logger.info("VYREN context initialized with all subsystems")

    # ------------------------------------------------------------------
    # Internal setup helpers
    # ------------------------------------------------------------------

    def _build_registry(self) -> ToolRegistry:
        """Create the tool registry with all tools registered."""
        return create_registry(
            memory_store=self.memory,
            knowledge_graph=self.knowledge_graph,
            scheduler=self.scheduler,
            world_model=self.world_model,
            event_bus=self.event_bus,
            memory_v2=self.memory_v2,
        )

    def _build_system_prompt(self) -> str:
        """Build the full system prompt with all context injected."""
        from system_prompt import build_system_prompt

        memory_context = self.memory.build_context()
        # Include v2 high-importance memories
        v2_context = self.memory_v2.build_context(max_tokens=300)
        if v2_context:
            memory_context += "\n" + v2_context
        world_context = self.world_model.to_context_string()
        kg_context = self.knowledge_graph.to_context_string()

        return build_system_prompt(
            memory_context=memory_context,
            world_context=world_context,
            kg_context=kg_context,
        )

    def _register_scheduler_handlers(self):
        """Register built-in scheduler handlers."""
        def health_check(_ctx):
            status = self.health.check_all()
            degraded = [k for k, v in status.items() if v != "healthy"]
            if degraded:
                return f"Degraded: {', '.join(degraded)}"
            return "All healthy"

        def watchdog_check(_ctx):
            stuck = self.watchdog.check()
            if stuck:
                return stuck
            return "No stuck operations"

        def memory_consolidate(_ctx):
            self.memory_v2.consolidate()
            return "Memory consolidation done"

        self.scheduler.register("health_check", health_check)
        self.scheduler.register("watchdog_check", watchdog_check)
        self.scheduler.register("memory_consolidate", memory_consolidate)

    def _register_health_checks(self):
        """Register health checks for the monitor."""
        from provider import _ollama_available

        self.health.register("gemini_api", lambda: self.gemini_breaker.state.value == "closed")
        self.health.register("event_bus", lambda: self.event_bus.subscriber_count() is not None)
        self.health.register("memory", lambda: self.memory.count() >= 0)
        self.health.register("knowledge_graph", lambda: self.knowledge_graph.entity_count >= 0)
        self.health.register("scheduler", lambda: not self.scheduler.is_running or True)

    def _on_heartbeat_notice(self, notice: dict):
        """Handle a heartbeat notice."""
        self.audit.info(f"Heartbeat notice: {notice.get('message', '')}")
        self.event_bus.publish_sync(
            Event(type="heartbeat.notice", source="heartbeat", data=notice)
        )

    def _global_event_handler(self, event: Event):
        """Catch-all handler for logging all events."""
        logger.debug(f"Event: {event.type} from {event.source}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_background(self):
        """Start all background subsystems."""
        if self.config.get("heartbeat.enabled", False):
            self.heartbeat.start()
            logger.info("Heartbeat started")

        # Schedule built-in maintenance jobs
        self.scheduler.every(
            name="health_check", handler="health_check",
            interval_seconds=600, description="Periodic health check",
        )
        self.scheduler.every(
            name="memory_consolidate", handler="memory_consolidate",
            interval_seconds=3600, description="Hourly memory consolidation",
        )
        self.scheduler.start()
        logger.info("Scheduler started")

        # Watchdog monitoring
        self.watchdog.on_timeout(lambda op: logger.error(f"Watchdog: {op['operation']} stuck ({op['elapsed_seconds']}s)"))
        self.watchdog.start_monitoring(interval=15.0)

        # Publish startup event
        self.event_bus.publish_sync(
            Event(type=VYREN_STARTED, source="core", data={"tool_count": len(self.registry.tool_names())})
        )

        logger.info("All background subsystems started")

    def shutdown(self):
        """Graceful shutdown of all subsystems."""
        logger.info("VYREN shutting down...")
        self.event_bus.publish_sync(
            Event(type="vyren.shutdown", source="core", data={})
        )
        self.scheduler.stop()
        self.heartbeat.stop()
        self.event_bus.clear_subscribers()
        logger.info("VYREN stopped")

    def refresh_system_prompt(self):
        """Rebuild system prompt with latest memory/KG/world context."""
        self.system_prompt = self._build_system_prompt()
        self.gemini_tools = self.registry.to_gemini_tools()

    def get_status(self) -> dict:
        """Get a full status overview."""
        from provider import _ollama_available
        return {
            "tools": len(self.registry.tool_names()),
            "memory_v1": self.memory.count(),
            "memory_v2": self.memory_v2.count(),
            "knowledge_graph": self.knowledge_graph.get_stats(),
            "world_model": self.world_model.stats,
            "scheduler": self.scheduler.get_status(),
            "heartbeat": self.heartbeat.get_status(),
            "health": self.health.get_status(),
            "gemini_breaker": self.gemini_breaker.get_status(),
            "ollama_available": _ollama_available(),
            "planner": self.planner.get_status(),
            "learning": self.learner.get_status(),
            "security": self.security.get_status(),
            "context": self.context_manager.estimate_usage(),
            "brain": self.brain.get_status() if hasattr(self, 'brain') else {},
            "event_bus": {
                "subscribers": self.event_bus.subscriber_count(),
                "history_size": len(self.event_bus.history),
            },
        }


# ----------------------------------------------------------------------
# Convenience: one global instance
# ----------------------------------------------------------------------

_ctx: VYRENCtx | None = None


def get_ctx() -> VYRENCtx:
    """Get or create the global VYREN context."""
    global _ctx
    if _ctx is None:
        _ctx = VYRENCtx()
    return _ctx