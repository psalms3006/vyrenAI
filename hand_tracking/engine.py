"""
hand_tracking/engine.py -- Hand tracking engine for VYREN.

Architecture:
- HandTrackingEngine
  - Worker: backend frame pump → HandTracker → GestureRecognizer
  - Result storage: bounded thread-safe deque
  - Observer: event_bus + optional external handlers
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from hand_tracking import GestureEvent, GestureRecognizer, Hand, HandBackend, SyntheticHandBackend

logger = logging.getLogger("vyren.hand_tracking.engine")


@dataclass
class HandTrackingConfig:
    backend: str = "synthetic"
    max_queue_size: int = 64
    max_result_history: int = 128
    min_confidence: float = 0.5
    gesture_cooldown_seconds: float = 0.35


class HandTrackingEngine:
    def __init__(self, config: HandTrackingConfig | None = None, event_bus: Any = None) -> None:
        self._config = config or HandTrackingConfig()
        self._event_bus = event_bus
        self._backend: Optional[HandBackend] = None
        self._recognizer = GestureRecognizer()
        self._history: deque[GestureEvent] = deque(maxlen=self._config.max_result_history)
        self._observers: list[Callable[[GestureEvent], None]] = []
        self._previous: Optional[Hand] = None
        self._lock = threading.RLock()
        self._active = False
        self._thread: Optional[threading.Thread] = None
        self._frames = 0
        self._gestures = 0

    def start(self) -> None:
        with self._lock:
            if self._active:
                return
            self._active = True
            if self._backend is None:
                self._backend = self._make_backend()
            self._backend.start()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._active = False
        if self._backend is not None:
            try:
                self._backend.stop()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def recent_gestures(self, limit: int = 64) -> list[GestureEvent]:
        with self._lock:
            return list(self._history)[-limit:]

    def status(self) -> dict:
        with self._lock:
            return {
                "active": self._active,
                "backend": type(self._backend).__name__ if self._backend else "none",
                "frames": self._frames,
                "gestures": self._gestures,
                "history": len(self._history),
                "last_gesture": self._history[-1].gesture if self._history else None,
            }

    def observe(self, handler: Callable[[GestureEvent], None]) -> None:
        with self._lock:
            self._observers.append(handler)

    def _make_backend(self) -> HandBackend:
        backend = (self._config.backend or "synthetic").lower()
        if backend in ("mediapipe", "mp", "hands"):
            try:
                from hand_tracking import MediaPipeHandBackend
                return MediaPipeHandBackend()
            except Exception as exc:
                logger.warning("MediaPipe backend unavailable: %s", exc)
        return SyntheticHandBackend()

    def _run(self) -> None:
        cooldown = self._config.gesture_cooldown_seconds
        last_gesture_time = 0.0
        last_gesture_name = ""
        while True:
            with self._lock:
                if not self._active:
                    break
            frame = self._backend.read_frame()
            if frame is None:
                time.sleep(0.05)
                continue
            hands = frame.get("hands") or []
            best_hand = None
            for hand in hands:
                if hand.confidence >= self._config.min_confidence and (best_hand is None or hand.confidence > best_hand.confidence):
                    best_hand = hand
            if best_hand is None:
                self._previous = None
                continue
            event = self._recognizer.recognize(best_hand, self._previous)
            now = time.monotonic()
            if event.gesture != "NONE" and (event.gesture != last_gesture_name or now - last_gesture_time > cooldown):
                with self._lock:
                    self._history.append(event)
                    self._frames += 1
                    self._gestures += 1
                    last_gesture_time = now
                    last_gesture_name = event.gesture
                    for handler in list(self._observers):
                        try:
                            handler(event)
                        except Exception as exc:
                            logger.debug("Observer failed: %s", exc)
                if self._event_bus is not None:
                    try:
                        from event_bus import GestureEventBus
                        bus = GestureEventBus(self._event_bus)
                        bus.emit(event.gesture, event.hand, event.confidence, event.meta)
                    except Exception:
                        pass
            self._previous = best_hand
            time.sleep(0.01)
