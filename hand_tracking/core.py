"""
hand_tracking.py -- Hand tracking and gesture recognition for VYREN.

Backends:
- MediaPipeHandBackend: real MediaPipe Hands/GestureRecognizer when available
- SyntheticHandBackend: deterministic synthetic hand data for testing

Supported gestures:
- PINCH
- EXPAND
- DRAG
- ROTATE
- POINT
- GRAB
- RELEASE
- WAVE

Events:
- GestureDetected(gesture, hand, confidence, meta)
"""
from __future__ import annotations

import dataclasses
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

logger = logging.getLogger("vyren.hand_tracking")

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------
_HAS_MP = False
try:  # pragma: no cover - environment dependent
    import mediapipe as mp  # type: ignore

    _HAS_MP = True
except Exception:
    mp = None  # type: ignore

_HAS_CV2 = False
try:  # pragma: no cover - environment dependent
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:
    cv2 = None  # type: ignore

_HAS_NP = False
try:  # pragma: no cover - environment dependent
    import numpy as np  # type: ignore

    _HAS_NP = True
except Exception:
    np = None  # type: ignore


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class GestureType:
    PINCH = "PINCH"
    EXPAND = "EXPAND"
    DRAG = "DRAG"
    ROTATE = "ROTATE"
    POINT = "POINT"
    GRAB = "GRAB"
    RELEASE = "RELEASE"
    WAVE = "WAVE"
    NONE = "NONE"


@dataclass
class HandLandmark:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    name: str = ""


@dataclass
class Hand:
    handedness: str = "unknown"
    landmarks: list[HandLandmark] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class GestureEvent:
    gesture: str = GestureType.NONE
    hand: str = "unknown"
    confidence: float = 0.0
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _dist(a: HandLandmark, b: HandLandmark) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _angle(a: HandLandmark, b: HandLandmark, c: HandLandmark) -> float:
    ab = (a.x - b.x, a.y - b.y)
    cb = (c.x - b.x, c.y - b.y)
    dot = ab[0] * cb[0] + ab[1] * cb[1]
    norm = math.hypot(*ab) * math.hypot(*cb)
    if norm == 0:
        return 0.0
    val = max(-1.0, min(1.0, dot / norm))
    return math.acos(val)


def _centroid(landmarks: Iterable[HandLandmark]) -> tuple[float, float]:
    xs, ys = [], []
    for lm in landmarks:
        xs.append(lm.x)
        ys.append(lm.y)
    if not xs:
        return 0.0, 0.0
    return sum(xs) / len(xs), sum(ys) / len(ys)


# ---------------------------------------------------------------------------
# Gesture recognition
# ---------------------------------------------------------------------------

