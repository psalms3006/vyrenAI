"""
vision/ocr.py -- OCR backends for VYREN.

Backends:
- DummyOcrBackend: always available, returns synthetic OCR results.
- TesseractBackend: requires `pytesseract` + `PIL` + tesseract binary.
- EasyOcrBackend: requires `easyocr`.
- PaddleOcrBackend: requires `paddleocr`.

Auto-selection:
- `resolve_backend()` picks the first available optional backend,
  falling back to DummyOcrBackend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable


@dataclass(frozen=True)
class OcrWord:
    text: str
    confidence: float = 0.0
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass
class OcrResult:
    text: str = ""
    words: list[OcrWord] = field(default_factory=list)
    confidence: float = 0.0
    backend: str = ""
    source: str = ""
    error: str = ""

    @property
    def average_confidence(self) -> float:
        if not self.words:
            return 0.0
        return sum(word.confidence for word in self.words) / len(self.words)


@runtime_checkable
class OcrBackend(Protocol):
    def detect_text(self, source: str | Path) -> OcrResult:
        ...


class DummyOcrBackend:
    name = "dummy"

    def load(self) -> None:
        return None

    def detect_text(self, source: str | Path) -> OcrResult:
        text = "SAMPLE_TERMINAL_OUTPUT\nStatus: active\nLine: 2"
        words = [
            OcrWord(text="SAMPLE_TERMINAL_OUTPUT", confidence=0.98, bbox=(10, 10, 300, 30)),
            OcrWord(text="Status:", confidence=0.97, bbox=(10, 40, 100, 60)),
            OcrWord(text="active", confidence=0.95, bbox=(110, 40, 180, 60)),
            OcrWord(text="Line:", confidence=0.99, bbox=(10, 70, 70, 90)),
            OcrWord(text="2", confidence=0.99, bbox=(80, 70, 100, 90)),
        ]
        return OcrResult(text=text, words=words, confidence=0.97, backend=self.name, source=str(source))


class TesseractBackend:
    name = "tesseract"

    def __init__(self) -> None:
        self._pytesseract = None
        self._Image = None
        self._load_ok = False
        self._error = ""

    def load(self) -> None:
        if self._load_ok:
            return
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore

            self._pytesseract = pytesseract
            self._Image = Image
            self._load_ok = True
        except Exception as exc:
            self._error = f"Tesseract backend unavailable: {type(exc).__name__}: {exc}"
            raise RuntimeError(self._error) from exc

    def detect_text(self, source: str | Path) -> OcrResult:
        if not self._load_ok:
            try:
                self.load()
            except RuntimeError:
                return OcrResult(text="", words=[], confidence=0.0, backend=self.name, source=str(source), error=self._error)
        if not self._load_ok:
            return OcrResult(text="", words=[], confidence=0.0, backend=self.name, source=str(source), error=self._error)
        try:
            image = self._Image.open(str(source))
            data = self._pytesseract.image_to_data(image, output_type=self._pytesseract.Output.DICT)
            words: list[OcrWord] = []
            text_items = data.get("text", [])
            conf_items = data.get("conf", [])
            left_items = data.get("left", [])
            top_items = data.get("top", [])
            width_items = data.get("width", [])
            height_items = data.get("height", [])
            for idx in range(len(text_items)):
                raw_text = text_items[idx]
                if not raw_text or not raw_text.strip():
                    continue
                conf = float(conf_items[idx]) / 100.0
                words.append(
                    OcrWord(
                        text=raw_text,
                        confidence=max(0.0, min(1.0, conf if conf >= 0 else 0.0)),
                        bbox=(
                            int(left_items[idx]),
                            int(top_items[idx]),
                            int(left_items[idx]) + int(width_items[idx]),
                            int(top_items[idx]) + int(height_items[idx]),
                        ),
                    )
                )
            text = " ".join(word.text for word in words)
            confidence = sum(word.confidence for word in words) / len(words) if words else 0.0
            return OcrResult(text=text, words=words, confidence=confidence, backend=self.name, source=str(source))
        except Exception as exc:
            return OcrResult(text="", words=[], confidence=0.0, backend=self.name, source=str(source), error=str(exc))


class EasyOcrBackend:
    name = "easyocr"

    def __init__(self) -> None:
        self._reader = None
        self._load_ok = False
        self._error = ""

    def load(self) -> None:
        if self._load_ok:
            return
        try:
            import easyocr  # type: ignore

            self._reader = easyocr.Reader(["en"], gpu=False)
            self._load_ok = True
        except Exception as exc:
            self._error = f"EasyOCR backend unavailable: {type(exc).__name__}: {exc}"
            raise RuntimeError(self._error) from exc

    def detect_text(self, source: str | Path) -> OcrResult:
        if not self._load_ok:
            try:
                self.load()
            except RuntimeError:
                return OcrResult(text="", words=[], confidence=0.0, backend=self.name, source=str(source), error=self._error)
        if not self._load_ok:
            return OcrResult(text="", words=[], confidence=0.0, backend=self.name, source=str(source), error=self._error)
        try:
            result = self._reader.readtext(str(source), detail=1, paragraph=False)
            words = [
                OcrWord(
                    text=text,
                    confidence=max(0.0, min(1.0, float(confidence))),
                    bbox=(int(points[0][0]), int(points[0][1]), int(points[2][0]), int(points[2][1])),
                )
                for points, text, confidence in result
            ]
            text = " ".join(word.text for word in words)
            confidence = sum(word.confidence for word in words) / len(words) if words else 0.0
            return OcrResult(text=text, words=words, confidence=confidence, backend=self.name, source=str(source))
        except Exception as exc:
            return OcrResult(text="", words=[], confidence=0.0, backend=self.name, source=str(source), error=str(exc))


class PaddleOcrBackend:
    name = "paddle"

    def __init__(self) -> None:
        self._ocr = None
        self._load_ok = False
        self._error = ""

    def load(self) -> None:
        if self._load_ok:
            return
        try:
            from paddleocr import PaddleOCR  # type: ignore

            self._ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
            self._load_ok = True
        except Exception as exc:
            self._error = f"PaddleOCR backend unavailable: {type(exc).__name__}: {exc}"
            raise RuntimeError(self._error) from exc

    def detect_text(self, source: str | Path) -> OcrResult:
        if not self._load_ok:
            try:
                self.load()
            except RuntimeError:
                return OcrResult(text="", words=[], confidence=0.0, backend=self.name, source=str(source), error=self._error)
        if not self._load_ok:
            return OcrResult(text="", words=[], confidence=0.0, backend=self.name, source=str(source), error=self._error)
        try:
            result = self._ocr.ocr(str(source), cls=True)
            words: list[OcrWord] = []
            for line in result or []:
                if not line:
                    continue
                for entry in line:
                    text = entry.get("rec_text", "")
                    confidence = entry.get("rec_score", 0.0)
                    points = entry.get("dt_polys", entry.get("points", []))
                    if hasattr(points, "tolist"):
                        points = points.tolist()
                    bbox = (0, 0, 0, 0)
                    if points and len(points) >= 4:
                        xs = [int(coord[0]) for coord in points]
                        ys = [int(coord[1]) for coord in points]
                        bbox = (min(xs), min(ys), max(xs), max(ys))
                    words.append(OcrWord(text=text, confidence=max(0.0, min(1.0, float(confidence))), bbox=bbox))
            text = " ".join(word.text for word in words)
            confidence = sum(word.confidence for word in words) / len(words) if words else 0.0
            return OcrResult(text=text, words=words, confidence=confidence, backend=self.name, source=str(source))
        except Exception as exc:
            return OcrResult(text="", words=[], confidence=0.0, backend=self.name, source=str(source), error=str(exc))


def resolve_backend(name: str | None = None) -> OcrBackend:
    if not name or name == "auto":
        for candidate in (TesseractBackend, EasyOcrBackend, PaddleOcrBackend):
            backend = candidate()
            try:
                backend.load()
                return backend
            except RuntimeError:
                continue
        return DummyOcrBackend()
    name = name.lower()
    mapping = {
        "dummy": DummyOcrBackend,
        "tesseract": TesseractBackend,
        "easyocr": EasyOcrBackend,
        "paddle": PaddleOcrBackend,
    }
    candidate = mapping.get(name)
    if candidate is None:
        raise ValueError(f"Unsupported OCR backend: {name}")
    backend = candidate()
    if name == "dummy":
        return backend
    backend.load()
    return backend


def backend_choices() -> dict[str, str]:
    return {
        "auto": "Auto-select first available backend",
        "dummy": "Synthetic OCR fallback",
        "tesseract": "pytesseract + PIL + tesseract binary",
        "easyocr": "EasyOCR",
        "paddle": "PaddleOCR",
    }
