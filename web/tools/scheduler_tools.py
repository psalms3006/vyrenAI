"""tools/scheduler_tools.py -- Scheduler and job management tools.

Lets VYREN schedule recurring tasks, one-shot jobs, and manage
its own autonomous behavior.
"""

from tools import ToolDef, ToolRegistry


def register(registry: ToolRegistry, scheduler=None):
    """Register all scheduler tools."""

    def schedule_recurring(name: str, handler: str, interval_seconds: int = 300,
                           description: str = "") -> str:
        """Schedule a recurring job that runs at a fixed interval."""
        if scheduler is None:
            return "Error: Scheduler not initialized."
        if interval_seconds < 60:
            return "Error: Minimum interval is 60 seconds."
        job = scheduler.every(
            name=name, handler=handler,
            interval_seconds=interval_seconds,
            description=description or f"Recurring: {name}",
        )
        return f"Scheduled recurring job '{name}' every {interval_seconds}s (id: {job.id})."

    def schedule_once(name: str, handler: str, description: str = "") -> str:
        """Schedule a one-shot job that runs immediately."""
        if scheduler is None:
            return "Error: Scheduler not initialized."
        job = scheduler.once(
            name=name, handler=handler,
            description=description or f"One-shot: {name}",
        )
        return f"Scheduled one-shot job '{name}' (id: {job.id})."

    def cancel_job(job_name: str) -> str:
        """Cancel a scheduled job by its name."""
        if scheduler is None:
            return "Error: Scheduler not initialized."
        for job in scheduler._jobs.values():
            if job.name == job_name and job.status.value != "cancelled":
                if scheduler.cancel(job.id):
                    return f"Cancelled job '{job_name}'."
                return f"Failed to cancel '{job_name}'."
        return f"No active job found with name '{job_name}'."

    def scheduler_status() -> str:
        """Get the status of all scheduled jobs."""
        if scheduler is None:
            return "Error: Scheduler not initialized."
        status = scheduler.get_status()
        lines = [
            f"Scheduler: {'running' if status['running'] else 'stopped'}",
            f"Total jobs: {status['total_jobs']}",
            f"Pending: {status['pending']}, Recurring: {status['recurring']}",
            f"Running now: {status['running_now']}, Failed: {status['failed']}",
            f"Completed: {status['completed']}",
            f"Registered handlers: {', '.join(status['handlers_registered']) or 'none'}",
        ]
        return "\n".join(lines)

    registry.register(ToolDef(
        name="schedule_recurring",
        description=(
            "Schedule a recurring job that runs at a fixed interval. "
            "Handler must be a registered handler name. Minimum interval: 60 seconds."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique name for this job"},
                "handler": {"type": "string", "description": "Name of the registered handler function"},
                "interval_seconds": {"type": "integer", "description": "Seconds between runs (min 60, default 300)"},
                "description": {"type": "string", "description": "What this job does"},
            },
            "required": ["name", "handler"],
        },
        handler=schedule_recurring,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="schedule_once",
        description=(
            "Schedule a one-shot job that runs immediately. "
            "Handler must be a registered handler name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique name for this job"},
                "handler": {"type": "string", "description": "Name of the registered handler function"},
                "description": {"type": "string", "description": "What this job does"},
            },
            "required": ["name", "handler"],
        },
        handler=schedule_once,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="cancel_job",
        description=(
            "Cancel a scheduled job by its name. The job will not run again."
        ),
        parameters={
            "type": "object",
            "properties": {
                "job_name": {"type": "string", "description": "Name of the job to cancel"},
            },
            "required": ["job_name"],
        },
        handler=cancel_job,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="scheduler_status",
        description=(
            "Get the status of the scheduler and all its jobs."
        ),
        parameters={"type": "object", "properties": {}},
        handler=scheduler_status,
        safety_level="safe",
    ))
