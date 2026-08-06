"""
event_bus.py -- typed event bus for VYREN.

Event types used by hand tracking:
    GestureDetected(gesture, hand, confidence, meta)

All handlers receive the event dataclass instance. Handlers may raise;
the bus isolates failures so one misbehaving subscriber does not break
the others.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("vyren.event_bus")

VYREN_STARTED = "vyren.started"


@dataclass
class Event:
    type: str
    source: str = "unknown"
    data: dict = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], None]]] = {}
        self._lock = threading.RLock()

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event: Event) -> None:
        handlers: list[Callable[[Event], None]] = []
        with self._lock:
            handlers = list(self._subscribers.get(event.type, []))
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                logger.debug("Event handler failed for %s: %s", event.type, exc)

    def publish_sync(self, event: Event) -> None:
        self.publish(event)


_GESTURE_TYPE_ALIASES = {
    "GestureDetected": "GestureDetected",
}


def _normalize_gesture_event(event: Event) -> Event:
    etype = event.type
    if etype in _GESTURE_TYPE_ALIASES:
        etype = _GESTURE_TYPE_ALIASES[etype]
    data = dict(event.data or {})
    gesture = str(data.get("gesture", data.get("name", "")))
    hand = str(data.get("hand", data.get("handedness", "")))
    confidence = float(data.get("confidence", 0.0))
    meta = dict(data.get("meta", {}))
    return Event(type="GestureDetected", source=event.source or "hand_tracking", data={"gesture": gesture, "hand": hand, "confidence": confidence, "meta": meta})


class GestureEventBus:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def emit(self, gesture: str, hand: str, confidence: float, meta: dict | None = None) -> None:
        event = Event(type="GestureDetected", source="hand_tracking", data={"gesture": gesture, "hand": hand, "confidence": confidence, "meta": meta or {}})
        self._bus.publish(event)
