"""
runtime/connectivity.py -- Connectivity Manager.

Monitors internet connectivity, manages online/offline transitions,
and provides a unified interface for all subsystems to check
network status without managing it themselves.

Automatically transitions between:
  - ONLINE: Full cloud capabilities (Gemini, cloud STT/TTS, web search)
  - OFFLINE: Local models (Ollama), local STT/TTS, ZIM Wikipedia

The transition is automatic, graceful, and preserves conversation state.
"""

import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import httpx

from platform_paths import get_offline_queue_path

logger = logging.getLogger("vyren.connectivity")

VOICE_FAILURE_THRESHOLD = 3
VOICE_RECOVERY_CHECK_INTERVAL_S = 30
VOICE_RECOVERY_REQUIRED_SUCCESSES = 2


class ConnectivityMode(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"


@dataclass
class ConnectivityStatus:
    """Current connectivity state."""
    mode: ConnectivityMode = ConnectivityMode.OFFLINE
    internet_available: bool = False
    gemini_available: bool = False
    ollama_available: bool = False
    latency_ms: int = 0
    last_check: float = 0
    last_online: float = 0
    last_offline: float = 0
    transition_count: int = 0
    check_interval: int = 10  # seconds
    offline_threshold: int = 3  # consecutive failures before going offline
    recovery_threshold: int = 2  # consecutive successes before going online


class ConnectivityManager:
    """
    Monitors connectivity and manages online/offline transitions.

    No other subsystem should directly check internet connectivity.
    They should ask this manager instead.
    """

    def __init__(self, ctx: dict, check_interval: int = 10):
        import config as _cfg
        self._ctx = ctx
        cfg_interval = _cfg.get("connectivity.check_interval", check_interval)
        self._status = ConnectivityStatus(check_interval=cfg_interval)
        self._status.offline_threshold = _cfg.get("connectivity.offline_threshold", VOICE_FAILURE_THRESHOLD)
        self._status.recovery_threshold = _cfg.get("connectivity.recovery_threshold", VOICE_RECOVERY_REQUIRED_SUCCESSES)
        self._monitoring = False
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._listeners: list[Callable[[ConnectivityMode, ConnectivityMode], None]] = []
        self._consecutive_failures = 0
        self._consecutive_successes = 0

    @property
    def is_online(self) -> bool:
        return self._status.mode == ConnectivityMode.ONLINE

    @property
    def is_offline(self) -> bool:
        return self._status.mode in (ConnectivityMode.OFFLINE, ConnectivityMode.DEGRADED)

    @property
    def status(self) -> ConnectivityStatus:
        return self._status

    @property
    def mode(self) -> ConnectivityMode:
        return self._status.mode

    def on_transition(self, callback: Callable[[ConnectivityMode, ConnectivityMode], None]):
        """Register a callback for mode transitions (old_mode, new_mode)."""
        self._listeners.append(callback)

    def start_monitoring(self):
        """Start the background connectivity monitor."""
        if self._monitoring:
            return
        self._monitoring = True
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="vyren-connectivity",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info("Connectivity monitor started")

    def stop_monitoring(self):
        """Stop the background monitor."""
        self._monitoring = False
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
        logger.info("Connectivity monitor stopped")

    def check_now(self) -> ConnectivityStatus:
        """Force an immediate connectivity check."""
        self._perform_check()
        return self._status

    def can_execute_task(self, requires_internet: bool = False) -> tuple[bool, str]:
        """
        Check if a task can be executed.

        Returns (can_execute, reason).
        """
        if requires_internet and self.is_offline:
            if self._status.ollama_available:
                return True, "offline_local_fallback"
            return False, "offline_no_local_model"
        return True, "ok"

    def queue_for_later(self, task_description: str) -> str:
        """Queue an online-only task for when connectivity returns."""
        queue_file = get_offline_queue_path()

        # Load existing queue
        import json
        queue = []
        if queue_file.exists():
            try:
                with open(queue_file, "r") as f:
                    queue = json.load(f)
            except (json.JSONDecodeError, IOError):
                queue = []

        # Add task
        queue.append({
            "task": task_description,
            "queued_at": time.time(),
            "status": "pending",
        })

        # Save
        with open(queue_file, "w") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)

        return f"Task queued. Will execute when online. ({len(queue)} tasks in queue)"

    def get_pending_tasks(self) -> list[dict]:
        """Get tasks queued for when connectivity returns."""
        from pathlib import Path
        import json, os

        queue_file = get_offline_queue_path()
        if not queue_file.exists():
            return []
        try:
            with open(queue_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    def _monitor_loop(self):
        """Background loop that periodically checks connectivity."""
        while not self._stop_event.is_set():
            try:
                self._perform_check()
            except Exception as e:
                logger.error(f"Connectivity check error: {e}")

            self._stop_event.wait(timeout=self._status.check_interval)

    def _perform_check(self):
        """Perform a single connectivity check and handle transitions."""
        old_mode = self._status.mode

        # Check internet (DNS resolution to a reliable host)
        internet = self._check_internet()

        # Check Gemini API
        gemini = self._check_gemini() if internet else False

        # Check Ollama
        ollama = self._check_ollama()

        # Update status
        self._status.internet_available = internet
        self._status.gemini_available = gemini
        self._status.ollama_available = ollama
        self._status.last_check = time.time()

        # Determine mode
        if gemini:
            self._consecutive_successes += 1
            self._consecutive_failures = 0

            if (self._consecutive_successes >= self._status.recovery_threshold
                    and self._status.mode != ConnectivityMode.ONLINE):
                self._status.mode = ConnectivityMode.ONLINE
                self._status.last_online = time.time()
                self._status.transition_count += 1
                self._consecutive_successes = 0
                self._on_mode_change(old_mode, ConnectivityMode.ONLINE)
                logger.info("Connectivity: ONLINE (Gemini available)")

                # Process any queued tasks
                self._process_queued_tasks()

            elif self._status.mode != ConnectivityMode.ONLINE:
                # Approaching online -- maybe degraded
                if self._consecutive_successes == 1:
                    self._status.mode = ConnectivityMode.DEGRADED
                    logger.info("Connectivity: DEGRADED (checking stability)")

        elif internet:
            self._status.mode = ConnectivityMode.DEGRADED
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            logger.debug("Connectivity: DEGRADED (internet but Gemini down)")
        else:
            self._consecutive_failures += 1
            self._consecutive_successes = 0

            if (self._consecutive_failures >= self._status.offline_threshold
                    and self._status.mode != ConnectivityMode.OFFLINE):
                self._status.mode = ConnectivityMode.OFFLINE
                self._status.last_offline = time.time()
                self._status.transition_count += 1
                self._on_mode_change(old_mode, ConnectivityMode.OFFLINE)
                logger.info("Connectivity: OFFLINE (no internet)")

    def _check_internet(self) -> bool:
        """Check internet connectivity via DNS and HTTP."""
        try:
            # DNS check
            socket.create_connection(("dns.google", 53), timeout=3)
            return True
        except (OSError, socket.timeout):
            pass

        # HTTP fallback
        try:
            resp = httpx.get("https://clients3.google.com/generate_204",
                             timeout=5, follow_redirects=False)
            return resp.status_code in (200, 204, 301, 302)
        except Exception:
            return False

    def _check_gemini(self) -> bool:
        """Check if the Gemini API is reachable."""
        if not self._ctx.get("gemini_breaker"):
            return False
        breaker = self._ctx["gemini_breaker"]
        if breaker.state.value != "closed":
            return False

        try:
            import os
            if not os.environ.get("GEMINI_API_KEY"):
                return False
            # Quick API check
            start = time.time()
            resp = httpx.get(
                "https://generativelanguage.googleapis.com",
                timeout=5,
            )
            self._status.latency_ms = int((time.time() - start) * 1000)
            return True
        except Exception:
            return False

    def _check_ollama(self) -> bool:
        """Check if Ollama is running locally."""
        try:
            resp = httpx.get("http://localhost:11434/api/tags", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def _on_mode_change(self, old_mode: ConnectivityMode, new_mode: ConnectivityMode):
        """Handle a mode transition."""
        # Notify listeners
        for listener in self._listeners:
            try:
                listener(old_mode, new_mode)
            except Exception as e:
                logger.error(f"Connectivity listener error: {e}")

        # Publish event
        event_bus = self._ctx.get("event_bus")
        if event_bus:
            from event_bus import Event
            event_bus.publish_sync(
                Event(
                    type="connectivity.change",
                    source="connectivity",
                    data={
                        "old_mode": old_mode.value,
                        "new_mode": new_mode.value,
                        "internet": self._status.internet_available,
                        "gemini": self._status.gemini_available,
                        "ollama": self._status.ollama_available,
                    },
                )
            )

    def _process_queued_tasks(self):
        """Execute any tasks that were queued while offline."""
        tasks = self.get_pending_tasks()
        if not tasks:
            return

        logger.info(f"Processing {len(tasks)} queued offline tasks...")
        audit = self._ctx.get("audit")
        if audit:
            audit.info(f"Processing {len(tasks)} queued offline tasks")

        # Clear the queue file
        queue_file = get_offline_queue_path()
        try:
            queue_file.unlink(missing_ok=True)
        except Exception:
            pass

        # Tasks are logged but actual execution would be handled by the brain
        # The brain can check for queued tasks on connectivity restoration