"""tools/screen_tools.py -- Screen capture and analysis tools.

Captures screenshots and uses Gemini vision to understand what's
on the user's screen. This is how VYREN can 'see' your screen.
"""

import os
import tempfile
from datetime import datetime

from tools import ToolDef, ToolRegistry


def _capture_screen(save_path: str) -> str:
    """Capture a screenshot and save to path. Returns the path or error."""
    try:
        from PIL import ImageGrab
        screenshot = ImageGrab.grab()
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        screenshot.save(save_path)
        return save_path
    except ImportError:
        # Fallback: try mss
        try:
            import mss
            with mss.mss() as sct:
                sct.shot(output=save_path)
            return save_path
        except ImportError:
            return ""
    except Exception as e:
        return ""


def register(registry: ToolRegistry):
    """Register screen tools."""

    def capture_screen() -> str:
        """Take a screenshot of the entire screen and save it to a file.

        Returns the file path so you can then use analyze_image to look at it.
        Requires Pillow (pip install Pillow) or mss (pip install mss).
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.expanduser(f"~/.vyren/screenshots/screen_{timestamp}.png")

        result = _capture_screen(save_path)
        if not result:
            return (
                "Screen capture failed. You need Pillow installed:\n"
                "  pip install Pillow\n"
                "Or mss as an alternative:\n"
                "  pip install mss"
            )

        return f"Screenshot saved to: {save_path}\nYou can now use analyze_image to look at it."

    def capture_and_analyze(question: str = "Describe what is on this screen in detail.") -> str:
        """Take a screenshot and immediately analyze it using Gemini vision.

        This combines capture_screen + analyze_image in one step. Returns
        a detailed description of what's on screen.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.expanduser(f"~/.vyren/screenshots/screen_{timestamp}.png")

        result = _capture_screen(save_path)
        if not result:
            return (
                "Screen capture failed. You need Pillow installed:\n"
                "  pip install Pillow\n"
                "Or mss as an alternative:\n"
                "  pip install mss"
            )

        # Now analyze with Gemini
        try:
            import base64
            from dotenv import load_dotenv
            from google import genai
            from google.genai import types

            load_dotenv()
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                return f"Screenshot saved to {save_path} but GEMINI_API_KEY not set for analysis."

            client = genai.Client(api_key=api_key)
            with open(save_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(question),
                            types.Part.from_bytes(
                                data=base64.b64decode(img_data),
                                mime_type="image/png",
                            ),
                        ],
                    )
                ],
            )

            return f"[Screenshot: {save_path}]\n\n{response.text}"

        except Exception as e:
            return f"Screenshot saved to {save_path} but analysis failed: {type(e).__name__} -- {e}"

    registry.register(ToolDef(
        name="capture_screen",
        description=(
            "Take a screenshot of the entire screen and save it as a PNG file. "
            "The file path is returned so you can then use analyze_image to examine it. "
            "Requires Pillow or mss to be installed."
        ),
        parameters={"type": "object", "properties": {}},
        handler=capture_screen,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="capture_and_analyze",
        description=(
            "Take a screenshot AND analyze it in one step. Returns a detailed description "
            "of what's on screen. This is how VYREN can 'see' your screen. "
            "You can ask specific questions about what's on screen."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "What to ask about the screen (default: describe in detail)",
                },
            },
        },
        handler=capture_and_analyze,
        safety_level="safe",
    ))
