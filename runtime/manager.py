"""
runtime/manager.py -- VYREN Runtime Manager.

The central orchestrator that owns the lifecycle of every subsystem.
Initialized by main.py, it delegates boot to BootManager then takes
over for continuous operation: process supervision, auto-restart,
health monitoring, always-on idle mode, and graceful shutdown.

Responsibilities:
  - Boot the entire system via BootManager
  - Supervise all services (auto-restart on crash)
  - Provide service discovery (get any subsystem by name)
  - Manage the always-on idle loop
  - Handle graceful shutdown (Ctrl+C, signals)
  - Provide the unified interaction entry point
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("vyren.runtime")

from platform_abstraction import get_env

VYREN_DIR: Path = get_env().data_dir


class RuntimeManager:
    """
    Central runtime orchestrator for the VYREN AI operating system.

    Usage from main.py:
        rt = RuntimeManager()
        rt.start()
        # VYREN is now running as a full OS
    """

    def __init__(self):
        from runtime.registry import RuntimeServiceRegistry

        self._services = RuntimeServiceRegistry()
        self._boot_manager = None
        self._running = False
        self._supervisor_thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()
        self._health_interval = 30  # seconds
        self._idle_cpu_target = 0.01  # 1% CPU when idle
        self._logged_notice_ids: set[str] = set()  # Track already-logged notices

        # Startup greeting sequencing (see _on_voice_state_for_greeting).
        # boot_ready: set once _boot() has fully returned (all 18 phases
        #             attempted) — the greeting waits on this too, so a
        #             fast-connecting voice engine can't fire the greeting
        #             before e.g. the server/service phases finish.
        # greeting_fired: guards against firing more than once (voice state
        #             can bounce through "listening" again on reconnects).
        self._boot_ready = threading.Event()
        self._greeting_fired = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._running

    def get(self, name: str) -> Any:
        """Get any subsystem by name (service discovery)."""
        return self._services.get(name)

    def register_service(self, name: str, instance: Any):
        """Register a running service instance."""
        self._services.register(name, instance)

    def start(self):
        """Boot the system and enter the always-on main loop."""
        # Ensure VYREN data directory exists
        VYREN_DIR.mkdir(parents=True, exist_ok=True)

        # Phase 1: Boot
        self._boot()

        # Phase 2: Signal handlers
        self._install_signal_handlers()

        # Phase 3: Mark running
        self._running = True

        # Phase 4: Start supervisor
        self._supervisor_thread = threading.Thread(
            target=self._supervisor_loop,
            name="vyren-supervisor",
            daemon=True,
        )
        self._supervisor_thread.start()

        # Phase 5: Main loop (blocks)
        self._main_loop()

    def shutdown(self):
        """Gracefully shut down the entire system."""
        if not self._running:
            return
        self._running = False
        self._shutdown_event.set()

        logger.info("Runtime Manager: Initiating graceful shutdown...")

        # Stop supervisor
        if self._supervisor_thread and self._supervisor_thread.is_alive():
            self._supervisor_thread.join(timeout=5)

        # Shutdown via boot manager (reverse order)
        if self._boot_manager:
            self._boot_manager.shutdown()

        logger.info("Runtime Manager: Shutdown complete")

    def get_status(self) -> dict:
        """Get comprehensive system status."""
        status = {
            "running": self._running,
            "services": {},
        }
        if self._boot_manager:
            status["boot"] = {
                "duration_ms": self._boot_manager.boot_duration_ms,
                "services": self._boot_manager.get_status(),
            }
        return status

    # ------------------------------------------------------------------
    # Boot
    # ------------------------------------------------------------------

    def _boot(self):
        """Execute the full boot sequence via BootManager."""
        from boot.manager import BootManager, Phase

        bm = BootManager()
        self._boot_manager = bm

        # Register all services in phase order.
        # Each init_fn receives (ctx: dict) and returns its instance.
        # The init_fn stores its result in ctx[name] for later services.

        # -- Phase 1: Config --
        bm.register("config", Phase.CONFIG, self._init_config,
                     critical=True)

        # -- Phase 2: Logging --
        bm.register("logging", Phase.LOGGING, self._init_logging,
                     critical=True, dependencies=["config"])

        # -- Phase 3: Audit --
        bm.register("audit", Phase.AUDIT, self._init_audit,
                     critical=False, dependencies=["config", "logging"])

        # -- Phase 4: Event Bus --
        bm.register("event_bus", Phase.EVENT_BUS, self._init_event_bus,
                     critical=True, dependencies=["logging"])

        # -- Phase 5: Memory --
        bm.register("memory", Phase.MEMORY, self._init_memory,
                     critical=True, dependencies=["config", "event_bus"])

        # -- Phase 6: Knowledge Graph --
        bm.register("knowledge_graph", Phase.KNOWLEDGE_GRAPH,
                     self._init_knowledge_graph,
                     dependencies=["event_bus"])

        # -- Phase 7: World Model --
        bm.register("world_model", Phase.WORLD_MODEL, self._init_world_model,
                     dependencies=["event_bus"])

        # -- Phase 8: Scheduler --
        bm.register("scheduler", Phase.SCHEDULER, self._init_scheduler,
                     dependencies=["event_bus", "memory"],
                     shutdown_fn=self._shutdown_scheduler)

        # -- Phase 9: Reliability --
        bm.register("reliability", Phase.RELIABILITY, self._init_reliability,
                     critical=False, dependencies=["logging", "event_bus"],
                     shutdown_fn=self._shutdown_reliability)

        # -- Phase 10: Heartbeat --
        bm.register("heartbeat", Phase.HEARTBEAT, self._init_heartbeat,
                     dependencies=["reliability", "scheduler"],
                     shutdown_fn=self._shutdown_heartbeat,
                     restart_on_failure=True)

        # -- Phase 11: Tools --
        bm.register("tools", Phase.TOOLS, self._init_tools,
                     critical=False,
                     dependencies=["memory", "knowledge_graph",
                                    "scheduler", "world_model",
                                    "event_bus"],
                     restart_on_failure=True)

        # -- Phase 12: Agents --
        bm.register("agents", Phase.AGENTS, self._init_agents,
                     dependencies=["memory", "knowledge_graph",
                                    "event_bus", "tools"])

        # -- Phase 13: Brain (planner + reasoning) --
        bm.register("brain", Phase.BRAIN, self._init_brain,
                     dependencies=["agents", "memory", "event_bus",
                                    "tools"])

        # -- Phase 14: Camera --
        bm.register("camera", Phase.CAMERA, self._init_camera,
                     dependencies=["config"],
                     shutdown_fn=self._shutdown_camera)

        # -- Phase 15: Connectivity --
        bm.register("connectivity", Phase.CONNECTIVITY,
                     self._init_connectivity,
                     dependencies=["event_bus", "reliability"],
                     shutdown_fn=self._shutdown_connectivity,
                     restart_on_failure=True)

        # -- Phase 16: Voice --
        bm.register("voice", Phase.VOICE, self._init_voice,
                     dependencies=["connectivity", "memory",
                                    "event_bus", "tools"],
                     shutdown_fn=self._shutdown_voice,
                     restart_on_failure=True)

        # -- Phase 17: Server --
        bm.register("server", Phase.SERVER, self._init_server,
                     dependencies=["memory", "tools", "event_bus",
                                    "heartbeat", "audit"],
                     shutdown_fn=self._shutdown_server,
                     restart_on_failure=True)

        # -- Phase 18: Service (PID file, state) --
        bm.register("service", Phase.SERVICE, self._init_service,
                     dependencies=["config"],
                     shutdown_fn=self._shutdown_service)

        # -- Phase 19: Monitoring --
        bm.register("monitoring", Phase.MONITORING, self._init_monitoring,
                     dependencies=["reliability", "tools", "event_bus"],
                     shutdown_fn=self._shutdown_monitoring)

        # Execute boot
        ctx = bm.boot()

        # Store all service references
        for name in bm._services:
            svc = bm._services[name]
            if svc._instance is not None:
                self._services[name] = svc._instance

        # Also store the shared context entries
        self._services.update(ctx)

    # ------------------------------------------------------------------
    # Service Initializers (one per subsystem)
    # ------------------------------------------------------------------

    def _init_config(self, ctx: dict):
        """Phase 1: Load configuration."""
        import config as cfg
        cfg.load()
        ctx["config"] = cfg
        return cfg

    def _init_logging(self, ctx: dict):
        """Phase 2: Initialize structured logging."""
        from reliability import setup_logging
        import config as cfg

        log_path = str(VYREN_DIR / "vyren.log")
        setup_logging(
            level=cfg.get("log.level", "INFO"),
            log_file=log_path,
        )
        ctx["log_path"] = log_path
        return log_path

    def _init_audit(self, ctx: dict):
        """Phase 3: Initialize audit logging."""
        from audit import AuditLog
        import config as cfg

        audit_path = str(VYREN_DIR / "audit.log")
        audit = AuditLog(audit_path)
        ctx["audit"] = audit
        return audit

    def _init_event_bus(self, ctx: dict):
        """Phase 4: Initialize the central event bus."""
        from event_bus import EventBus, Event

        bus = EventBus()
        # Global event handler for logging
        def global_handler(event):
            logger.debug(f"Event: {event.type} from {event.source}")

        bus.subscribe("*", global_handler)
        ctx["event_bus"] = bus
        return bus

    def _init_memory(self, ctx: dict):
        """Phase 5: Initialize persistent memory (v1 + v2)."""
        from memory import MemoryStore
        from memory_v2 import MemoryManager

        mem_v1 = MemoryStore(str(VYREN_DIR / "memory.json"))
        mem_v2 = MemoryManager()
        ctx["memory"] = mem_v1
        ctx["memory_v2"] = mem_v2
        return mem_v2  # Return v2 as primary

    def _init_knowledge_graph(self, ctx: dict):
        """Phase 6: Initialize knowledge graph."""
        from knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        ctx["knowledge_graph"] = kg
        return kg

    def _init_world_model(self, ctx: dict):
        """Phase 7: Initialize world model."""
        from world_model import WorldModel

        wm = WorldModel()
        ctx["world_model"] = wm
        return wm

    def _init_camera(self, ctx: dict):
        """Phase 14: Initialize camera engine."""
        try:
            from camera import CameraManager

            manager = CameraManager()
            ctx["camera"] = manager
            return manager
        except Exception as exc:
            logger.warning("Camera init failed: %s", exc)
            ctx["camera"] = None
            return None

    def _shutdown_camera(self, instance, ctx: dict):
        try:
            if instance is not None:
                instance.stop()
        except Exception:
            pass

    def _init_scheduler(self, ctx: dict):
        """Phase 8: Initialize job scheduler."""
        from scheduler import Scheduler

        sched = Scheduler()
        ctx["scheduler"] = sched
        return sched

    def _shutdown_scheduler(self, instance, ctx: dict):
        instance.stop()

    def _init_reliability(self, ctx: dict):
        """Phase 9: Initialize reliability (circuit breaker, health, watchdog)."""
        from reliability import CircuitBreaker, HealthMonitor, Watchdog

        gemini_breaker = CircuitBreaker("gemini_api", failure_threshold=5, recovery_timeout=60)
        health = HealthMonitor()
        watchdog = Watchdog(default_timeout=60)

        ctx["gemini_breaker"] = gemini_breaker
        ctx["health"] = health
        ctx["watchdog"] = watchdog
        return {"breaker": gemini_breaker, "health": health, "watchdog": watchdog}

    def _shutdown_reliability(self, instance, ctx: dict):
        pass  # Watchdog runs as daemon thread, stops automatically

    def _init_heartbeat(self, ctx: dict):
        """Phase 10: Initialize heartbeat monitoring."""
        from heartbeat import Heartbeat, NoticeStore
        import config as cfg

        notice_store = NoticeStore(str(VYREN_DIR / "notices.json"))
        heartbeat = Heartbeat(
            notice_store=notice_store,
            config=cfg.get("heartbeat", {
                "enabled": False, "interval_seconds": 300, "checks": []
            }),
            on_notice=lambda n: self._on_heartbeat_notice(n, ctx),
        )
        ctx["heartbeat"] = heartbeat
        ctx["notice_store"] = notice_store
        return heartbeat

    def _on_heartbeat_notice(self, notice: dict, ctx: dict):
        audit = ctx.get("audit")
        event_bus = ctx.get("event_bus")
        if audit:
            audit.info(f"Heartbeat notice: {notice.get('message', '')}")
        if event_bus:
            from event_bus import Event
            event_bus.publish_sync(
                Event(type="heartbeat.notice", source="heartbeat", data=notice)
            )

    def _shutdown_heartbeat(self, instance, ctx: dict):
        instance.stop()

    def _init_tools(self, ctx: dict):
        """Phase 11: Initialize tool registry with all tools."""
        from tools import create_registry

        try:
            registry = create_registry(
                memory_store=ctx["memory"],
                knowledge_graph=ctx["knowledge_graph"],
                scheduler=ctx["scheduler"],
                world_model=ctx["world_model"],
                event_bus=ctx["event_bus"],
                memory_v2=ctx["memory_v2"],
            )
            ctx["registry"] = registry
            return registry
        except ModuleNotFoundError as e:
            # google-genai not installed -- create a minimal registry
            logger.warning(f"Tools init partial (missing {e.name}); creating minimal registry")
            from tools import ToolRegistry
            registry = ToolRegistry()
            ctx["registry"] = registry
            return registry

    def _init_agents(self, ctx: dict):
        """Phase 12: Initialize agent registry with concrete agents."""
        from agents import AgentRegistry, Coordinator
        from agents.developer import DeveloperAgent
        from agents.self_editor import SelfEditorAgent

        registry = AgentRegistry()

        # Create and register concrete agents
        developer = DeveloperAgent()
        developer.set_context(ctx)
        registry.register(developer)

        self_editor = SelfEditorAgent()
        self_editor.set_context(ctx)
        registry.register(self_editor)

        coordinator = Coordinator(registry, shared_context=ctx)

        ctx["agent_registry"] = registry
        ctx["coordinator"] = coordinator
        return coordinator

    def _init_brain(self, ctx: dict):
        """Phase 13: Initialize brain (planner, reasoning engine, system prompt)."""
        from system_prompt import build_system_prompt
        from brain.planner import Planner
        from brain.reasoning import ReasoningEngine

        # Build system prompt
        memory = ctx.get("memory")
        world_model = ctx.get("world_model")
        knowledge_graph = ctx.get("knowledge_graph")
        registry = ctx.get("registry")

        memory_context = memory.build_context() if memory else ""
        world_context = world_model.to_context_string() if world_model else ""
        kg_context = knowledge_graph.to_context_string() if knowledge_graph else ""

        try:
            system_prompt = build_system_prompt(
                memory_context=memory_context,
                world_context=world_context,
                kg_context=kg_context,
            )
        except Exception as e:
            logger.warning(f"System prompt build error: {e}")
            system_prompt = "You are VYREN, an autonomous AI operating system."

        planner = Planner(ctx)
        reasoning = ReasoningEngine(ctx)

        ctx["system_prompt"] = system_prompt
        ctx["planner"] = planner
        ctx["reasoning"] = reasoning

        if registry:
            try:
                ctx["gemini_tools"] = registry.to_gemini_tools()
            except Exception:
                ctx["gemini_tools"] = []
        else:
            ctx["gemini_tools"] = []

        return {"planner": planner, "reasoning": reasoning}

    def _init_connectivity(self, ctx: dict):
        """Phase 15: Initialize connectivity manager."""
        from runtime.connectivity import ConnectivityManager

        cm = ConnectivityManager(ctx)
        cm.start_monitoring()
        ctx["connectivity"] = cm
        return cm

    def _shutdown_connectivity(self, instance, ctx: dict):
        instance.stop_monitoring()

    def _init_voice(self, ctx: dict):
        """Phase 16: Initialize voice runtime."""
        from voice.runtime import VoiceRuntime

        vr = VoiceRuntime(ctx)

        # The startup greeting must not fire until the voice engine has
        # actually connected — starting the engine thread (vr.start()) is
        # NOT the same as the Gemini Live WebSocket handshake completing.
        # Firing on "voice phase started" instead of "voice phase actually
        # connected" was the original bug: speak() was called before
        # self._session existed and silently no-op'd. Hooking the engine's
        # own state-change callback is the correct signal — no polling,
        # no arbitrary sleep.
        vr.on_state_change(self._on_voice_state_for_greeting)

        try:
            vr.start()
        except Exception as exc:
            logger.warning("Voice unavailable at boot: %s", exc)
            vr._fallback_mode = True
            vr._notify_state("fallback")

        ctx["voice_runtime"] = vr

        threading.Thread(
            target=self._greeting_watchdog, name="vyren-greeting-watchdog", daemon=True,
        ).start()

        return vr

    def _shutdown_voice(self, instance, ctx: dict):
        try:
            instance.stop()
        except Exception:
            pass

    def _init_server(self, ctx: dict):
        """Phase 17: Initialize the web server (FastAPI + WebSocket)."""
        from runtime.web_server import WebServer

        ws = WebServer(ctx)
        ws.start()
        ctx["web_server"] = ws
        return ws

    def _shutdown_server(self, instance, ctx: dict):
        instance.stop()

    def _init_service(self, ctx: dict):
        """Phase 18: Initialize service state (PID, crash recovery)."""
        from service import ServiceState

        state = ServiceState(VYREN_DIR / "state.json")
        state.mark_startup()

        # Write PID file
        pid_file = VYREN_DIR / "vyren.pid"
        pid_file.write_text(str(os.getpid()))

        ctx["service_state"] = state
        return state

    def _shutdown_service(self, instance, ctx: dict):
        instance.mark_clean_shutdown()
        pid_file = VYREN_DIR / "vyren.pid"
        if pid_file.exists():
            pid_file.unlink()

    def _init_monitoring(self, ctx: dict):
        """Phase 19: Initialize health monitoring, background tasks, auto-save."""
        from event_bus import Event, VYREN_STARTED

        # Register health checks
        health = ctx.get("health")
        if health:
            # Note: these are placeholder health checks. They don't actually
            # verify subsystem health. They are registered to avoid
            # empty health check errors. Real checks should verify
            # actual subsystem functionality.
            gemini_breaker = ctx.get("gemini_breaker")
            if gemini_breaker:
                health.register("gemini_api",
                                lambda: gemini_breaker.state.value == "closed")

        # Start scheduler
        scheduler = ctx.get("scheduler")
        if scheduler:
            # Register built-in handlers
            def health_check(_ctx):
                status = health.check_all() if health else {}
                degraded = [k for k, v in status.items() if v != "healthy"]
                return f"Degraded: {', '.join(degraded)}" if degraded else "All healthy"

            def watchdog_check(_ctx):
                watchdog = ctx.get("watchdog")
                if watchdog:
                    stuck = watchdog.check()
                    return stuck if stuck else "No stuck operations"
                return "No watchdog"

            def memory_consolidate(_ctx):
                ctx["memory_v2"].consolidate()
                return "Memory consolidation done"

            scheduler.register("health_check", health_check)
            scheduler.register("watchdog_check", watchdog_check)
            scheduler.register("memory_consolidate", memory_consolidate)

            # Schedule periodic jobs
            scheduler.every(name="health_check", handler="health_check",
                            interval_seconds=600, description="Periodic health check")
            scheduler.every(name="memory_consolidate", handler="memory_consolidate",
                            interval_seconds=3600, description="Hourly memory consolidation")
            scheduler.start()

        # Start heartbeat
        heartbeat = ctx.get("heartbeat")
        import config as cfg_mod
        if heartbeat and cfg_mod.get("heartbeat.enabled", False):
            heartbeat.start()

        # Start watchdog
        watchdog = ctx.get("watchdog")
        if watchdog:
            watchdog.on_timeout(
                lambda op: logger.error(
                    f"Watchdog: {op['operation']} stuck "
                    f"({op['elapsed_seconds']}s)"
                )
            )
            watchdog.start_monitoring(interval=15.0)

        # Publish startup event
        event_bus = ctx.get("event_bus")
        if event_bus:
            registry = ctx.get("registry")
            tool_names = registry.tool_names() if registry and hasattr(registry, 'tool_names') else []
            event_bus.publish_sync(
                Event(
                    type=VYREN_STARTED,
                    source="runtime",
                    data={"tool_count": len(tool_names)},
                )
            )

        # Auto-save checkpoint periodically
        def auto_checkpoint():
            while self._running and not self._shutdown_event.is_set():
                self._shutdown_event.wait(timeout=300)  # Every 5 min
                if not self._running:
                    break
                try:
                    ctx["memory_v2"].consolidate()
                    logger.debug("Auto-checkpoint completed")
                except Exception as e:
                    logger.error(f"Auto-checkpoint failed: {e}")

        t = threading.Thread(target=auto_checkpoint, name="auto-checkpoint", daemon=True)
        t.start()

        return True

    def _shutdown_monitoring(self, instance, ctx: dict):
        scheduler = ctx.get("scheduler")
        if scheduler:
            scheduler.stop()
        heartbeat = ctx.get("heartbeat")
        if heartbeat:
            heartbeat.stop()
        event_bus = ctx.get("event_bus")
        if event_bus:
            event_bus.clear_subscribers()

    # ------------------------------------------------------------------
    # Always-On Main Loop
    # ------------------------------------------------------------------

    def _main_loop(self):
        """The always-on main loop. Blocks until shutdown."""
        logger.info("VYREN is now running. Press Ctrl+C to shut down.")

        try:
            import config as cfg
            interaction_cfg = cfg.get("interaction", {})
        except Exception:
            interaction_cfg = {}

        from interaction.conversation_state import (
            BACKGROUND,
            ConversationStateMachine,
            PASSIVE_LISTENING,
        )
        from interaction.interaction_controller import InteractionController
        sm = ConversationStateMachine()
        ctrl = InteractionController(sm, interaction_cfg)
        boot_state = ctrl.state_machine.state
        if boot_state == sm.state:
            boot_state = sm.transition(BACKGROUND)
        self._services["interaction_controller"] = ctrl

        self._print_status_banner()

        self._boot_ready.set()

        from runtime.terminal import start_terminal_loop
        start_terminal_loop(self._services, self._shutdown_event, interaction_controller=self._services.get("interaction_controller"))

        while self._running and not self._shutdown_event.is_set():
            try:
                self._check_proactive_assistance()

                self._shutdown_event.wait(timeout=2.0)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                self._shutdown_event.wait(timeout=5.0)

        self.shutdown()

    def _supervisor_loop(self):
        """Background thread that supervises all services."""
        while self._running and not self._shutdown_event.is_set():
            try:
                self._shutdown_event.wait(timeout=self._health_interval)
                if not self._running:
                    break
                self._health_check_all()
            except Exception as e:
                logger.error(f"Supervisor error: {e}")
                self._shutdown_event.wait(timeout=10)

    def _health_check_all(self):
        """Check health of all services and attempt recovery."""
        if not self._boot_manager:
            return

        for name, svc in self._boot_manager._services.items():
            if not svc.is_running and svc.restart_on_failure:
                logger.warning(f"Service {name} is not running. Attempting restart...")
                try:
                    if svc.shutdown_fn and svc._instance:
                        svc.shutdown_fn(svc._instance, self._boot_manager.ctx)
                except Exception:
                    pass
                svc._state = "stopped"
                svc._error = None
                # Re-initialize
                try:
                    instance = svc.init_fn(self._boot_manager.ctx)
                    svc.set_instance(instance)
                    if isinstance(instance, dict):
                        self._services.update(instance)
                    else:
                        self._services[name] = instance
                    logger.info(f"Service {name} restarted successfully")
                except Exception as e:
                    logger.error(f"Service {name} restart failed: {e}")
                    svc.mark_failed(str(e))

    def _check_proactive_assistance(self):
        """Check for pending notices and log NEW ones only (no spam)."""
        notice_store = self._services.get("notice_store")
        if not notice_store:
            return

        pending = notice_store.get_pending()
        if not pending:
            return

        for notice in pending:
            notice_id = notice.get("id", "")
            # Only log each notice ONCE — don't spam the same alert every loop
            if notice_id in self._logged_notice_ids:
                continue

            urgency = notice.get("urgency", "low")
            message = notice.get("message", "")

            if urgency == "high":
                logger.warning("[Proactive] %s", message)
            elif urgency == "medium":
                logger.info("[Proactive] %s", message)

            self._logged_notice_ids.add(notice_id)

    def _print_status_banner(self):
        """Print the dashboard/status block immediately at startup.

        Deliberately does NOT include the spoken greeting text — that's
        generated asynchronously once the voice engine actually connects
        (see _run_startup_greeting). Printing this immediately keeps the
        console feeling responsive even while the greeting is still being
        composed in the background.
        """
        registry = self._services.get("registry")
        tool_count = len(registry.tool_names()) if registry and hasattr(registry, 'tool_names') else 0
        ollama = False
        try:
            from provider import _ollama_available
            ollama = _ollama_available()
        except Exception:
            pass

        voice_rt = self._services.get("voice_runtime")
        voice_mode = voice_rt.mode if voice_rt and voice_rt.is_active else "off"

        print()
        try:
            from identity import get_assistant_name, get_wake_word
            assistant_name = get_assistant_name()
            wake_word = get_wake_word()
        except Exception:
            assistant_name = "VYREN"
            wake_word = "vyren"
        print(f"  {assistant_name} is online.")
        print(f"  Voice: {voice_mode}")
        print(f"  Tools: {tool_count} loaded")
        print(f"  Ollama: {'available' if ollama else 'not running'}")
        print(f"  Dashboard: http://localhost:{self._services.get('server_port', 8420)}")
        print(f"  Text input available.")
        print()

    def _on_voice_state_for_greeting(self, state: str):
        """Callback registered on the voice runtime — fires the greeting
        the moment the voice engine is genuinely ready to speak, instead
        of the instant boot() returns (which is what silently dropped
        every greeting before: the engine thread had started, but the
        Gemini Live WebSocket handshake hadn't finished, so send_text()
        found no session and no-op'd).

        Fires on "listening" (Gemini Live connected) or "fallback" (no
        API key / offline — local TTS path) — either way, VYREN is now
        actually capable of speaking.
        """
        if state not in ("listening", "fallback"):
            return
        try:
            ctrl = self._services.get("interaction_controller")
            if ctrl is not None:
                ctrl.set_user_mode("conversation")
        except Exception:
            pass
        self._fire_greeting_once()

    def _greeting_watchdog(self):
        """Belt-and-suspenders: if the voice runtime never reports a
        speakable state at all (missing sounddevice, stuck reconnect
        loop, voice disabled entirely), fire the greeting anyway after a
        bounded wait so VYREN is never silently mute for the whole
        session over an edge case this module didn't anticipate.
        """
        if self._greeting_fired.wait(timeout=20.0):
            return  # Already fired via the normal state-change path
        self._fire_greeting_once()

    def _fire_greeting_once(self):
        if self._greeting_fired.is_set():
            return
        self._greeting_fired.set()
        threading.Thread(
            target=self._run_startup_greeting, name="vyren-greeting", daemon=True,
        ).start()

    def _run_startup_greeting(self):
        """Build and speak the startup greeting.

        Runs off the main thread so a slow network call can never delay
        boot or block the voice engine's own event loop.
        """
        self._boot_ready.wait(timeout=15.0)

        try:
            import config as cfg
            if not cfg.get("interaction.startup_speak_greeting", False):
                return
        except Exception:
            return

        try:
            from brain.greeting_engine import GreetingManager
            gm = GreetingManager(self._services)
            greeting = asyncio.run(gm.generate_async(timeout=4.0))
        except Exception as e:
            logger.debug(f"Greeting generation failed, using fallback: {e}")
            greeting = "VYREN is online."

        print(f"  {greeting}\n")

        voice_rt = self._services.get("voice_runtime")
        if voice_rt is not None:
            if voice_rt.is_active:
                voice_rt.speak(greeting)
            elif getattr(voice_rt, "mode", None) == "fallback":
                try:
                    voice_rt._speak_fallback(greeting)
                except Exception as exc:
                    logger.debug("Fallback greeting speak failed: %s", exc)
                    print(f"  [Fallback TTS unavailable: {exc}]")

    # ------------------------------------------------------------------
    # Signal Handling
    # ------------------------------------------------------------------

    def _install_signal_handlers(self):
        """Install graceful shutdown signal handlers."""
        original_sigint = [None]

        def sigint_handler(signum, frame):
            # First Ctrl+C: graceful shutdown
            if self._running:
                logger.info("Received SIGINT. Shutting down gracefully...")
                print("\n\n  Shutting down VYREN...\n")
                self.shutdown()
            else:
                # Second Ctrl+C: force exit
                logger.info("Forced exit")
                os._exit(1)

        def sigterm_handler(signum, frame):
            logger.info("Received SIGTERM. Shutting down...")
            self.shutdown()

        try:
            signal.signal(signal.SIGINT, sigint_handler)
            signal.signal(signal.SIGTERM, sigterm_handler)
        except (OSError, ValueError):
            # Not supported on this platform (e.g., Windows threads)
            pass