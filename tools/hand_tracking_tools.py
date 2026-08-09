"""tools/hand_tracking_tools.py -- Hand tracking and gesture tools for VYREN."""

from __future__ import annotations

import logging
from typing import Any

from tools import ToolDef, ToolRegistry

logger = logging.getLogger("vyren.tools.hand_tracking")


def register(registry: ToolRegistry):
    try:
        from hand_tracking import HandTrackingEngine, HandTrackingConfig
    except ImportError as exc:
        logger.warning("Hand tracking tools not loaded: %s", exc)
        return

    engine = HandTrackingEngine()

    def hand_tracking_start() -> str:
        """Start hand tracking."""
        try:
            engine.start()
            return "Hand tracking started."
        except Exception as e:
            return f"Hand tracking start failed: {type(e).__name__} -- {e}"

    def hand_tracking_stop() -> str:
        """Stop hand tracking."""
        try:
            engine.stop()
            return "Hand tracking stopped."
        except Exception as e:
            return f"Hand tracking stop failed: {type(e).__name__} -- {e}"

    def hand_tracking_status() -> str:
        """Return hand tracking state."""
        try:
            return str(engine.status())
        except Exception as e:
            return f"Hand tracking status failed: {type(e).__name__} -- {e}"

    def hand_tracking_recent(limit: int = 20) -> str:
        """Return recent gesture events."""
        try:
            events = engine.recent_gestures(limit=max(1, min(limit, 200)))
            if not events:
                return "No gestures detected yet."
            return "\n".join(
                f"{e.gesture}: confidence={e.confidence:.2f}" for e in events
            )
        except Exception as e:
            return f"Hand tracking recent failed: {type(e).__name__} -- {e}"

    registry.register(
        ToolDef(
            name="hand_tracking_start",
            description="Start hand tracking and gesture recognition.",
            parameters={"type": "object", "properties": {}},
            handler=hand_tracking_start,
            safety_level="safe",
        )
    )
    registry.register(
        ToolDef(
            name="hand_tracking_stop",
            description="Stop hand tracking and gesture recognition.",
            parameters={"type": "object", "properties": {}},
            handler=hand_tracking_stop,
            safety_level="safe",
        )
    )
    registry.register(
        ToolDef(
            name="hand_tracking_status",
            description="Return hand tracking state and recent metrics.",
            parameters={"type": "object", "properties": {}},
            handler=hand_tracking_status,
            safety_level="safe",
        )
    )
    registry.register(
        ToolDef(
            name="hand_tracking_recent",
            description="Return recent gesture events from hand tracking.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max events to return"}
                },
            },
            handler=hand_tracking_recent,
            safety_level="safe",
        )
    )
