"""tools/screen_tools.py -- Screen capture and analysis tools.

Captures screenshots and uses Gemini vision to understand what's
on the user's screen. This is how VYREN can 'see' your screen.
"""

from __future__ import annotations

import base64
import io
import os
from datetime import datetime

from platform_paths import get_screenshot_dir

from tools import ToolDef, ToolRegistry


def _to_jpeg(img_bytes: bytes, max_w: int = 1280, max_h: int = 720, quality: int = 75) -> bytes:
    try:
        from PIL import Image
    except ImportError:
        return img_bytes
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img.thumbnail([max_w, max_h], Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=False)
        return buf.getvalue()
    except Exception:
        return img_bytes


def _capture_screen(
    save_path: str,
    monitor_index: int | None = None,
    region: tuple[int, int, int, int] | None = None,
) -> str:
    """Capture a screenshot and save to path.

    Prefers MSS monitor-aware capture, falls back to Pillow ImageGrab.
    Returns the path, or an error string prefixed with 'ERROR:'.
    """
    try:
        import mss
        import mss.tools
    except ImportError:
        mss = None  # type: ignore

    try:
        if monitor_index is not None and mss is not None:
            with mss.mss() as sct:
                monitors = sct.monitors
                idx = monitor_index + 1 if 0 <= monitor_index < len(monitors) - 1 else 1
                shot = sct.grab(monitors[idx])
                png_bytes = mss.tools.to_png(shot.rgb, shot.size)
            jpeg = _to_jpeg(png_bytes)
            os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(jpeg)
            return save_path
        if region is not None and mss is not None:
            left, top, width, height = region
            with mss.mss() as sct:
                shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
                png_bytes = mss.tools.to_png(shot.rgb, shot.size)
            jpeg = _to_jpeg(png_bytes)
            os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(jpeg)
            return save_path
    except Exception as e:
        return f"ERROR:{type(e).__name__}: {e}"

    try:
        from PIL import ImageGrab
        screenshot = ImageGrab.grab()
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        screenshot.save(save_path)
        return save_path
    except ImportError:
        if mss is not None:
            try:
                with mss.mss() as sct:
                    sct.shot(output=save_path)
                return save_path
            except Exception as e:
                return f"ERROR:{type(e).__name__}: {e}"
        return "ERROR:no_capture_library"
    except Exception as e:
        return f"ERROR:{type(e).__name__}: {e}"


def _analyze_image(save_path: str, question: str) -> str:
    try:
        from dotenv import load_dotenv
        from google import genai
        from google.genai import types

        load_dotenv()
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return f"Screenshot saved to {save_path} but GEMINI_API_KEY not set for analysis."

        client = genai.Client(api_key=api_key)
        with open(save_path, "rb") as f:
            img_data = f.read()
        mime = "image/png"
        if save_path.lower().endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        elif save_path.lower().endswith(".webp"):
            mime = "image/webp"
        elif save_path.lower().endswith(".gif"):
            mime = "image/gif"

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=question),
                        types.Part.from_bytes(data=img_data, mime_type=mime),
                    ],
                )
            ],
        )
        return response.text
    except Exception as e:
        return f"Screenshot saved to {save_path} but analysis failed: {type(e).__name__} -- {e}"


def register(registry: ToolRegistry):
    """Register screen tools."""

    def capture_screen(monitor_index: int | None = None, region: tuple[int, int, int, int] | None = None) -> str:
        """Take a screenshot and save it to a file.

        Returns the file path so you can then use analyze_image to look at it.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = str(get_screenshot_dir() / f"screen_{timestamp}.png")

        result = _capture_screen(save_path, monitor_index=monitor_index, region=region)
        if not result or result.startswith("ERROR:"):
            if result == "ERROR:no_capture_library":
                return (
                    "Screen capture failed. You need Pillow installed: pip install Pillow\\n"
                    "Or mss as an alternative: pip install mss"
                )
            return f"Screen capture failed: {result[len('ERROR:'):] if result.startswith('ERROR:') else 'unknown error'}"

        return f"Screenshot saved to: {save_path}\\nYou can now use analyze_image to look at it."

    def capture_and_analyze(
        question: str = "Describe what is on this screen in detail.",
        monitor_index: int | None = None,
        region: tuple[int, int, int, int] | None = None,
    ) -> str:
        """Take a screenshot and immediately analyze it using Gemini vision."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = str(get_screenshot_dir() / f"screen_{timestamp}.png")

        result = _capture_screen(save_path, monitor_index=monitor_index, region=region)
        if not result or result.startswith("ERROR:"):
            if result == "ERROR:no_capture_library":
                return (
                    "Screen capture failed. You need Pillow installed: pip install Pillow\\n"
                    "Or mss as an alternative: pip install mss"
                )
            return f"Screen capture failed: {result[len('ERROR:'):] if result.startswith('ERROR:') else 'unknown error'}"

        return _analyze_image(save_path, question)

    registry.register(
        ToolDef(
            name="capture_screen",
            description="Take a screenshot of the entire screen and save it as a PNG file. The file path is returned so you can then use analyze_image to examine it.",
            parameters={
                "type": "object",
                "properties": {
                    "monitor_index": {"type": "integer", "description": "Optional monitor index for multi-monitor capture."},
                    "region": {"type": "array", "items": {"type": "integer"}, "description": "Optional [left, top, width, height] region capture."},
                },
            },
            handler=capture_screen,
            safety_level="safe",
        )
    )

    registry.register(
        ToolDef(
            name="capture_and_analyze",
            description="Take a screenshot AND analyze it in one step. Returns a detailed description of what's on screen.",
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "What to ask about the screen (default: describe in detail)"},
                    "monitor_index": {"type": "integer", "description": "Optional monitor index for multi-monitor capture."},
                    "region": {"type": "array", "items": {"type": "integer"}, "description": "Optional [left, top, width, height] region capture."},
                },
                "required": ["question"],
            },
            handler=capture_and_analyze,
            safety_level="safe",
        )
    )
