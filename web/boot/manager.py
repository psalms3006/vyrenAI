"""
boot/manager.py -- VYREN Boot Manager.

Responsible for ordered, dependency-aware initialization and shutdown
of every subsystem in the VYREN AI operating system.

Startup phases (in order):
  1. config        -- Load configuration
  2. logging       -- Initialize structured logging
  3. audit         -- Structured audit trail
  4. event_bus     -- Central pub/sub event bus
  5. memory        -- Persistent memory (v1 + v2)
  6. knowledge_graph -- Semantic knowledge graph
  7. world_model   -- User environment model
  8. scheduler     -- Job scheduler
  9. reliability   -- Circuit breakers, health monitor, watchdog
 10. heartbeat     -- Proactive system monitoring
 11. tools         -- Tool registry
 12. agents        -- Agent registry + coordinator
 13. brain         -- Planner, reasoning engine
 14. connectivity  -- Online/offline manager
 15. voice         -- Voice runtime (wake-word, continuous, Gemini Live)
 16. server        -- FastAPI + WebSocket dashboard
 17. service       -- PID file, crash recovery, state persistence
 18. monitoring    -- Health verification, auto-restart

No manual startup of any component should ever be required.
"""

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("vyren.boot")


class Phase(IntEnum):
    """Boot phases in strict startup order."""
    CONFIG = 1
    LOGGING = 2
    AUDIT = 3
    EVENT_BUS = 4
    MEMORY = 5
    KNOWLEDGE_GRAPH = 6
    WORLD_MODEL = 7
    SCHEDULER = 8
    RELIABILITY = 9
    HEARTBEAT = 10
    TOOLS = 11
    AGENTS = 12
    BRAIN = 13
    CONNECTIVITY = 14
    VOICE = 15
    SERVER = 16
    SERVICE = 17
    MONITORING = 18


@dataclass
class ServiceDescriptor:
    """Describes a bootable service."""
    name: str
    phase: Phase
    init_fn: Callable
    shutdown_fn: Callable | None = None
    critical: bool = False
    dependencies: list[str] = field(default_factory=list)
    restart_on_failure: bool = False
    max_restarts: int = 3
    _instance: Any = field(default=None, repr=False)
    _state: str = "stopped"  # stopped, starting, running, failed, stopping
    _restart_count: int = field(default=0, repr=False)
    _error: str | None = field(default=None, repr=False)

    @property
    def is_running(self) -> bool:
        return self._state == "running"

    @property
    def is_critical(self) -> bool:
        return self.critical

    def set_instance(self, instance: Any):
        self._instance = instance
        self._state = "running"

    def mark_failed(self, error: str):
        self._error = error
        self._state = "failed"

    def mark_stopped(self):
        self._state = "stopped"
        self._error = None


