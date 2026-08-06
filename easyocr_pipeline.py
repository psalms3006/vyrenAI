"""
easyocr_pipeline.py -- EasyOCR wrapper for VYREN.

Supports:
- image files
- terminal/browser screenshots
- PDF/book rendered pages
- form fields / handwritten text (best-effort)

Falls back gracefully if easyocr is unavailable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Mapping, Any


class EasyOcrPipelineError(Exception):
    pass


def is_available() -> bool:
    try:
        __import__("easyocr")
        return True
    except Exception:
        return False


def extract_text(
    source: str | Path,
    *,
    languages: Sequence[str] | None = None,
    gpu: bool = False,
    min_confidence: float = 0.25,
) -> Mapping[str, Any]:
    """Run EasyOCR on a source path and return normalized OCR output."""
    path = str(source)
    if not path or not Path(path).exists():
        raise EasyOcrPipelineError(f"source not found: {path!r}")

    try:
        import easyocr  # type: ignore
    except Exception as exc:  # pragma: no cover - optional backend
        raise EasyOcrPipelineError(f"easyocr unavailable: {type(exc).__name__}: {exc}") from exc

    langs = list(languages or ["en"])
    try:
        reader = easyocr.Reader(langs, gpu=gpu)
        result = reader.readtext(path, detail=1, paragraph=False)
    except Exception as exc:
        raise EasyOcrPipelineError(f"easyocr inference failed: {type(exc).__name__}: {exc}") from exc

    words = []
    text_parts = []
    confidences = []
    for bbox, text, confidence in result or []:
        if not text or not text.strip():
            continue
        conf = max(0.0, min(1.0, float(confidence)))
        if conf < min_confidence:
            continue
        words.append(
            {
                "text": text.strip(),
                "confidence": conf,
                "bbox": [
                    [int(coord[0]), int(coord[1])] for coord in bbox
                ],
            }
        )
        text_parts.append(text.strip())
        confidences.append(conf)

    text = "\n".join(part for part in text_parts if part) or ""
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return {
        "backend": "easyocr",
        "text": text,
        "confidence": confidence,
        "words": words,
        "source": path,
    }
