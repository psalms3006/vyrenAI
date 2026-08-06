"""
camera/manager.py -- VYREN Camera Engine.

Responsibilities:
- Enumerate cameras
- Start/stop capture sessions
- Capture single frames
- Stream frames into a thread-safe queue
- Record to file when requested
- Take timestamped photos
- Switch cameras at runtime
- Auto-reconnect on capture failure
- Surface FPS/health metrics

Design:
- One CameraManager instance owns all camera sessions.
- Each CameraSession wraps a capture source and exposes:
    - frames queue
    - capture thread
    - metrics/fps state
- Public API is intentionally small:
    start()
    stop()
    switch_camera(camera_index or camera_id)
    capture_frame(timeout=...)
    capture_stream(max_queue_size=...)
    record(path, ...)
    take_photo(path)
    status()

This is intentionally transport-agnostic; it does not depend on
voice/vision/gesture code. Other subsystems subscribe to frames
through the returned queue or snapshot APIs.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any, Callable, Optional

from camera.backends import (
    CameraBackendConfig,
    CameraMetrics,
    CameraSession,
    HAS_CV2,
)

logger = logging.getLogger("vyren.camera")


class CameraError(Exception):
    pass


class CameraNotFoundError(CameraError):
    pass


@dataclass
class CameraInfo:
    index: int
    name: str = ""
    backend: str = "opencv"
    recommended_width: int = 1280
    recommended_height: int = 720
    recommended_fps: int = 30
    extra: dict = field(default_factory=dict)


class CameraManager:
    def __init__(self, default_camera_index: int = 0, width: int = 1280, height: int = 720, fps: int = 30):
        self._default_camera_index = default_camera_index
        self._width = width
        self._height = height
        self._fps = fps
        self._session: CameraSession | None = None
        self._lock = threading.Lock()
        self._recorder: Any = None
        self._metrics = CameraMetrics()
        self._backend_label = "opencv" if HAS_CV2 else "synthetic"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def backend_label(self) -> str:
        return self._backend_label

    def start(self, camera_index: int | None = None) -> CameraInfo:
        with self._lock:
            return self._start_unlocked(camera_index)

    def stop(self) -> None:
        with self._lock:
            self._stop_unlocked()

    def switch_camera(self, camera_index: int | None = None) -> CameraInfo:
        with self._lock:
            self._stop_unlocked()
            return self._start_unlocked(camera_index)

    def capture_frame(self, timeout: float = 1.0) -> Any:
        session = self._get_active_session()
        if session is None:
            raise CameraError("Camera is not running")
        try:
            return session.frames.get(timeout=timeout)
        except Empty as exc:
            raise CameraError("No frame available") from exc

    def capture_stream(self, max_queue_size: int = 8) -> Queue:
        session = self._get_active_session()
        if session is None:
            raise CameraError("Camera is not running")
        bounded = Queue(maxsize=max_queue_size)

        def _forward(frame: Any) -> None:
            try:
                bounded.put_nowait(frame)
            except Full:
                pass

        session._on_frame = _forward
        return bounded

    def record(self, path: str | Path, camera_index: int | None = None) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not str(target).lower().endswith(".avi"):
            target = target.with_suffix(".avi")

        with self._lock:
            if self._session is None:
                self._start_unlocked(camera_index)
            self._metrics.recording_path = str(target)

        logger.info("Camera recording requested: %s", target)

    def take_photo(self, path: str | Path) -> Path:
        frame = self.capture_frame(timeout=2.0)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not str(target).lower().endswith(".png"):
            target = target.with_suffix(".png")
        if not HAS_CV2:
            raise CameraError("Photo save requires OpenCV")
        try:
            import cv2  # type: ignore
            cv2.imwrite(str(target), frame)
        except Exception as exc:
            raise CameraError(f"Photo save failed: {exc}") from exc
        logger.info("Photo saved: %s", target)
        return target

    def status(self) -> dict[str, Any]:
        with self._lock:
            session = self._session
        if session is not None:
            metrics = session.metrics
        else:
            metrics = self._metrics
        return {
            "state": metrics.state,
            "camera_index": metrics.current_camera_index,
            "backend": self._backend_label,
            "resolution": [self._width, self._height],
            "fps": metrics.current_fps,
            "frames_captured": metrics.frames_captured,
            "frames_dropped": metrics.frames_dropped,
            "reconnect_count": metrics.reconnect_count,
            "last_frame_ts": metrics.last_frame_ts,
            "recording_path": metrics.recording_path,
        }

    def enumerate_cameras(self) -> list[CameraInfo]:
        cameras: list[CameraInfo] = []
        if HAS_CV2:
            try:
                import cv2  # type: ignore
                for index in range(8):
                    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
                    opened = cap.isOpened()
                    name = ""
                    if opened:
                        try:
                            name = str(cap.get(cv2.CAP_PROP_DEVICE_NAME)) or ""
                        except Exception:
                            name = f"Camera {index}"
                        cap.release()
                    if opened:
                        cameras.append(CameraInfo(index=index, name=name, backend="opencv"))
            except Exception as exc:
                logger.debug("Camera enumeration failed: %s", exc)
        return cameras

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_active_session(self) -> CameraSession | None:
        with self._lock:
            return self._session

    def _start_unlocked(self, camera_index: int | None) -> CameraInfo:
        camera_index = camera_index if camera_index is not None else self._default_camera_index
        session = CameraSession(CameraBackendConfig(camera_index=camera_index, width=self._width, height=self._height, fps=self._fps))
        session.start()
        self._session = session
        self._metrics.current_camera_index = camera_index
        self._metrics.state = session.metrics.state
        return CameraInfo(index=camera_index, name=f"Camera {camera_index}", backend=self._backend_label, recommended_width=self._width, recommended_height=self._height, recommended_fps=self._fps)

    def _stop_unlocked(self) -> None:
        if self._session is not None:
            try:
                self._session.stop()
            except Exception:
                pass
            session_metrics = self._session.metrics
            self._metrics.frames_captured = session_metrics.frames_captured
            self._metrics.frames_dropped = session_metrics.frames_dropped
            self._metrics.reconnect_count = session_metrics.reconnect_count
            self._metrics.last_frame_ts = session_metrics.last_frame_ts
            self._metrics.current_fps = session_metrics.current_fps
            self._metrics.current_camera_index = self._session.config.camera_index
            self._metrics.state = "idle"
            self._metrics.recording_path = session_metrics.recording_path
            self._session = None