class BootManager:
    """
    Orchestrates the full VYREN boot sequence.

    Usage (from main.py):
        boot = BootManager()
        runtime = boot.boot()
        # runtime holds references to every subsystem
    """

    def __init__(self):
        self._services: dict[str, ServiceDescriptor] = {}
        self._startup_log: list[dict] = []
        self._boot_start: datetime | None = None
        self._boot_end: datetime | None = None
        self._ctx: dict = {}  # Shared context for all subsystems

    def register(self, name: str, phase: Phase, init_fn: Callable,
                 shutdown_fn: Callable | None = None,
                 critical: bool = False,
                 dependencies: list[str] | None = None,
                 restart_on_failure: bool = False,
                 max_restarts: int = 3):
        """Register a service to be initialized during boot."""
        self._services[name] = ServiceDescriptor(
            name=name,
            phase=phase,
            init_fn=init_fn,
            shutdown_fn=shutdown_fn,
            critical=critical,
            dependencies=dependencies or [],
            restart_on_failure=restart_on_failure,
            max_restarts=max_restarts,
        )

    def get(self, name: str) -> Any:
        """Get a service instance by name (after boot)."""
        svc = self._services.get(name)
        if svc and svc._instance is not None:
            return svc._instance
        return None

    @property
    def ctx(self) -> dict:
        """Shared context dictionary accessible by all subsystems."""
        return self._ctx

    @property
    def boot_duration_ms(self) -> int:
        if self._boot_start and self._boot_end:
            return int((self._boot_end - self._boot_start).total_seconds() * 1000)
        return 0

    def boot(self) -> dict:
        """
        Execute the full boot sequence. Returns the shared context
        dictionary with all subsystem references.

        If a critical service fails, boot is aborted.
        Non-critical services log the failure and continue.
        """
        self._boot_start = datetime.now(timezone.utc)
        logger.info("=" * 60)
        logger.info("VYREN OS Boot Sequence Starting")
        logger.info("=" * 60)

        # Verify dependency graph
        self._validate_dependencies()

        # Execute phases in order
        for phase in Phase:
            phase_services = [
                svc for svc in self._services.values()
                if svc.phase == phase
            ]
            for svc in phase_services:
                self._start_service(svc)

        self._boot_end = datetime.now(timezone.utc)
        duration = self.boot_duration_ms

        # Summary
        running = sum(1 for s in self._services.values() if s.is_running)
        failed = sum(1 for s in self._services.values() if s._state == "failed")
        logger.info("=" * 60)
        logger.info(f"VYREN OS Boot Complete -- {running} services running, "
                     f"{failed} failed, {duration}ms")
        logger.info("=" * 60)

        return self._ctx

    def shutdown(self):
        """Shut down all services in reverse phase order."""
        logger.info("VYREN OS Shutting Down...")

        for phase in reversed(list(Phase)):
            phase_services = [
                svc for svc in self._services.values()
                if svc.phase == phase
            ]
            for svc in phase_services:
                self._stop_service(svc)

        logger.info("VYREN OS Stopped")

    def get_status(self) -> dict:
        """Get the status of all registered services."""
        return {
            name: {
                "phase": svc.phase.name,
                "state": svc._state,
                "critical": svc.critical,
                "error": svc._error,
                "restart_count": svc._restart_count,
            }
            for name, svc in self._services.items()
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _validate_dependencies(self):
        """Verify all dependency references exist."""
        for name, svc in self._services.items():
            for dep in svc.dependencies:
                if dep not in self._services:
                    raise RuntimeError(
                        f"Service '{name}' depends on '{dep}', "
                        f"which is not registered."
                    )

    def _start_service(self, svc: ServiceDescriptor):
        """Start a single service with error handling and restart logic."""
        logger.info(f"[Phase {svc.phase:02d}] Starting {svc.name}...")

        # Check dependencies
        for dep in svc.dependencies:
            dep_svc = self._services.get(dep)
            if dep_svc and not dep_svc.is_running:
                if dep_svc.critical:
                    msg = f"Critical dependency '{dep}' not running; skipping {svc.name}"
                    logger.error(msg)
                    svc.mark_failed(msg)
                    return
                else:
                    logger.warning(f"Dependency '{dep}' not running; starting {svc.name} anyway")

        svc._state = "starting"
        start_time = time.time()

        for attempt in range(svc.max_restarts + 1):
            try:
                instance = svc.init_fn(self._ctx)
                svc.set_instance(instance)
                svc._restart_count = attempt
                elapsed = (time.time() - start_time) * 1000
                logger.info(f"[Phase {svc.phase:02d}] {svc.name} ready ({elapsed:.0f}ms)")
                self._startup_log.append({
                    "service": svc.name,
                    "phase": svc.phase.name,
                    "duration_ms": int(elapsed),
                    "attempt": attempt + 1,
                    "success": True,
                })
                return
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                elapsed = (time.time() - start_time) * 1000
                logger.error(f"[Phase {svc.phase:02d}] {svc.name} failed: {error_msg}")
                svc._restart_count = attempt + 1

                if attempt < svc.max_restarts and svc.restart_on_failure:
                    logger.info(f"[Phase {svc.phase:02d}] Restarting {svc.name} (attempt {attempt + 2})...")
                    time.sleep(1 * (attempt + 1))  # Exponential backoff
                    continue

                break

        svc.mark_failed(error_msg)
        self._startup_log.append({
            "service": svc.name,
            "phase": svc.phase.name,
            "duration_ms": int(elapsed),
            "attempt": svc._restart_count,
            "success": False,
            "error": error_msg,
        })

        if svc.critical:
            logger.critical(f"CRITICAL service {svc.name} failed. Aborting boot.")
            self.shutdown()
            sys.exit(1)

    def _stop_service(self, svc: ServiceDescriptor):
        """Stop a single service."""
        if not svc.is_running:
            return
        svc._state = "stopping"
        try:
            if svc.shutdown_fn:
                svc.shutdown_fn(svc._instance, self._ctx)
            svc.mark_stopped()
            logger.info(f"[Shutdown] {svc.name} stopped")
        except Exception as e:
            logger.error(f"[Shutdown] Error stopping {svc.name}: {e}")
            svc.mark_failed(str(e))