class GestureRecognizer:
    REQUIRED_GESTURES = (
        GestureType.PINCH,
        GestureType.EXPAND,
        GestureType.DRAG,
        GestureType.ROTATE,
        GestureType.POINT,
        GestureType.GRAB,
        GestureType.RELEASE,
        GestureType.WAVE,
    )

    def recognize(self, hand: Hand, previous: Optional[Hand]) -> GestureEvent:
        landmarks = hand.landmarks
        if len(landmarks) < 21:
            return GestureEvent()

        thumb = landmarks[4]
        index = landmarks[8]
        middle = landmarks[12]
        ring = landmarks[16]
        pinky = landmarks[20]
        wrist = landmarks[0]
        index_mcp = landmarks[5]
        middle_mcp = landmarks[9]
        ring_mcp = landmarks[13]
        pinky_mcp = landmarks[17]

        pinch_dist = _dist(thumb, index)
        expand_dist = _dist(thumb, pinky)
        index_extended = index.y < landmarks[6].y
        middle_extended = middle.y < landmarks[10].y
        ring_extended = ring.y < landmarks[14].y
        pinky_extended = pinky.y < landmarks[18].y
        extended_count = sum([index_extended, middle_extended, ring_extended, pinky_extended])

        if pinch_dist < 0.06:
            meta = {"pinch_distance": round(pinch_dist, 4)}
            return GestureEvent(gesture=GestureType.PINCH, hand=hand.handedness, confidence=hand.confidence, meta=meta)

        if expand_dist > 0.22 and extended_count >= 3:
            meta = {"expand_distance": round(expand_dist, 4)}
            return GestureEvent(gesture=GestureType.EXPAND, hand=hand.handedness, confidence=hand.confidence, meta=meta)

        if index_extended and not middle_extended:
            angle = _angle(index_mcp, index, landmarks[7])
            if angle < 0.55:
                return GestureEvent(gesture=GestureType.POINT, hand=hand.handedness, confidence=hand.confidence)

        fist = not index_extended and not middle_extended and not ring_extended and not pinky_extended
        if fist:
            meta = {"fist": True}
            return GestureEvent(gesture=GestureType.GRAB, hand=hand.handedness, confidence=hand.confidence, meta=meta)

        if previous and previous.landmarks:
            prev_wrist = previous.landmarks[0]
            dx = wrist.x - prev_wrist.x
            dy = wrist.y - prev_wrist.y
            move_dist = math.hypot(dx, dy)
            if move_dist > 0.04:
                rotation = math.atan2(dy, dx)
                meta = {"dx": round(dx, 4), "dy": round(dy, 4), "angle_rad": round(rotation, 4)}
                return GestureEvent(gesture=GestureType.DRAG, hand=hand.handedness, confidence=hand.confidence, meta=meta)

        if previous and previous.landmarks:
            prev_centroid = _centroid(previous.landmarks[0:21])
            curr_centroid = _centroid(landmarks[0:21])
            prev_angle = math.atan2(previous.landmarks[9].y - prev_centroid[1], previous.landmarks[9].x - prev_centroid[0])
            curr_angle = math.atan2(landmarks[9].y - curr_centroid[1], landmarks[9].x - curr_centroid[0])
            delta = abs(curr_angle - prev_angle)
            delta = min(delta, 2 * math.pi - delta)
            if delta > 0.25:
                return GestureEvent(gesture=GestureType.ROTATE, hand=hand.handedness, confidence=hand.confidence, meta={"delta": round(delta, 4)})

        if previous and previous.landmarks:
            dx = wrist.x - previous.landmarks[0].x
            if abs(dx) > 0.04:
                direction = "right" if dx > 0 else "left"
                return GestureEvent(gesture=GestureType.WAVE, hand=hand.handedness, confidence=hand.confidence, meta={"direction": direction})

        return GestureEvent(gesture=GestureType.RELEASE, hand=hand.handedness, confidence=hand.confidence)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class HandBackend:
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def read_frame(self): ...
    def release(self) -> None: ...


class SyntheticHandBackend(HandBackend):
    def __init__(self, cycle: float = 1.0) -> None:
        self._cycle = cycle
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def read_frame(self):
        if not self._running:
            return None
        t = time.monotonic() % self._cycle
        phase = t / max(self._cycle, 1e-6)

        if phase < 0.3:
            gesture = GestureType.PINCH
        elif phase < 0.45:
            gesture = GestureType.POINT
        elif phase < 0.6:
            gesture = GestureType.WAVE
        elif phase < 0.75:
            gesture = GestureType.DRAG
        else:
            gesture = GestureType.RELEASE

        landmarks = [
            HandLandmark(x=0.5 + 0.1 * math.sin(phase * 2.0 * math.pi), y=0.5 + 0.1 * math.cos(phase * 2.0 * math.pi), name="wrist"),
            HandLandmark(x=0.55, y=0.45, name="thumb_cmc"),
            HandLandmark(x=0.58, y=0.40, name="thumb_mcp"),
            HandLandmark(x=0.62, y=0.36, name="thumb_ip"),
            HandLandmark(x=0.64, y=0.34 if gesture != GestureType.PINCH else 0.37, name="thumb_tip"),
            HandLandmark(x=0.52, y=0.38, name="index_mcp"),
            HandLandmark(x=0.52, y=0.32, name="index_pip"),
            HandLandmark(x=0.52, y=0.27, name="index_dip"),
            HandLandmark(x=0.52, y=0.23 if gesture != GestureType.PINCH else 0.29, name="index_tip"),
            HandLandmark(x=0.49, y=0.37, name="middle_mcp"),
            HandLandmark(x=0.49, y=0.31, name="middle_pip"),
            HandLandmark(x=0.49, y=0.26, name="middle_dip"),
            HandLandmark(x=0.49, y=0.22, name="middle_tip"),
            HandLandmark(x=0.46, y=0.38, name="ring_mcp"),
            HandLandmark(x=0.46, y=0.33, name="ring_pip"),
            HandLandmark(x=0.46, y=0.28, name="ring_dip"),
            HandLandmark(x=0.46, y=0.24, name="ring_tip"),
            HandLandmark(x=0.43, y=0.40, name="pinky_mcp"),
            HandLandmark(x=0.43, y=0.35, name="pinky_pip"),
            HandLandmark(x=0.43, y=0.31, name="pinky_dip"),
            HandLandmark(x=0.43, y=0.28, name="pinky_tip"),
        ]
        hand = Hand(handedness="Right", landmarks=landmarks, confidence=0.88)
        return {"hands": [hand], "timestamp": time.time(), "gesture": gesture}

    def release(self) -> None:
        self.stop()


