"""
brain/planner.py -- Intelligent Task Planner.

Decomposes goals into executable steps, selects appropriate agents
and tools, and manages multi-step task execution. The planner is
shared across ALL interfaces (voice, text, UI, API) -- ONE PLANNER.

The planner also handles:
  - Online/offline capability negotiation
  - Task queuing for offline mode
  - Multi-agent collaboration orchestration
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("vyren.brain.planner")


class TaskPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    step_id: int
    description: str
    tool: str | None = None
    agent: str | None = None
    args: dict = field(default_factory=dict)
    requires_online: bool = False
    can_offline_fallback: bool = False
    estimated_duration_ms: int = 0
    completed: bool = False
    result: str = ""


@dataclass
class Plan:
    """A complete execution plan."""
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.MEDIUM
    created_at: float = field(default_factory=time.time)
    status: str = "planned"  # planned, executing, completed, failed, queued


class Planner:
    """
    The central planner for VYREN.

    Responsibilities:
      - Decompose natural language goals into executable steps
      - Select the best agent for each step
      - Negotiate online/offline capabilities
      - Track plan execution progress
      - Support multi-agent collaboration
    """

    def __init__(self, ctx: dict):
        self._ctx = ctx
        self._active_plans: list[Plan] = []
        self._completed_plans: list[Plan] = []
        self._queued_plans: list[Plan] = []

    def plan(self, goal: str, context: str = "") -> Plan:
        """
        Create an execution plan for a goal.

        In a full implementation, this would use the LLM to decompose
        the goal. For now, it creates a basic plan structure that the
        model's tool-calling loop naturally handles.
        """
        plan = Plan(goal=goal)

        # Check connectivity for capability negotiation
        connectivity = self._ctx.get("connectivity")
        online = connectivity.is_online if connectivity else True

        # Determine if this needs to be queued (offline + online-only task)
        if not online and self._requires_internet(goal):
            plan.status = "queued"
            self._queued_plans.append(plan)
            logger.info(f"Task queued (offline): {goal[:60]}")
            return plan

        # For the current implementation, planning is handled by the
        # model's tool-calling loop. The planner provides the framework
        # for future enhancement with explicit plan decomposition.
        plan.status = "planned"
        self._active_plans.append(plan)

        return plan

    def can_execute(self, goal: str) -> tuple[bool, str]:
        """
        Check if a goal can be executed right now.

        Returns (can_execute, reason).
        """
        connectivity = self._ctx.get("connectivity")
        if connectivity and connectivity.is_offline:
            if self._requires_internet(goal):
                return False, "offline_needs_internet"
        return True, "ok"

    def get_queued_tasks(self) -> list[Plan]:
        """Get tasks queued for when connectivity returns."""
        return self._queued_plans

    def process_queue(self):
        """Process queued tasks (called when connectivity is restored)."""
        remaining = []
        for plan in self._queued_plans:
            connectivity = self._ctx.get("connectivity")
            if connectivity and connectivity.is_online:
                plan.status = "planned"
                self._active_plans.append(plan)
                logger.info(f"Unqueued task: {plan.goal[:60]}")
            else:
                remaining.append(plan)
        self._queued_plans = remaining

    def get_status(self) -> dict:
        return {
            "active_plans": len(self._active_plans),
            "completed_plans": len(self._completed_plans),
            "queued_plans": len(self._queued_plans),
        }

    def _requires_internet(self, goal: str) -> bool:
        """Heuristic: does this goal likely require internet?"""
        internet_keywords = [
            "search", "browse", "web", "email", "send", "api",
            "download", "upload", "online", "google", "github",
            "lookup", "fetch", "url", "http", "website",
        ]
        goal_lower = goal.lower()
        return any(kw in goal_lower for kw in internet_keywords)