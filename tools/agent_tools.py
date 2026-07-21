"""
tools/agent_tools.py -- Autonomous task execution tool for VYREN.

Provides the agent_task tool that allows the model (or user) to submit
multi-step autonomous goals. These are queued and executed in the
background by the agent subsystem.

Inspired by Mark-XXXIX-OR's agent_task action, but uses VYREN's
own TaskQueue and AgentExecutor.
"""


def register(registry, ctx=None):
    """Register agent tools."""

    def agent_task(
        goal: str,
        priority: str = "normal",
    ) -> str:
        """Submit a multi-step autonomous task for background execution.

        Use this for complex goals that require 3+ tool calls across
        different tools (e.g. "research X and save a report", "create a
        project from scratch").

        For simple single-tool actions, call the tool directly instead.

        Args:
            goal: The high-level goal to accomplish autonomously.
            priority: Task priority: "low", "normal", "high", "critical".
        """
        try:
            from agent.task_queue import TaskQueue, TaskPriority, get_task_queue
        except ImportError:
            return "Agent subsystem not available."

        priority_map = {
            "low": TaskPriority.LOW,
            "normal": TaskPriority.NORMAL,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.CRITICAL,
        }
        task_priority = priority_map.get(priority.lower(), TaskPriority.NORMAL)

        queue = get_task_queue(ctx)
        task_id = queue.submit(goal=goal, priority=task_priority)

        return f"Task queued (ID: {task_id}, priority: {priority}). Working on it now."

    def get_task_status(task_id: str) -> str:
        """Check the status of a previously submitted autonomous task.

        Args:
            task_id: The task ID returned by agent_task.
        """
        try:
            from agent.task_queue import get_task_queue
        except ImportError:
            return "Agent subsystem not available."

        queue = get_task_queue()
        status = queue.get_status(task_id)
        if not status:
            return f"No task found with ID: {task_id}"

        return (
            f"Task {status['task_id']}: {status['status'].upper()}\n"
            f"Goal: {status['goal']}\n"
            f"Progress: {status['steps']}\n"
            + (f"Result: {status['result']}" if status.get("result") else "")
            + (f"\nError: {status['error']}" if status.get("error") else "")
        )

    def list_tasks() -> str:
        """List all autonomous tasks and their statuses."""
        try:
            from agent.task_queue import get_task_queue
        except ImportError:
            return "Agent subsystem not available."

        queue = get_task_queue()
        tasks = queue.get_all_tasks()
        if not tasks:
            return "No tasks submitted yet."

        lines = []
        for t in tasks:
            lines.append(
                f"[{t['status'].upper()}] {t['task_id']} "
                f"({t['priority']}) {t['goal']}"
                + (f" — {t['steps']}" if t['steps'] != "0/0" else "")
            )
        return "\n".join(lines)

    registry.register(__import__("tools").ToolDef(
        name="agent_task",
        description=(
            "Submit a complex multi-step goal for autonomous background execution. "
            "The system will plan the steps, execute them, handle errors, and "
            "report back. Use for goals requiring 3+ tool calls."
        ),
        parameters={
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The high-level goal to accomplish",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "critical"],
                    "description": "Task priority (default: normal)",
                },
            },
            "required": ["goal"],
        },
        handler=agent_task,
        safety_level="safe",
    ))

    registry.register(__import__("tools").ToolDef(
        name="get_task_status",
        description="Check the status of an autonomous task by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID from agent_task",
                },
            },
            "required": ["task_id"],
        },
        handler=get_task_status,
        safety_level="safe",
    ))

    registry.register(__import__("tools").ToolDef(
        name="list_tasks",
        description="List all autonomous tasks and their current statuses.",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=list_tasks,
        safety_level="safe",
    ))