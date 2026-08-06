"""
vision/sources.py -- Frame acquisition for VYREN vision pipeline.

Supported source kinds:
- monitor: full desktop capture via Windows GDI
- webcam: optional OpenCV VideoCapture
- synthetic: fallback software frames when no source is available
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("vyren.vision")

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

from vision.windows_grab import MonitorCapture, MonitorRect


@dataclass(frozen=True)
class MonitorInfo:
    kind: str = "monitor"
    name: str = ""
    source: str = ""
    width: int = 0
    height: int = 0
    fps: int = 0
    extra: dict = field(default_factory=dict)


class _MonitorSource:
    def __init__(self, info: MonitorInfo, capture: MonitorCapture) -> None:
        self._info = info
        self._capture = capture
        self._rect = MonitorRect(0, 0, info.width, info.height)

    def read(self) -> bytes | None:
        return self._capture.capture(self._rect)


class _WebcamSource:
    def __init__(self, info: MonitorInfo) -> None:
        self._info = info
        self._cap = None
        if cv2 is not None:
            try:
                self._cap = cv2.VideoCapture(info.source, cv2.CAP_DSHOW)
            except Exception:
                self._cap = None

    def read(self) -> bytes | None:
        if self._cap is None:
            return None
        try:
            ret, frame = self._cap.read()
            if not ret:
                return None
            return cv2.imencode(".png", frame)[1].tobytes()
        except Exception:
            return None

    def stop(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None


class _SyntheticSource:
    def __init__(self, info: MonitorInfo) -> None:
        self._info = info
        self._count = 0

    def read(self) -> bytes | None:
        self._count += 1
        if np is not None:
            frame = np.zeros((self._info.height, self._info.width, 3), dtype=np.uint8)
            return cv2.imencode(".png", frame)[1].tobytes() if cv2 is not None else b""
        return b""


class FrameSourceManager:
    """Acquires frames from multiple sources."""

    def __init__(self, fps: int = 5) -> None:
        self._fps = max(fps, 1)
        self._sources: list[Any] = []
        self._current: Any | None = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._queue: Any = __import__("queue").Queue(maxsize=16)
        self._lock = threading.Lock()
        self._processed = 0
        self._dropped = 0
        self._active_source: str | None = None
        self._setup_sources()

    @property
    def config(self) -> dict[str, Any]:
        return {"fps": self._fps}

    def _setup_sources(self) -> None:
        try:
            capture = MonitorCapture()
            monitors = capture.monitors
        except Exception:
            monitors = []

        if monitors:
            for rect in monitors:
                info = MonitorInfo(
                    kind="monitor",
                    name=f"Monitor {rect.index}",
                    source=f"{rect.index}",
                    width=rect.width,
                    height=rect.height,
                    fps=self._fps,
                    extra={"left": rect.left, "top": rect.top, "box": rect.box},
                )
                self._sources.append(_MonitorSource(info, capture))
        else:
            info = MonitorInfo(kind="synthetic", name="Synthetic", source="0", width=320, height=240, fps=self._fps)
            self._sources.append(_SyntheticSource(info))

        if cv2 is not None:
            for index in range(2):
                info = MonitorInfo(
                    kind="webcam",
                    name=f"Webcam {index}",
                    source=str(index),
                    width=640,
                    height=480,
                    fps=self._fps,
                )
                self._sources.append(_WebcamSource(info))

        if not self._sources:
            info = MonitorInfo(kind="synthetic", name="Synthetic", source="0", width=320, height=240, fps=self._fps)
            self._sources.append(_SyntheticSource(info))

    @property
    def sources(self) -> list[MonitorInfo]:
        out = []
        for source in self._sources:
            info = getattr(source, "_info", None)
            if info is None:
                continue
            out.append(MonitorInfo(**info.__dict__))
        return out

    def enumerate_sources(self) -> list[MonitorInfo]:
        return self.sources

    def set_active_source(self, info: MonitorInfo) -> None:
        for source in self._sources:
            current = getattr(source, "_info", None)
            if current is None:
                continue
            if current.kind == info.kind and str(current.source) == str(info.source or current.source):
                with self._lock:
                    self._current = source
                    self._active_source = str(current.source)
                return
        if info.source is not None:
            for source in self._sources:
                current = getattr(source, "_info", None)
                if current and str(current.source) == str(info.source):
                    with self._lock:
                        self._current = source
                        self._active_source = str(current.source)
                    return
        raise ValueError(f"Unknown source: {info}")

    def start(self) -> None:
        self._stop_event.clear()
        if not self._sources:
            self._setup_sources()
        if self._current is None and self._sources:
            self._current = self._sources[0]
            current_info = getattr(self._current, "_info", None)
            self._active_source = getattr(current_info, "source", None)
        self._thread = threading.Thread(target=self._run, name="vision-source", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        for source in self._sources:
            stop = getattr(source, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass

    def next_frame(self, timeout: float = 1.0) -> bytes:
        try:
            return self._queue.get(timeout=timeout)
        except Exception:
            raise RuntimeError("No frame available")

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": not self._stop_event.is_set(),
                "frames_processed": self._processed,
                "frames_dropped": self._dropped,
                "active_source": self._active_source,
                "source_count": len(self._sources),
            }

    def _run(self) -> None:
        interval = 1.0 / max(self._fps, 1)
        while not self._stop_event.is_set():
            source = self._current
            if source is None:
                self._stop_event.wait(timeout=interval)
                continue
            try:
                frame = source.read()
            except Exception:
                frame = None

            if frame is not None:
                try:
                    self._queue.put_nowait(frame)
                    with self._lock:
                        self._processed += 1
                except Exception:
                    with self._lock:
                        self._dropped += 1

            self._stop_event.wait(timeout=interval)
