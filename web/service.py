"""
service.py — VYREN daemon/service mode.

Makes VYREN a continuously running operating system service instead of a
program that only exists while a chat window is open. Handles:
  - graceful startup (load all subsystems in order)
  - graceful shutdown (save state, stop threads, close connections)
  - crash recovery (detect unclean shutdown, restore state)
  - state persistence (save/restore operational state across restarts)
  - PID file management (prevent duplicate instances)
"""

import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("vyren.service")

# Default VYREN data directory
VYREN_DIR = Path(os.path.expanduser("~/.vyren"))
PID_FILE = VYREN_DIR / "vyren.pid"
STATE_FILE = VYREN_DIR / "state.json"


class ServiceState:
    """Persistent state that survives restarts."""

    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._data = {}

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value
        self._save()

    def delete(self, key: str):
        self._data.pop(key, None)
        self._save()

    @property
    def last_shutdown(self) -> str | None:
        return self.get("last_shutdown")

    @property
    def last_startup(self) -> str | None:
        return self.get("last_startup")

    @property
    def clean_shutdown(self) -> bool:
        return self.get("clean_shutdown", True)

    @property
    def crash_count(self) -> int:
        return self.get("crash_count", 0)

    def mark_startup(self):
        now = datetime.now(timezone.utc).isoformat()
        self.set("last_startup", now)
        self.set("clean_shutdown", False)
        logger.info(f"Service starting (previous: {self.last_shutdown or 'first run'})")

    def mark_clean_shutdown(self):
        now = datetime.now(timezone.utc).isoformat()
        self.set("last_shutdown", now)
        self.set("clean_shutdown", True)

    def mark_crash(self):
        count = self.crash_count + 1
        self.set("crash_count", count)
        logger.warning(f"Unclean shutdown detected. Total crashes: {count}")


class VYRENService:
    """
    Manages VYREN's lifecycle as a persistent service.

    Subsystems register startup and shutdown hooks. The service runs them
    in order on startup (reverse order on shutdown) and handles signals
    for graceful termination.

    Usage:
        service = VYRENService()

        service.on_startup("memory", init_memory)
        service.on_startup("event_bus", init_event_bus)
        service.on_shutdown("event_bus", shutdown_event_bus)
        service.on_shutdown("memory", save_memory)

        service.start()  # Blocks until shutdown signal
    """

    def __init__(self):
        self.state = ServiceState()
        self._startup_hooks: list[tuple[str, Callable, int]] = []  # (name, fn, order)
        self._shutdown_hooks: list[tuple[str, Callable, int]] = []
        self._running = False
        self._pid = os.getpid()
        self._threads: list[threading.Thread] = []
        self._subsystems: dict[str, Any] = {}  # Named subsystem references

        # Check for previous crash
        if not self.state.clean_shutdown and self.state.last_startup:
            self.state.mark_crash()

    def on_startup(self, name: str, fn: Callable, order: int = 50):
        """Register a startup hook. Lower order = runs first."""
        self._startup_hooks.append((name, fn, order))
        self._startup_hooks.sort(key=lambda x: x[2])

    def on_shutdown(self, name: str, fn: Callable, order: int = 50):
        """Register a shutdown hook. Lower order = runs first."""
        self._shutdown_hooks.append((name, fn, order))
        self._shutdown_hooks.sort(key=lambda x: x[2])

    def register_subsystem(self, name: str, subsystem: Any):
        """Register a subsystem for cross-module access."""
        self._subsystems[name] = subsystem

    def get_subsystem(self, name: str) -> Any:
        """Get a registered subsystem."""
        return self._subsystems.get(name)

    def start_background_thread(self, target: Callable, name: str, daemon: bool = True) -> threading.Thread:
        """Start a background thread tracked by the service."""
        t = threading.Thread(target=target, name=name, daemon=daemon)
        t.start()
        self._threads.append(t)
        return t

    def _write_pid(self):
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(self._pid))

    def _remove_pid(self):
        if PID_FILE.exists():
            PID_FILE.unlink()

    def _check_pid(self) -> bool:
        """Check if another VYREN instance is running."""
        if not PID_FILE.exists():
            return False
        try:
            old_pid = int(PID_FILE.read_text().strip())
            # Check if process exists
            os.kill(old_pid, 0)
            return True  # Process exists
        except (ValueError, ProcessLookupError, PermissionError):
            PID_FILE.unlink()
            return False

    def _install_signal_handlers(self):
        """Install graceful shutdown handlers."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.shutdown()

    def start(self):
        """Start the VYREN service. Blocks until shutdown."""
        if self._check_pid():
            old_pid = PID_FILE.read_text().strip()
            raise RuntimeError(
                f"VYREN is already running (PID {old_pid}). "
                f"Stop it first, or delete {PID_FILE} if it's a stale lock."
            )

        self._write_pid()
        self._install_signal_handlers()
        self.state.mark_startup()

        logger.info("VYREN service starting...")

        # Run startup hooks
        for name, fn, _ in self._startup_hooks:
            try:
                logger.info(f"Starting subsystem: {name}")
                fn()
                logger.info(f"Subsystem ready: {name}")
            except Exception as e:
                logger.error(f"Failed to start {name}: {e}")
                if name in ("config", "memory"):  # Critical subsystems
                    self.shutdown()
                    raise

        self._running = True
        logger.info("VYREN service is running.")

        # Block main thread
        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self):
        """Gracefully shut down all subsystems."""
        if not self._running:
            return
        self._running = False
        logger.info("VYREN service shutting down...")

        # Run shutdown hooks in reverse registration order
        for name, fn, _ in reversed(self._shutdown_hooks):
            try:
                logger.info(f"Stopping subsystem: {name}")
                fn()
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")

        # Wait for background threads (briefly)
        for t in self._threads:
            if t.is_alive() and t.daemon:
                t.join(timeout=2)

        self.state.mark_clean_shutdown()
        self._remove_pid()
        logger.info("VYREN service stopped.")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def uptime_seconds(self) -> float:
        """Seconds since last startup."""
        if not self.state.last_startup:
            return 0
        try:
            started = datetime.fromisoformat(self.state.last_startup)
            return (datetime.now(timezone.utc) - started).total_seconds()
        except Exception:
            return 0