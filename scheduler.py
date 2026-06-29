"""
scheduler.py — Job scheduler for autonomous VYREN behavior.

Supports:
  - One-shot jobs (run once at a specific time)
  - Recurring jobs (cron-style intervals)
  - Event-triggered jobs (run when an event fires)
  - Priority queue (higher priority jobs run first)
  - Graceful cancellation
  - Job history and status tracking

Integrates with the event bus for trigger-based scheduling.
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("vyren.scheduler")

JOBS_FILE = Path(os.path.expanduser("~/.vyren/jobs.json"))


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECURRING = "recurring"


@dataclass
class Job:
    """A scheduled unit of work."""
    id: str
    name: str
    handler: str              # Handler function name
    handler_ref: Callable | None = field(default=None, repr=False)
    status: JobStatus = JobStatus.PENDING
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_run: str | None = None
    next_run: str | None = None
    last_result: str | None = None
    error: str | None = None
    run_count: int = 0
    fail_count: int = 0
    priority: int = 5         # 1=highest
    # Schedule config
    schedule_type: str = "once"  # "once", "interval", "cron", "event"
    interval_seconds: int = 0
    cron_expr: str = ""          # e.g. "0 9 * * 1-5" (9am weekdays)
    event_trigger: str = ""      # Event type that triggers this job
    # Metadata
    description: str = ""
    tags: list[str] = field(default_factory=list)
    timeout_seconds: int = 300


class JobStore:
    """Persistent job storage."""

    def __init__(self, path: Path = JOBS_FILE):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r") as f:
                    self._jobs = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._jobs = {}

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._jobs, f, indent=2, ensure_ascii=False)

    def save_job(self, job: Job):
        """Persist a job (without the callable reference)."""
        self._jobs[job.id] = {
            "id": job.id,
            "name": job.name,
            "handler": job.handler,
            "status": job.status.value,
            "created": job.created,
            "last_run": job.last_run,
            "next_run": job.next_run,
            "last_result": job.last_result,
            "error": job.error,
            "run_count": job.run_count,
            "fail_count": job.fail_count,
            "priority": job.priority,
            "schedule_type": job.schedule_type,
            "interval_seconds": job.interval_seconds,
            "cron_expr": job.cron_expr,
            "event_trigger": job.event_trigger,
            "description": job.description,
            "tags": job.tags,
            "timeout_seconds": job.timeout_seconds,
        }
        self._save()

    def load_all(self) -> list[dict]:
        return list(self._jobs.values())

    def get_pending(self) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        return [
            j for j in self._jobs.values()
            if j["status"] in ("pending", "recurring")
            and j.get("next_run") and j["next_run"] <= now
        ]


class Scheduler:
    """
    Job scheduler for autonomous VYREN behavior.

    Usage:
        scheduler = Scheduler()

        # Register a handler
        scheduler.register("check_email", my_email_checker)

        # Schedule a recurring job
        scheduler.every("email_check", "check_email", interval_seconds=300)

        # Schedule a one-shot job
        scheduler.once("backup", "run_backup", run_at="2024-12-25T09:00:00Z")

        # Start the scheduler loop
        scheduler.start()
    """

    def __init__(self):
        self._handlers: dict[str, Callable] = {}
        self._jobs: dict[str, Job] = {}
        self._store = JobStore()
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._job_counter = 0

    def register(self, name: str, handler: Callable):
        """Register a named handler function."""
        self._handlers[name] = handler
        logger.debug(f"Registered job handler: {name}")

    def once(self, name: str, handler: str, run_at: str | None = None,
             priority: int = 5, description: str = "", timeout: int = 300) -> Job:
        """Schedule a one-shot job. If run_at is None, runs immediately."""
        job = self._create_job(
            name=name, handler=handler, schedule_type="once",
            priority=priority, description=description, timeout_seconds=timeout,
        )
        job.next_run = run_at or datetime.now(timezone.utc).isoformat()
        self._store.save_job(job)
        logger.info(f"Scheduled one-shot job: {name} at {job.next_run}")
        return job

    def every(self, name: str, handler: str, interval_seconds: int = 300,
              priority: int = 5, description: str = "", timeout: int = 300) -> Job:
        """Schedule a recurring job."""
        job = self._create_job(
            name=name, handler=handler, schedule_type="interval",
            interval_seconds=interval_seconds, priority=priority,
            description=description, timeout_seconds=timeout,
        )
        job.next_run = datetime.now(timezone.utc).isoformat()
        job.status = JobStatus.RECURRING
        self._store.save_job(job)
        logger.info(f"Scheduled recurring job: {name} every {interval_seconds}s")
        return job

    def on_event(self, name: str, handler: str, event_type: str,
                 priority: int = 5, description: str = "") -> Job:
        """Schedule a job that triggers on an event."""
        job = self._create_job(
            name=name, handler=handler, schedule_type="event",
            event_trigger=event_type, priority=priority, description=description,
        )
        job.status = JobStatus.RECURRING
        self._store.save_job(job)
        logger.info(f"Scheduled event-triggered job: {name} on '{event_type}'")
        return job

    def cancel(self, job_id: str) -> bool:
        """Cancel a scheduled job."""
        job = self._jobs.get(job_id)
        if job:
            job.status = JobStatus.CANCELLED
            self._store.save_job(job)
            return True
        return False

    def _create_job(self, **kwargs) -> Job:
        self._job_counter += 1
        job_id = f"job_{int(time.time())}_{self._job_counter}"
        job = Job(id=job_id, **kwargs)
        # Wire up the actual handler if registered
        if job.handler in self._handlers:
            job.handler_ref = self._handlers[job.handler]
        self._jobs[job.id] = job
        return job

    def trigger_event(self, event_type: str, event_data: dict | None = None):
        """Trigger all jobs subscribed to this event type."""
        for job in self._jobs.values():
            if job.status == JobStatus.CANCELLED:
                continue
            if job.schedule_type == "event" and job.event_trigger == event_type:
                self._execute_job(job, event_data or {})

    def _execute_job(self, job: Job, context: dict | None = None):
        """Execute a job in a background thread."""
        if not job.handler_ref:
            handler = self._handlers.get(job.handler)
            if not handler:
                logger.error(f"No handler registered for job '{job.name}' ({job.handler})")
                job.error = f"Handler '{job.handler}' not registered"
                job.status = JobStatus.FAILED
                job.fail_count += 1
                self._store.save_job(job)
                return
            job.handler_ref = handler

        job.status = JobStatus.RUNNING
        self._store.save_job(job)

        def run():
            try:
                result = job.handler_ref(context or {})
                job.last_result = str(result)[:500] if result else "Done."
                job.status = JobStatus.RECURRING if job.schedule_type != "once" else JobStatus.COMPLETED
                job.run_count += 1
                logger.info(f"Job '{job.name}' completed (run #{job.run_count})")
            except Exception as e:
                job.error = f"{type(e).__name__}: {e}"
                job.status = JobStatus.RECURRING if job.schedule_type != "once" else JobStatus.FAILED
                job.fail_count += 1
                logger.error(f"Job '{job.name}' failed: {e}")
            finally:
                job.last_run = datetime.now(timezone.utc).isoformat()
                # Set next run for recurring jobs
                if job.schedule_type == "interval" and job.status == JobStatus.RECURRING:
                    from datetime import timedelta
                    last = datetime.fromisoformat(job.last_run)
                    next_time = last + timedelta(seconds=job.interval_seconds)
                    job.next_run = next_time.isoformat()
                self._store.save_job(job)

        t = threading.Thread(target=run, name=f"job-{job.name}", daemon=True)
        t.start()

    def _tick(self):
        """Check for due jobs and execute them."""
        now = datetime.now(timezone.utc)
        due_jobs = []

        with self._lock:
            for job in self._jobs.values():
                if job.status in (JobStatus.CANCELLED,):
                    continue
                if job.next_run and job.status in (JobStatus.PENDING, JobStatus.RECURRING):
                    try:
                        next_time = datetime.fromisoformat(job.next_run)
                        if next_time <= now:
                            due_jobs.append(job)
                    except ValueError:
                        pass

        for job in due_jobs:
            self._execute_job(job)

    def _loop(self):
        """Main scheduler loop."""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
            time.sleep(5)  # Check every 5 seconds

    def start(self):
        """Start the scheduler in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Scheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        """Get scheduler status for display."""
        jobs = list(self._jobs.values())
        return {
            "running": self._running,
            "total_jobs": len(jobs),
            "pending": sum(1 for j in jobs if j.status == JobStatus.PENDING),
            "recurring": sum(1 for j in jobs if j.status == JobStatus.RECURRING),
            "running_now": sum(1 for j in jobs if j.status == JobStatus.RUNNING),
            "failed": sum(1 for j in jobs if j.status == JobStatus.FAILED),
            "completed": sum(1 for j in jobs if j.status == JobStatus.COMPLETED),
            "handlers_registered": list(self._handlers.keys()),
        }