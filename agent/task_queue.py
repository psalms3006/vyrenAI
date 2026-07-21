"""
agent/task_queue.py -- Priority-based autonomous task queue for VYREN.

A single-worker background queue that accepts goals, plans them with AI,
and executes step-by-step. Tasks have priorities and can be cancelled.

Inspired by Mark-XXXIX-OR's agent/task_queue.py but integrated with
VYREN's tool registry, event bus, and context system.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("vyren.agent.queue")


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(int, Enum):
    LOW = 3
    NORMAL = 2
    HIGH = 1
    CRITICAL = 0


@dataclass(order=True)
class Task:
    """A single autonomous task with priority ordering."""
    sort_key: tuple = field(init=False, repr=False)
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: float = field(default_factory=time.time)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    goal: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    error: str = ""
    steps_total: int = 0
    steps_completed: int = 0
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    on_complete: Callable[[str], None] | None = None

    def __post_init__(self):
        # Lower priority number = higher priority, then earlier created = higher
        self.sort_key = (self.priority.value, self.created_at)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "goal": self.goal[:100],
            "status": self.status.value,
            "priority": self.priority.name,
            "steps": f"{self.steps_completed}/{self.steps_total}",
            "result": self.result[:200] if self.result else "",
            "error": self.error[:200] if self.error else "",
        }


class TaskQueue:
    """
    Thread-safe priority task queue with a single background worker.

    Usage:
        queue = get_task_queue(ctx)
        task_id = queue.submit("Research Nigerian fintech startups and save to file")
        # ... later
        status = queue.get_status(task_id)
    """

    def __init__(self, ctx: dict | None = None):
        self._queue: list[Task] = []
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._running = False
        self._worker_thread: threading.Thread | None = None
        self._ctx = ctx or {}
        self._task_map: dict[str, Task] = {}

    def submit(
        self,
        goal: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        on_complete: Callable[[str], None] | None = None,
    ) -> str:
        """Submit a new goal for autonomous execution. Returns task ID."""
        task = Task(
            goal=goal,
            priority=priority,
            on_complete=on_complete,
        )
        with self._lock:
            self._queue.append(task)
            self._task_map[task.task_id] = task
            self._queue.sort()
            self._condition.notify()

        logger.info(
            "Task submitted: %s [%s] %s",
            task.task_id, priority.name, goal[:80],
        )

        # Publish event
        event_bus = self._ctx.get("event_bus")
        if event_bus:
            try:
                from event_bus import Event
                event_bus.publish_sync(Event(
                    type="agent.task_submitted",
                    source="task_queue",
                    data={"task_id": task.task_id, "goal": goal},
                ))
            except Exception:
                pass

        return task.task_id

    def cancel(self, task_id: str) -> bool:
        """Cancel a pending or running task."""
        with self._lock:
            task = self._task_map.get(task_id)
        if not task:
            return False
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False
        task.cancel_flag.set()
        task.status = TaskStatus.CANCELLED
        logger.info("Task cancelled: %s", task_id)
        return True

    def get_status(self, task_id: str) -> dict | None:
        """Get the status of a task."""
        task = self._task_map.get(task_id)
        return task.to_dict() if task else None

    def get_all_tasks(self) -> list[dict]:
        """Get status of all tasks."""
        return [t.to_dict() for t in self._task_map.values()]

    def start(self):
        """Start the background worker thread."""
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="vyren-task-queue",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Task queue worker started")

    def stop(self):
        """Stop the worker thread."""
        self._running = False
        with self._condition:
            self._condition.notify_all()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        logger.info("Task queue worker stopped")

    def _worker_loop(self):
        """Background worker: pop highest-priority task, execute it."""
        while self._running:
            with self._condition:
                # Wait for a task
                while not self._queue and self._running:
                    self._condition.wait(timeout=2.0)

                if not self._running:
                    break

                if not self._queue:
                    continue

                task = self._queue.pop(0)

            # Skip cancelled tasks
            if task.status == TaskStatus.CANCELLED:
                continue

            # Execute the task
            self._execute_task(task)

    def _execute_task(self, task: Task):
        """Execute a single task using the AgentExecutor."""
        task.status = TaskStatus.RUNNING

        try:
            from agent.executor import AgentExecutor
            executor = AgentExecutor(self._ctx)

            def speak(text: str):
                """Speak intermediate results (used by long-running tools)."""
                voice = self._ctx.get("voice_runtime")
                if voice and hasattr(voice, "speak"):
                    try:
                        voice.speak(text)
                    except Exception:
                        pass
                logger.info("[Agent] %s", text[:100])

            result = executor.execute(
                goal=task.goal,
                speak=speak,
                cancel_flag=task.cancel_flag,
            )

            if task.cancel_flag.is_set():
                task.status = TaskStatus.CANCELLED
                task.error = "Cancelled by user"
            else:
                task.status = TaskStatus.COMPLETED
                task.result = result

            logger.info(
                "Task %s completed: %s",
                task.task_id,
                result[:100] if result else "(empty)",
            )

        except Exception as e:
            if task.cancel_flag.is_set():
                task.status = TaskStatus.CANCELLED
            else:
                task.status = TaskStatus.FAILED
                task.error = f"{type(e).__name__}: {e}"
            logger.error(
                "Task %s failed: %s", task.task_id, task.error,
            )

        # Notify callback
        if task.on_complete:
            try:
                task.on_complete(task.result if task.status == TaskStatus.COMPLETED else task.error)
            except Exception:
                pass

        # Publish event
        event_bus = self._ctx.get("event_bus")
        if event_bus:
            try:
                from event_bus import Event
                event_bus.publish_sync(Event(
                    type="agent.task_completed",
                    source="task_queue",
                    data=task.to_dict(),
                ))
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_queue: TaskQueue | None = None
_queue_lock = threading.Lock()


def get_task_queue(ctx: dict | None = None) -> TaskQueue:
    """Get or create the global task queue singleton."""
    global _queue
    with _queue_lock:
        if _queue is None:
            _queue = TaskQueue(ctx)
            _queue.start()
        return _queue