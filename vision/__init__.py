"""
vision/__init__.py -- Vision Engine package.

Public surface:
    VisionEngine
    VisionConfig
    VisionObservation
    VisionError
    FrameSourceManager
    MonitorInfo
    ObjectDetectorWorker
    DetectorBackend
    DummyDetectorBackend
    ObjectTracker
    DetectedObject
    OcrBackend
    DummyOcrBackend
    TesseractBackend
    EasyOcrBackend
    PaddleOcrBackend
    resolve_backend
    OcrResult
    OcrWord
"""

from vision.engine import (
    VisionEngine,
    VisionConfig,
    VisionObservation,
    VisionError,
)
from vision.sources import (
    FrameSourceManager,
    MonitorInfo,
)
from vision.detection import (
    ObjectDetectorWorker,
    DetectorBackend,
    DummyDetectorBackend,
    ObjectTracker,
    DetectedObject,
)
from vision.ocr import (
    OcrBackend,
    DummyOcrBackend,
    TesseractBackend,
    EasyOcrBackend,
    PaddleOcrBackend,
    resolve_backend,
    OcrResult,
    OcrWord,
)

__all__ = [
    "VisionEngine",
    "VisionConfig",
    "VisionObservation",
    "VisionError",
    "FrameSourceManager",
    "MonitorInfo",
    "ObjectDetectorWorker",
    "DetectorBackend",
    "DummyDetectorBackend",
    "ObjectTracker",
    "DetectedObject",
    "OcrBackend",
    "DummyOcrBackend",
    "TesseractBackend",
    "EasyOcrBackend",
    "PaddleOcrBackend",
    "resolve_backend",
    "OcrResult",
    "OcrWord",
]
