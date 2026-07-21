"""
agent/__init__.py -- Agent subsystem for VYREN.

Provides autonomous task execution with planning, step-by-step
execution, and AI-powered error recovery.

Inspired by Mark-XXXIX-OR's agent/ subsystem but adapted to VYREN's
architecture: uses VYREN's provider.py, tool registry, event bus,
and memory system instead of direct API calls.
"""

from agent.task_queue import TaskQueue, TaskPriority, TaskStatus, get_task_queue
from agent.executor import AgentExecutor

__all__ = [
    "TaskQueue", "TaskPriority", "TaskStatus",
    "get_task_queue", "AgentExecutor",
]