"""
vision/detection.py -- Object detection integration for VYREN.

Provides:
- DetectorBackend interface
- DummyDetectorBackend for fallback/testing
- ObjectDetectorWorker for integration with VisionEngine
- ObjectTracker for persistent IDs across frames
- DetectedObject dataclass for structured output
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from vision.engine import VisionObservation

logger = logging.getLogger("vyren.vision.detection")


class DetectionBackendError(Exception):
    pass


@dataclass
class DetectedObject:
    object_id: str = ""
    label: str = ""
    confidence: float = 0.0
    box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    center: tuple[float, float] = (0.0, 0.0)
    frame_ts: float = 0.0
    history: list[dict] = field(default_factory=list)

    def update(self, box: tuple[float, float, float, float], confidence: float, frame_ts: float) -> None:
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
        prev = self.center
        dx = cx - prev[0]
        dy = cy - prev[1]
        self.history.append(
            {
                "box": box,
                "confidence": confidence,
                "center": (cx, cy),
                "frame_ts": frame_ts,
                "movement": math.hypot(dx, dy),
            }
        )
        self.box = box
        self.confidence = confidence
        self.center = (cx, cy)
        self.frame_ts = frame_ts
        if len(self.history) > 64:
            self.history = self.history[-64:]


class DetectionResult:
    def __init__(self, frame_ts: float, detections: list[DetectedObject] | None = None) -> None:
        self.frame_ts = frame_ts
        self.detections = detections or []

    def to_observation(self) -> VisionObservation:
        labels = [d.label for d in self.detections if d.label]
        summary = ", ".join(labels) if labels else "objects"
        return VisionObservation(
            source="vision.object_detector",
            frame_ts=self.frame_ts,
            model="detector",
            summary=summary,
            objects=[
                {
                    "id": d.object_id,
                    "label": d.label,
                    "confidence": d.confidence,
                    "box": list(d.box),
                    "center": list(d.center),
                    "history_count": len(d.history),
                    "movement": d.history[-1]["movement"] if d.history else 0.0,
                }
                for d in self.detections
            ],
            confidence=max((d.confidence for d in self.detections), default=0.0),
        )


class DetectorBackend:
    name: str = "backend"

    def load(self) -> None:
        raise NotImplementedError

    def detect(self, frame: Any, threshold: float = 0.3) -> DetectionResult:
        raise NotImplementedError


class DummyDetectorBackend(DetectorBackend):
    name = "dummy"

    def load(self) -> None:
        logger.info("Loaded dummy detector backend")

    def detect(self, frame: Any, threshold: float = 0.3) -> DetectionResult:
        _ = frame, threshold
        return DetectionResult(frame_ts=time.monotonic(), detections=[])


class ObjectTracker:
    def __init__(
        self,
        iou_threshold: float = 0.3,
        center_threshold: float = 0.25,
        max_lost_frames: int = 20,
        track_history: int = 64,
    ) -> None:
        self._objects: dict[str, DetectedObject] = {}
        self._next_id = 1
        self._iou_threshold = iou_threshold
        self._center_threshold = center_threshold
        self._max_lost_frames = max_lost_frames
        self._track_history = track_history
        self._lock = threading.Lock()

    def _trim(self, obj: DetectedObject) -> None:
        if len(obj.history) > self._track_history:
            obj.history = obj.history[-self._track_history:]

    def _iou(self, a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        if inter <= 0.0:
            return 0.0
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        union = area_a + area_b - inter
        if union <= 0.0:
            return 0.0
        return inter / union

    def _distance(self, a: tuple[float, float], b: tuple[float, float], scale: float) -> float:
        if scale <= 0.0:
            return math.hypot(a[0] - b[0], a[1] - b[1])
        return math.hypot((a[0] - b[0]) / scale, (a[1] - b[1]) / scale)

    def _scale(self, box: tuple[float, float, float, float]) -> float:
        w = box[2] - box[0]
        h = box[3] - box[1]
        return max(w, h, 1.0)

    def _assign(self, detections: Sequence[DetectedObject], frame_ts: float) -> list[DetectedObject]:
        if not detections:
            return []
        used_ids: set[str] = set()
        unmatched = list(detections)
        assigned: list[DetectedObject] = []
        for obj_id, obj in list(self._objects.items()):
            if obj.frame_ts != frame_ts:
                obj.lost_count = getattr(obj, "lost_count", 0) + 1
            else:
                obj.lost_count = 0
        for detection in unmatched:
            candidates = []
            for obj_id, obj in self._objects.items():
                if obj_id in used_ids:
                    continue
                iou = self._iou(detection.box, obj.box)
                dist = self._distance(detection.center, obj.center, self._scale(detection.box))
                score = iou + max(0.0, 1.0 - dist)
                candidates.append((score, obj_id, obj))
            candidates.sort(key=lambda x: x[0], reverse=True)
            matched = False
            for score, obj_id, obj in candidates:
                if obj_id in used_ids:
                    continue
                iou = self._iou(detection.box, obj.box)
                dist = self._distance(detection.center, obj.center, self._scale(detection.box))
                if iou >= self._iou_threshold or (score >= 1.3 and dist < self._center_threshold):
                    obj.update(detection.box, detection.confidence, frame_ts)
                    obj.lost_count = 0
                    assigned.append(obj)
                    used_ids.add(obj_id)
                    matched = True
                    break
            if not matched:
                detection.object_id = f"obj-{self._next_id}"
                self._next_id += 1
                detection.update(detection.box, detection.confidence, frame_ts)
                detection.lost_count = 0
                assigned.append(detection)
        for obj in assigned:
            self._trim(obj)
        return assigned

    def update(self, result: DetectionResult) -> DetectionResult:
        with self._lock:
            assigned = self._assign(result.detections, result.frame_ts)
            stale = [obj_id for obj_id, obj in self._objects.items() if getattr(obj, "lost_count", 0) > self._max_lost_frames]
            for obj_id in stale:
                self._objects.pop(obj_id, None)
            for obj in assigned:
                self._objects[obj.object_id] = obj
            result.detections = assigned
            return result

    def objects(self) -> list[DetectedObject]:
        with self._lock:
            return list(self._objects.values())

    def stats(self) -> dict[str, Any]:
        with self._lock:
            active = sum(1 for obj in self._objects.values() if getattr(obj, "lost_count", 0) == 0)
            lost = len(self._objects) - active
            history = sum(len(obj.history) for obj in self._objects.values())
            return {
                "tracked": len(self._objects),
                "active": active,
                "lost": lost,
                "history_entries": history,
            }


class ObjectDetectorWorker:
    def __init__(self, backend: DetectorBackend | None = None, tracker: ObjectTracker | None = None) -> None:
        self.backend = backend or DummyDetectorBackend()
        self.tracker = tracker or ObjectTracker()
        self.backend.load()

    def process(self, frame: Any, instance: Any = None) -> VisionObservation | None:
        try:
            result = self.backend.detect(frame)
            tracked = self.tracker.update(result)
            return tracked.to_observation()
        except Exception as exc:
            logger.debug("Object detector failed: %s", exc)
            return None
