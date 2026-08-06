"""
vision/engine.py -- VYREN continuous Vision Engine.

Design:
- Asynchronous frame pipeline
- Multiple model workers can consume from a shared frame queue
- Results are normalized into a WorldModel-compatible observation
- Observers can subscribe to vision results without coupling to models
- Integrated with FrameSourceManager for monitor/webcam/synthetic input

Public surface:
    VisionEngine
    VisionConfig
    VisionObservation
    VisionModelWorker
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any, Callable, Type

logger = logging.getLogger("vyren.vision")


class VisionError(Exception):
    pass


@dataclass
class VisionConfig:
    max_queue_size: int = 8
    worker_count: int = 2
    frame_interval_s: float = 0.25
    save_debug_frames: bool = False
    debug_dir: Path | None = None
    max_result_history: int = 128


@dataclass
class VisionObservation:
    source: str = "vision"
    frame_ts: float = 0.0
    model: str = ""
    summary: str = ""
    objects: list[dict] = field(default_factory=list)
    text: str = ""
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)


class _ModelWorker:
    def __init__(
        self,
        name: str,
        in_queue: Queue,
        out_queue: Queue,
        stop_event: threading.Event,
        worker_cls: Type | None = None,
        worker_instance: Any = None,
    ):
        self.name = name
        self.in_queue = in_queue
        self.out_queue = out_queue
        self._stop_event = stop_event
        self._worker_cls = worker_cls
        self._worker_instance = worker_instance
        self._thread = threading.Thread(target=self._run, name=f"vision-{name}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)

    def _run(self) -> None:
        logger.info("Vision worker started: %s", self.name)
        instance = self._worker_instance
        if instance is None and self._worker_cls is not None:
            try:
                instance = self._worker_cls()
            except Exception as exc:
                logger.debug("Vision worker %s init failed: %s", self.name, exc)
        while not self._stop_event.is_set():
            try:
                frame = self.in_queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                result = self.process(frame, instance=instance)
                if result is not None:
                    try:
                        self.out_queue.put_nowait(result)
                    except Full:
                        pass
            except Exception as exc:
                logger.debug("Vision worker %s failed: %s", self.name, exc)
        logger.info("Vision worker stopped: %s", self.name)

    def process(self, frame: Any, instance: Any = None) -> VisionObservation | None:
        if instance is not None and hasattr(instance, "process"):
            try:
                return instance.process(frame)
            except Exception as exc:
                logger.debug("Vision worker %s process error: %s", self.name, exc)
                return None
        return VisionObservation(summary="sample", frame_ts=time.monotonic())


class VisionEngine:
    def __init__(self, config: VisionConfig | None = None, world_model: Any = None, memory: Any = None, reasoning: Any = None):
        self._config = config or VisionConfig()
        self._frame_queue: Queue[Any] = Queue(maxsize=self._config.max_queue_size)
        self._result_queue: Queue[VisionObservation] = Queue(maxsize=self._config.max_queue_size)
        self._result_history: deque[VisionObservation] = deque(maxlen=max(self._config.max_result_history, 1))
        self._result_lock = threading.Lock()
        self._workers: list[_ModelWorker] = []
        self._stop_event = threading.Event()
        self._observers: list[Callable[[VisionObservation], None]] = []
        self._running = False
        self._last_frame_ts = 0.0
        self._world_model = world_model
        self._memory = memory
        self._reasoning = reasoning
        self._source_manager: Any = None
        self._source_thread: Optional[threading.Thread] = None
        self._registered_workers: list[tuple[str, Type, int, Any]] = []

    @property
    def config(self) -> VisionConfig:
        return self._config

    def start(self) -> None:
        self._stop_event.clear()
        if not self._registered_workers:
            for i in range(self._config.worker_count):
                worker = _ModelWorker(
                    f"default-{i}",
                    self._frame_queue,
                    self._result_queue,
                    self._stop_event,
                )
                self._workers.append(worker)
                worker.start()
        else:
            for name, worker_cls, count, instance in self._registered_workers:
                for i in range(max(count, 1)):
                    worker = _ModelWorker(
                        f"{name}-{i}",
                        self._frame_queue,
                        self._result_queue,
                        self._stop_event,
                        worker_cls=worker_cls,
                        worker_instance=instance,
                    )
                    self._workers.append(worker)
                    worker.start()
        self._running = True
        self._start_sources()
        self._start_result_pump()
        logger.info("Vision engine started with %s workers", len(self._workers))

    def stop(self) -> None:
        self._stop_event.set()
        self._running = False
        self._stop_sources()
        for worker in self._workers:
            worker.stop()
        self._workers.clear()

    def _start_sources(self) -> None:
        try:
            from vision.sources import FrameSourceManager

            self._source_manager = FrameSourceManager(fps=max(1, int(1.0 / max(self._config.frame_interval_s, 0.01))))
            self._source_manager.start()

            def source_loop() -> None:
                while not self._stop_event.is_set():
                    try:
                        frame = self._source_manager.next_frame(timeout=max(self._config.frame_interval_s, 0.01))
                        self.submit_frame(frame)
                    except Exception:
                        pass

            self._source_thread = threading.Thread(target=source_loop, name="vision-source-pump", daemon=True)
            self._source_thread.start()
        except Exception as exc:
            logger.debug("Vision source manager unavailable: %s", exc)

    def _stop_sources(self) -> None:
        if self._source_manager is not None:
            try:
                self._source_manager.stop()
            except Exception:
                pass
            self._source_manager = None
        if self._source_thread and self._source_thread.is_alive():
            self._source_thread.join(timeout=3)
        self._source_thread = None

    def _start_result_pump(self) -> None:
        def pump() -> None:
            while not self._stop_event.is_set():
                try:
                    results = self.drain_results(32)
                except Exception:
                    results = []
                for obs in results:
                    try:
                        with self._result_lock:
                            self._result_history.append(obs)
                        if self._world_model is not None and hasattr(self._world_model, "ingest_observation"):
                            self._world_model.ingest_observation(obs)
                        if self._memory is not None and hasattr(self._memory, "ingest_vision_observation"):
                            self._memory.ingest_vision_observation(obs)
                        if self._reasoning is not None and hasattr(self._reasoning, "ingest_vision_observation"):
                            self._reasoning.ingest_vision_observation(obs)
                        for handler in list(self._observers):
                            try:
                                handler(obs)
                            except Exception:
                                pass
                    except Exception:
                        pass
                if not results:
                    self._stop_event.wait(timeout=0.1)

        self._pump_thread = threading.Thread(target=pump, name="vision-result-pump", daemon=True)
        self._pump_thread.start()

    def register_worker(self, worker: Any, count: int = 1, name: str | None = None) -> None:
        worker_cls = worker if isinstance(worker, type) else worker.__class__
        if not hasattr(worker_cls, "process"):
            raise VisionError("Worker must implement process(frame)")
        worker_name = name or getattr(worker, "name", None) or getattr(worker_cls, "__name__", "worker")
        self._registered_workers.append((worker_name, worker_cls, max(count, 1), None if isinstance(worker, type) else worker))

    def submit_frame(self, frame: Any) -> None:
        if not self._running:
            raise VisionError("Vision engine is not running")
        try:
            self._frame_queue.put_nowait(frame)
            self._last_frame_ts = time.monotonic()
        except Full:
            pass

    def drain_results(self, max_results: int = 16) -> list[VisionObservation]:
        results = []
        for _ in range(max_results):
            try:
                results.append(self._result_queue.get_nowait())
            except Empty:
                break
        return results

    def recent_results(self, max_results: int = 16) -> list[VisionObservation]:
        with self._result_lock:
            return list(self._result_history)[-max_results:]

    def observe(self, handler: Callable[[VisionObservation], None]) -> None:
        self._observers.append(handler)

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "queued_frames": self._frame_queue.qsize(),
            "queued_results": self._result_queue.qsize(),
            "worker_count": len(self._workers),
            "observer_count": len(self._observers),
            "last_frame_ts": self._last_frame_ts,
            "source_manager": self._source_manager.status() if self._source_manager is not None else None,
        }
