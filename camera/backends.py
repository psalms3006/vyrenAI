"""
camera/backends.py -- Optional camera backend abstraction.

Prefer OpenCV when available; otherwise fall back to a synthetic
frame source so the rest of VYREN can still exercise camera APIs,
status reporting, and integration without real hardware or cv2.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from typing import Any, Callable, Optional

logger = logging.getLogger("vyren.camera")

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

HAS_CV2 = cv2 is not None
HAS_NP = np is not None


class _SyntheticFrame:
    """Minimal frame-like object when OpenCV/numpy are unavailable."""

    def __init__(self, width: int, height: int, label: bytes = b"synthetic") -> None:
        self.width = width
        self.height = height
        self.shape = (height, width, 3)
        self._payload = bytearray(label * (width * height * 3 // len(label) + 1))[
            : width * height * 3
        ]

    def tobytes(self) -> bytes:
        return bytes(self._payload)

    def __len__(self) -> int:
        return len(self._payload)


@dataclass
class CameraBackendConfig:
    camera_index: int
    width: int
    height: int
    fps: int


@dataclass
class CameraMetrics:
    frames_captured: int = 0
    frames_dropped: int = 0
    reconnect_count: int = 0
    last_frame_ts: float = 0.0
    current_fps: float = 0.0
    current_camera_index: int = -1
    state: str = "idle"
    recording_path: str | None = None
    frame_shape: tuple[int, int, int] | None = None


class _SyntheticBackend:
    """Software frame source used when no camera backend is available."""

    def __init__(self, config: CameraBackendConfig, frames: Queue[Any], stop_event: threading.Event, on_frame: Optional[Callable[[Any], None]] = None):
        self._config = config
        self._frames = frames
        self._stop_event = stop_event
        self._on_frame = on_frame
        self._metrics = CameraMetrics(current_camera_index=config.camera_index, frame_shape=(config.height, config.width, 3))

    @property
    def metrics(self) -> CameraMetrics:
        return self._metrics

    def run(self) -> None:
        interval = 1.0 / max(self._config.fps, 1)
        counter = 0
        frame = None
        if HAS_CV2 and HAS_NP:
            frame = np.zeros((self._config.height, self._config.width, 3), dtype=np.uint8)  # type: ignore
        else:
            frame = _SyntheticFrame(self._config.width, self._config.height)

        last_fps_ts = time.monotonic()
        frames_since_last = 0

        while not self._stop_event.is_set():
            if isinstance(frame, _SyntheticFrame):
                counter += 1
                payload = frame._payload  # type: ignore[attr-defined]
                if payload:
                    payload[0] = (payload[0] + 1) % 256

            now = time.monotonic()
            self._metrics.frames_captured += 1
            self._metrics.last_frame_ts = now
            frames_since_last += 1

            if now - last_fps_ts >= 1.0:
                self._metrics.current_fps = frames_since_last / (now - last_fps_ts)
                frames_since_last = 0
                last_fps_ts = now

            try:
                self._frames.put_nowait(frame)
            except Full:
                self._metrics.frames_dropped += 1

            if self._on_frame is not None:
                try:
                    self._on_frame(frame)
                except Exception:
                    pass

            self._stop_event.wait(timeout=interval)


class _OpenCvBackend:
    """Real capture backend using OpenCV."""

    def __init__(self, config: CameraBackendConfig, frames: Queue[Any], stop_event: threading.Event, on_frame: Optional[Callable[[Any], None]] = None):
        self._config = config
        self._frames = frames
        self._stop_event = stop_event
        self._on_frame = on_frame
        self._metrics = CameraMetrics(current_camera_index=config.camera_index, frame_shape=(config.height, config.width, 3))

    @property
    def metrics(self) -> CameraMetrics:
        return self._metrics

    def run(self) -> None:
        if not HAS_CV2:
            raise RuntimeError("OpenCV is not available")

        cap = cv2.VideoCapture(self._config.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open camera index={self._config.camera_index}")

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.height)
        cap.set(cv2.CAP_PROP_FPS, self._config.fps)

        self._metrics.state = "running"
        last_fps_ts = time.monotonic()
        frames_since_last = 0

        while not self._stop_event.is_set():
            try:
                ret, frame = cap.read()
            except Exception as exc:
                logger.debug("Camera read error: %s", exc)
                self._metrics.reconnect_count += 1
                time.sleep(0.05)
                continue

            if not ret:
                self._metrics.frames_dropped += 1
                time.sleep(0.005)
                continue

            now = time.monotonic()
            self._metrics.frames_captured += 1
            self._metrics.last_frame_ts = now
            frames_since_last += 1

            if now - last_fps_ts >= 1.0:
                self._metrics.current_fps = frames_since_last / (now - last_fps_ts)
                frames_since_last = 0
                last_fps_ts = now

            try:
                self._frames.put_nowait(frame)
            except Full:
                self._metrics.frames_dropped += 1

            if self._on_frame is not None:
                try:
                    self._on_frame(frame)
                except Exception:
                    pass

        try:
            cap.release()
        except Exception:
            pass
        self._metrics.state = "stopped"


class CameraSession:
    """Owns one capture session, independent of backend choice."""

    def __init__(self, config: CameraBackendConfig):
        self.config = config
        self.frames: Queue[Any] = Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._on_frame: Optional[Callable[[Any], None]] = None
        self.backend = self._create_backend(config)

    def _create_backend(self, config: CameraBackendConfig):
        if HAS_CV2:
            return _OpenCvBackend(config, self.frames, self._stop_event)
        return _SyntheticBackend(config, self.frames, self._stop_event)

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name=f"camera-{self.config.camera_index}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    @property
    def metrics(self) -> CameraMetrics:
        return self.backend.metrics

    def _run(self) -> None:
        try:
            self.backend.run()
        except Exception as exc:
            logger.error("Camera session error: %s", exc)
            self.backend.metrics.state = "failed"