class MediaPipeHandBackend(HandBackend):
    def __init__(self, max_hands: int = 2, min_detection_confidence: float = 0.5, min_tracking_confidence: float = 0.5) -> None:
        if not _HAS_MP:
            raise RuntimeError("mediapipe is not installed")
        self._max_hands = max_hands
        self._min_detection_confidence = min_detection_confidence
        self._min_tracking_confidence = min_tracking_confidence
        self._hands = None
        self._capture = None

    def start(self) -> None:
        if self._hands is None:
            self._hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=self._max_hands,
                min_detection_confidence=self._min_detection_confidence,
                min_tracking_confidence=self._min_tracking_confidence,
            )
        if _HAS_CV2 and self._capture is None:
            self._capture = cv2.VideoCapture(0)

    def stop(self) -> None:
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                pass
            self._capture = None

    def read_frame(self):
        if self._capture is None or not self._capture.isOpened():
            return None
        ok, image = self._capture.read()
        if not ok:
            return None
        image.flags.writeable = False
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self._hands.process(image)
        hands = []
        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                landmarks = [
                    HandLandmark(x=lm.x, y=lm.y, z=lm.z, name=str(idx))
                    for idx, lm in enumerate(hand_landmarks.landmark)
                ]
                hands.append(Hand(handedness="Right", landmarks=landmarks, confidence=0.9))
        return {"hands": hands, "timestamp": time.time()}

    def release(self) -> None:
        self.stop()
        if self._hands is not None:
            try:
                self._hands.close()
            except Exception:
                pass
            self._hands = None


# ---------------------------------------------------------------------------
# Hand tracker
# ---------------------------------------------------------------------------

class HandTracker:
    def __init__(
        self,
        backend: Optional[HandBackend] = None,
        recognizer: Optional[GestureRecognizer] = None,
        min_confidence: float = 0.5,
        cooldown_seconds: float = 0.35,
        on_gesture: Optional[Callable[[GestureEvent], None]] = None,
    ) -> None:
        self._backend = backend or SyntheticHandBackend()
        self._recognizer = recognizer or GestureRecognizer()
        self._min_confidence = min_confidence
        self._cooldown_seconds = cooldown_seconds
        self._on_gesture = on_gesture
        self._previous: Optional[Hand] = None
        self._last_gesture = GestureType.NONE
        self._last_gesture_time = 0.0
        self._lock = threading.Lock()
        self._active = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._active = True
        self._backend.start()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._active = False
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._backend.stop()

    def status(self) -> dict:
        with self._lock:
            return {
                "active": self._active,
                "backend": type(self._backend).__name__,
                "mediapipe_available": _HAS_MP,
                "last_gesture": self._last_gesture,
            }

    def _run(self) -> None:
        while self._active:
            frame = self._backend.read_frame()
            if frame is None:
                time.sleep(0.05)
                continue
            hands = frame.get("hands") or []
            best_hand = None
            for hand in hands:
                if hand.confidence >= self._min_confidence and (best_hand is None or hand.confidence > best_hand.confidence):
                    best_hand = hand

            if best_hand is None:
                self._previous = None
                time.sleep(0.01)
                continue

            event = self._recognizer.recognize(best_hand, self._previous)
            now = time.monotonic()
            if event.gesture != GestureType.NONE and (event.gesture != self._last_gesture or now - self._last_gesture_time > self._cooldown_seconds):
                with self._lock:
                    self._last_gesture = event.gesture
                    self._last_gesture_time = now
                if self._on_gesture is not None:
                    try:
                        self._on_gesture(event)
                    except Exception as exc:
                        logger.debug("Gesture callback failed: %s", exc)

            self._previous = best_hand
            time.sleep(0.01)
