"""
planner/ -- Goal decomposition and multi-step planning.

The planner behaves like a senior engineer: it breaks goals into milestones,
estimates complexity, identifies dependencies, chooses tools, and monitors
execution. It supports dynamic replanning when things go wrong.
"""

import logging
import time
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("vyren.planner")

PLAN_DIR = Path(os.path.expanduser("~/.vyren/plans"))


class PlanStatus(str, Enum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass
class PlanStep:
    id: str
    description: str
    status: StepStatus = StepStatus.PENDING
    tool: str = ""           # Tool to use (if any)
    tool_args: dict = field(default_factory=dict)
    expected_outcome: str = ""
    actual_outcome: str = ""
    complexity: str = "medium"  # low, medium, high, critical
    estimated_time: str = ""
    dependencies: list[str] = field(default_factory=list)
    verification: str = ""   # How to verify this step succeeded
    notes: str = ""


@dataclass
class Plan:
    id: str
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_steps: int = 0
    failed_steps: int = 0
    total_estimated_time: str = ""
    reasoning_mode: str = "fast"
    context: dict = field(default_factory=dict)
    reflection: str = ""


class PlanStore:
    """Persistent plan storage."""

    def __init__(self):
        PLAN_DIR.mkdir(parents=True, exist_ok=True)
        self._plans: dict[str, Plan] = {}
        self._load()

    def _load(self):
        for f in PLAN_DIR.glob("plan_*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                plan = self._from_dict(data)
                self._plans[plan.id] = plan
            except Exception:
                pass

    def _save(self, plan: Plan):
        path = PLAN_DIR / f"plan_{plan.id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._to_dict(plan), f, indent=2, ensure_ascii=False)

    def _to_dict(self, plan: Plan) -> dict:
        return {
            "id": plan.id, "goal": plan.goal, "status": plan.status.value,
            "created": plan.created, "updated": plan.updated,
            "completed_steps": plan.completed_steps, "failed_steps": plan.failed_steps,
            "total_estimated_time": plan.total_estimated_time,
            "reasoning_mode": plan.reasoning_mode, "reflection": plan.reflection,
            "steps": [
                {
                    "id": s.id, "description": s.description, "status": s.status.value,
                    "tool": s.tool, "tool_args": s.tool_args,
                    "expected_outcome": s.expected_outcome, "actual_outcome": s.actual_outcome,
                    "complexity": s.complexity, "estimated_time": s.estimated_time,
                    "dependencies": s.dependencies, "verification": s.verification,
                    "notes": s.notes,
                }
                for s in plan.steps
            ],
        }

    def _from_dict(self, d: dict) -> Plan:
        steps = []
        for sd in d.get("steps", []):
            sd["status"] = StepStatus(sd["status"])
            steps.append(PlanStep(**{k: v for k, v in sd.items() if k in PlanStep.__dataclass_fields__}))
        d["status"] = PlanStatus(d["status"])
        return Plan(**{k: v for k, v in d.items() if k in Plan.__dataclass_fields__}, steps=steps)

    def save(self, plan: Plan):
        self._plans[plan.id] = plan
        self._save(plan)

    def get(self, plan_id: str) -> Plan | None:
        return self._plans.get(plan_id)

    def get_active(self) -> list[Plan]:
        return [p for p in self._plans.values() if p.status == PlanStatus.IN_PROGRESS]

    def list_all(self) -> list[dict]:
        return [
            {"id": p.id, "goal": p.goal, "status": p.status.value,
             "steps": len(p.steps), "completed": p.completed_steps}
            for p in self._plans.values()
        ]


class Planner:
    """
    Goal decomposition and execution planner.

    Usage:
        planner = Planner(store)

        # Create a plan from a goal
        plan = planner.create_plan("Build a REST API for the todo app")

        # Execute step by step
        for step in plan.steps:
            result = planner.execute_step(plan, step)
    """

    def __init__(self, store: PlanStore, ctx=None):
        self.store = store
        self.ctx = ctx
        self._step_counter = 0

    def _next_id(self) -> str:
        self._step_counter += 1
        return f"step_{int(time.time())}_{self._step_counter}"

    def create_plan(self, goal: str, reasoning_mode: str = "fast") -> Plan:
        """Create a new plan from a goal description."""
        plan_id = f"plan_{int(time.time())}"
        plan = Plan(
            id=plan_id, goal=goal,
            reasoning_mode=reasoning_mode,
            status=PlanStatus.DRAFT,
        )
        self.store.save(plan)
        logger.info(f"Created plan {plan_id}: {goal[:80]}")
        return plan

    def add_step(self, plan: Plan, description: str, tool: str = "",
                 tool_args: dict | None = None, complexity: str = "medium",
                 dependencies: list[str] | None = None,
                 verification: str = "", expected_outcome: str = "") -> PlanStep:
        """Add a step to a plan."""
        step = PlanStep(
            id=self._next_id(),
            description=description,
            tool=tool,
            tool_args=tool_args or {},
            complexity=complexity,
            dependencies=dependencies or [],
            verification=verification,
            expected_outcome=expected_outcome,
        )
        plan.steps.append(step)
        plan.updated = datetime.now(timezone.utc).isoformat()
        self.store.save(plan)
        return step

    def get_next_step(self, plan: Plan) -> PlanStep | None:
        """Get the next step that can be executed (dependencies met)."""
        completed_ids = {s.id for s in plan.steps if s.status == StepStatus.COMPLETED}
        for step in plan.steps:
            if step.status != StepStatus.PENDING:
                continue
            # Check dependencies
            unmet = [d for d in step.dependencies if d not in completed_ids]
            if unmet:
                step.status = StepStatus.BLOCKED
                continue
            return step
        return None

    def execute_step(self, plan: Plan, step: PlanStep) -> str:
        """Execute a plan step using the registry."""
        if not self.ctx:
            return "Error: No context available for execution."

        step.status = StepStatus.IN_PROGRESS
        plan.updated = datetime.now(timezone.utc).isoformat()
        self.store.save(plan)

        try:
            if step.tool and self.ctx.registry:
                result = self.ctx.registry.execute(step.tool, step.tool_args)
            else:
                result = f"Step '{step.description}' marked complete (no tool)."

            step.actual_outcome = result[:500]
            step.status = StepStatus.COMPLETED
            plan.completed_steps += 1
        except Exception as e:
            step.actual_outcome = f"Error: {type(e).__name__} -- {e}"
            step.status = StepStatus.FAILED
            plan.failed_steps += 1

        plan.updated = datetime.now(timezone.utc).isoformat()
        self.store.save(plan)
        return step.actual_outcome

    def replan(self, plan: Plan, failed_step: PlanStep) -> list[PlanStep]:
        """Generate recovery steps after a failure."""
        recovery = PlanStep(
            id=self._next_id(),
            description=f"Recovery: Fix failure in '{failed_step.description}'",
            complexity="high",
            notes=f"Original error: {failed_step.actual_outcome[:200]}",
        )
        plan.steps.append(recovery)
        plan.updated = datetime.now(timezone.utc).isoformat()
        self.store.save(plan)
        return [recovery]

    def complete_plan(self, plan: Plan, reflection: str = ""):
        """Mark a plan as completed."""
        plan.status = PlanStatus.COMPLETED
        plan.reflection = reflection
        plan.updated = datetime.now(timezone.utc).isoformat()
        self.store.save(plan)
        logger.info(f"Plan {plan.id} completed: {plan.goal[:60]}")

    def get_status(self) -> dict:
        active = self.store.get_active()
        return {
            "active_plans": len(active),
            "total_plans": len(self.store.list_all()),
        }