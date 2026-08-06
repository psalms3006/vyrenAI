"""
voice_engine/voice_supervisor.py -- Voice Supervisor.

Monitors:
- microphone health
- playback health
- websocket/transport health
- Gemini session
- audio queues
- streaming latency

Automatically recovers unhealthy components without tearing down the
entire session when a single worker hiccups.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("vyren.voice.supervisor")


class VoiceSupervisor:
    """
    Observes engine state and triggers lightweight recovery actions.

    This does NOT replace the engine's internal supervisor; it adds
    higher-level health checks that are awkward to express inside the
    engine itself because they cross worker/queue/state boundaries.
    """

    def __init__(
        self,
        *,
        engine: Any = None,
        conversation_manager: Any = None,
        clock: Callable[[], float] = time.monotonic,
        check_interval: float = 2.0,
        max_queue_age_seconds: float = 1.5,
        max_websocket_silence_seconds: float = 8.0,
        reconnect_cooldown_seconds: float = 20.0,
    ):
        self._engine = engine
        self._conversation_manager = conversation_manager
        self._clock = clock
        self._check_interval = check_interval
        self._max_queue_age_seconds = max_queue_age_seconds
        self._max_websocket_silence_seconds = max_websocket_silence_seconds
        self._reconnect_cooldown_seconds = reconnect_cooldown_seconds

        self._active = False
        self._stop_event: Any = None
        self._thread: Any = None

        # Recovery signal handles
        self._on_reconnect: Optional[Callable[[], None]] = None
        self._on_reset_queues: Optional[Callable[[], None]] = None
        self._on_mic_restart: Optional[Callable[[], None]] = None
        self._on_speaker_restart: Optional[Callable[[], None]] = None

        self._last_reconnect_attempt: float = 0.0

    def set_recovery_handlers(
        self,
        *,
        on_reconnect: Optional[Callable[[], None]] = None,
        on_reset_queues: Optional[Callable[[], None]] = None,
        on_mic_restart: Optional[Callable[[], None]] = None,
        on_speaker_restart: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_reconnect = on_reconnect
        self._on_reset_queues = on_reset_queues
        self._on_mic_restart = on_mic_restart
        self._on_speaker_restart = on_speaker_restart

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, stop_event: Any) -> None:
        self._active = True
        self._stop_event = stop_event
        self._last_reconnect_attempt = 0.0

        import threading
        self._thread = threading.Thread(target=self._run, name="vyren-voice-supervisor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._active = False
        if self._stop_event is not None:
            self._stop_event.set()

    def wait(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        logger.info("[SUPERVISOR] Started")
        while self._active and not self._stop_event.is_set():
            try:
                self._check()
            except Exception as e:
                logger.debug("[SUPERVISOR] Check error: %s", e)
            self._stop_event.wait(timeout=self._check_interval)
        logger.info("[SUPERVISOR] Stopped")

    def _check(self) -> None:
        if self._engine is None:
            return

        now = self._clock()
        self._check_queues(now)
        self._check_transport_latency(now)

        conv = self._conversation_manager
        if conv is not None and getattr(conv, "is_reconnecting", False):
            return

        if self._should_reconnect(now):
            if now - self._last_reconnect_attempt > self._reconnect_cooldown_seconds:
                self._last_reconnect_attempt = now
                self._recover("transport silent too long")

    def _check_queues(self, now: float) -> None:
        engine = self._engine
        try:
            speaker_queue = getattr(engine, "_speaker_queue", None)
            mic_queue = getattr(engine, "_mic_queue", None)

            speaker_age = self._queue_age(speaker_queue, now)
            mic_age = self._queue_age(mic_queue, now)

            if speaker_age is not None and speaker_age > self._max_queue_age_seconds:
                if self._on_speaker_restart is not None:
                    try:
                        self._on_speaker_restart()
                    except Exception as e:
                        logger.debug("[SUPERVISOR] speaker restart failed: %s", e)

            if mic_age is not None and mic_age > self._max_queue_age_seconds:
                if self._on_mic_restart is not None:
                    try:
                        self._on_mic_restart()
                    except Exception as e:
                        logger.debug("[SUPERVISOR] mic restart failed: %s", e)
        except Exception:
            pass

    def _check_transport_latency(self, now: float) -> None:
        try:
            last = getattr(self._engine, "_last_receive_ts", None)
            if last is None:
                return
            if now - last > self._max_websocket_silence_seconds:
                self._recover("websocket receive silent")
        except Exception:
            pass

    def _should_reconnect(self, now: float) -> bool:
        try:
            state = getattr(self._engine, "state", None)
            if state is None:
                return False
            value = str(getattr(state, "value", state))
            if value in ("failed", "reconnecting", "failed"):
                return False
            return True
        except Exception:
            return False

    def _recover(self, reason: str) -> None:
        logger.warning("[SUPERVISOR] Recovering session: %s", reason)
        if self._on_reset_queues is not None:
            try:
                self._on_reset_queues()
            except Exception as e:
                logger.debug("[SUPERVISOR] queue reset failed: %s", e)
        if self._on_reconnect is not None:
            try:
                self._on_reconnect()
            except Exception as e:
                logger.debug("[SUPERVISOR] reconnect handler failed: %s", e)

    @staticmethod
    def _queue_age(queue: Any, now: float) -> Optional[float]:
        try:
            if queue is None:
                return None
            if hasattr(queue, "qsize"):
                if queue.qsize() == 0:
                    return 0.0
                # asyncio queues do not expose oldest-item timestamps;
                # treat non-empty as unknown age rather than inventing
                # timing from internal structures.
                return None
            q = getattr(queue, "_queue", None)
            if q is None:
                return None
            if not q:
                return 0.0
            newest = max(item[1] for item in q.queue if hasattr(item, "__len__") and len(item) >= 2)
            return now - newest
        except Exception:
            return None
