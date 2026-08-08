"""
tools/vision_tools.py -- Image and video generation tools.

Uses Gemini's multimodal capabilities to generate images and analyze
visual content. Image generation requires a model that supports it.
Falls back gracefully if the model doesn't support generation.
"""

import os
import base64
import tempfile
from datetime import datetime

from tools import ToolDef, ToolRegistry


def _get_generated_dir() -> str:
    from platform_paths import get_generated_dir
    return str(get_generated_dir())


def register(registry: ToolRegistry):

    def generate_image(prompt: str, save_path: str = "") -> str:
        """Generate an image from a text description using Gemini."""
        try:
            from dotenv import load_dotenv
            from google import genai
            from google.genai import types

            load_dotenv()
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                return "Error: GEMINI_API_KEY not set."

            client = genai.Client(api_key=api_key)

            # Try using Gemini's native image generation
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )

            # Check for image in response
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    img_data = part.inline_data.data
                    mime = part.inline_data.mime_type or "image/png"

                    # Determine save path
                    if not save_path:
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        save_path = str(get_generated_dir() / f"generated_{timestamp}.png")

                    save_path = str(get_generated_dir() / save_path)
                    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

                    ext = ".png" if "png" in mime else ".jpg"
                    if not save_path.endswith(ext):
                        save_path += ext

                    with open(save_path, "wb") as f:
                        f.write(img_data)

                    return f"Image generated and saved to: {save_path}"

            # No image in response — return the text
            text = "".join(
                p.text for p in response.candidates[0].content.parts
                if hasattr(p, "text") and p.text
            )
            if text:
                return f"Model responded with text instead of an image: {text}"
            return "Image generation returned no content. The model may not support image generation."
        except Exception as e:
            return (
                f"Image generation failed: {type(e).__name__} — {e}\n"
                "This may require a model that supports image generation."
            )

    def analyze_image(file_path: str, question: str = "Describe this image in detail.") -> str:
        """Analyze an image file using Gemini's vision capabilities."""
        try:
            from dotenv import load_dotenv
            from google import genai
            from google.genai import types

            load_dotenv()
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                return "Error: GEMINI_API_KEY not set."

            client = genai.Client(api_key=api_key)

            resolved = os.path.realpath(file_path)
            if not os.path.isfile(resolved):
                return f"File not found: {file_path}"

            # Read and encode image
            with open(resolved, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")

            mime = "image/png"
            if resolved.endswith((".jpg", ".jpeg")):
                mime = "image/jpeg"
            elif resolved.endswith(".webp"):
                mime = "image/webp"
            elif resolved.endswith(".gif"):
                mime = "image/gif"

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(text=question),
                            types.Part.from_bytes(
                                data=base64.b64decode(img_data),
                                mime_type=mime,
                            ),
                        ],
                    )
                ],
            )

            return response.text
        except Exception as e:
            return f"Image analysis failed: {type(e).__name__} — {e}"

    def ocr_image(file_path: str, backend: str = "auto") -> str:
        """Run OCR on an image, PDF page, screenshot, or camera frame path."""
        import json
        from pathlib import Path
        try:
            from vision.ocr import resolve_backend
            source = file_path
            ocr_backend = resolve_backend(backend)
            result = ocr_backend.detect_text(source)
            
            result_data = {
                "status": "success",
                "text": result.text or "",
                "backend": result.backend,
                "confidence": result.confidence,
                "word_count": len(result.words)
            }
            
            if result.error:
                result_data["status"] = "error"
                result_data["error"] = result.error
                
            return json.dumps(result_data)
        except Exception as e:
            return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"})

    registry.register(ToolDef(
        name="generate_image",
        description=(
            "Generate an image from a text description. "
            "The image is saved to a file. Specify a save_path or it "
            "auto-saves to the platform cache dir with a timestamp."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the image to generate",
                },
                "save_path": {
                    "type": "string",
                    "description": "Where to save the image (optional, auto-generates if omitted)",
                },
            },
            "required": ["prompt"],
        },
        handler=generate_image,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="analyze_image",
        description=(
            "Analyze an image file — describe what's in it, answer questions "
            "about it, extract text (OCR), or identify objects. "
            "Supports PNG, JPG, WebP, GIF."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the image file to analyze",
                },
                "question": {
                    "type": "string",
                    "description": "What to ask about the image (default: describe in detail)",
                },
            },
            "required": ["file_path"],
        },
        handler=analyze_image,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="ocr_image",
        description=(
            "Extract text from an image, terminal screenshot, browser screenshot, "
            "PDF page, book page, form, or handwritten note path. "
            "Choose an OCR backend or use auto."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path or source path for image/pdf/screenshot",
                },
                "backend": {
                    "type": "string",
                    "description": "OCR backend: auto, tesseract, easyocr, paddle",
                },
            },
            "required": ["file_path"],
        },
        handler=ocr_image,
        safety_level="safe",
    ))
