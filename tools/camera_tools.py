"""tools/camera_tools.py -- Camera capture tools for VYREN."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tools import ToolDef, ToolRegistry

logger = logging.getLogger("vyren.tools.camera")


def register(registry: ToolRegistry):
    try:
        from camera import CameraManager
    except ImportError as exc:
        logger.warning("Camera tools not loaded: %s", exc)
        return

    manager = CameraManager()

    def camera_capture_photo(path: str = "") -> str:
        """Capture a single photo from the default camera and save it."""
        try:
            manager.start()
            target = Path(path) if path else Path("camera_photo.png")
            target.parent.mkdir(parents=True, exist_ok=True)
            out = manager.take_photo(target)
            return f"Photo saved: {out}"
        except Exception as e:
            return f"Camera capture failed: {type(e).__name__} -- {e}"
        finally:
            try:
                manager.stop()
            except Exception:
                pass

    def camera_status() -> str:
        """Return camera availability and current state."""
        try:
            status = manager.status()
            return str(status)
        except Exception as e:
            return f"Camera status failed: {type(e).__name__} -- {e}"

    def camera_list() -> str:
        """List available cameras."""
        try:
            cameras = manager.enumerate_cameras()
            if not cameras:
                return "No cameras detected."
            return "\n".join(f"{c.index}: {c.name or 'Camera'} ({c.backend})" for c in cameras)
        except Exception as e:
            return f"Camera enumeration failed: {type(e).__name__} -- {e}"

    registry.register(
        ToolDef(
            name="camera_capture_photo",
            description="Capture a single photo from the default camera and save it.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional save path"}
                },
            },
            handler=camera_capture_photo,
            safety_level="safe",
        )
    )
    registry.register(
        ToolDef(
            name="camera_status",
            description="Return camera availability and current state.",
            parameters={"type": "object", "properties": {}},
            handler=camera_status,
            safety_level="safe",
        )
    )
    registry.register(
        ToolDef(
            name="camera_list",
            description="List available cameras.",
            parameters={"type": "object", "properties": {}},
            handler=camera_list,
            safety_level="safe",
        )
    )
