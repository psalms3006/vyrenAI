"""generation/eventing.py -- Event emission helpers for the generation layer."""
from __future__ import annotations

import logging
from typing import Any

from event_bus import Event

logger = logging.getLogger("vyren.generation")

GENERATION_STARTED = "generation.started"
GENERATION_PROGRESS = "generation.progress"
GENERATION_COMPLETED = "generation.completed"
GENERATION_FAILED = "generation.failed"
GENERATION_CANCELLED = "generation.cancelled"
ARTIFACT_CREATED = "artifact.created"


def publish(event_bus, event_type: str, data: dict[str, Any]) -> None:
    if event_bus is None:
        return
    try:
        event_bus.publish_sync(Event(type=event_type, source="generation", data=data))
    except Exception as exc:
        logger.debug("Event publish skipped: %s", exc)
