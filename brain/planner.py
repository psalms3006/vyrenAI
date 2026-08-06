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
import json
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


PLAN_SYSTEM_PROMPT = (
    "You are VYREN's planning module.\n"
    "\n"
    "Break any user goal into a sequence of executable steps using ONLY\n"
    "the tools and agents listed below.\n"
    "\n"
    "ABSOLUTE RULES:\n"
    "- Every step must be independent. Never reference another step's result.\n"
    "- Use the minimum number of steps needed; max 5 steps.\n"
    "- Prefer direct tools over agents unless the task explicitly needs\n"
    "  multi-file development, long-running background work, or a\n"
    "  specialized agent.\n"
    "- If a step needs information you do not have, use web_search.\n"
    "- If a step should save output to disk, use file_controller.\n"
    "- Return ONLY valid JSON. No markdown, no explanation, no code fences.\n"
    "\n"
    "OUTPUT FORMAT:\n"
    "{\n"
    "  \"goal\": \"...\",\n"
    "  \"plan\": [\n"
    "    {\n"
    "      \"step\": 1,\n"
    "      \"description\": \"...\",\n"
    "      \"tool\": \"tool_name\",\n"
    "      \"agent\": null,\n"
    "      \"args\": {},\n"
    "      \"requires_online\": false,\n"
    "      \"can_offline_fallback\": false,\n"
    "      \"estimated_duration_ms\": 0,\n"
    "      \"completed\": false,\n"
    "      \"result\": \"\"\n"
    "    }\n"
    "  ],\n"
    "  \"priority\": \"medium\",\n"
    "  \"status\": \"planned\"\n"
    "}\n"
)


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    step: int = 0
    description: str = ""
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
    goal: str = ""
    plan: list[PlanStep] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.MEDIUM
    status: str = "planned"
    created_at: float = field(default_factory=time.time)


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

    def create_plan(self, goal: str, context: str = "") -> Plan:
        """
        Create an execution plan for a goal.

        Uses the configured lightweight model to produce a structured
        JSON plan. If LLM planning is unavailable, returns a minimal
        single-step passthrough plan so execution can still proceed.
        """
        plan = Plan(goal=goal)

        connectivity = self._ctx.get("connectivity")
        online = connectivity.is_online if connectivity else True
        if not online and self._requires_internet(goal):
            plan.status = "queued"
            self._queued_plans.append(plan)
            logger.info("Task queued (offline): %s", goal[:60])
            return plan

        steps = self._generate_steps(goal, context)
        if not steps:
            step = PlanStep(
                step=1,
                description=goal,
                tool=None,
                agent=None,
                requires_online=False,
                can_offline_fallback=True,
                estimated_duration_ms=0,
            )
            steps = [step]

        plan.plan = steps
        plan.status = "planned"
        plan.priority = self._infer_priority(goal)
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
        return list(self._queued_plans)

    def process_queue(self):
        """Process queued tasks (called when connectivity is restored)."""
        remaining = []
        for plan in self._queued_plans:
            connectivity = self._ctx.get("connectivity")
            if connectivity and connectivity.is_online:
                plan.status = "planned"
                self._active_plans.append(plan)
                logger.info("Unqueued task: %s", plan.goal[:60])
            else:
                remaining.append(plan)
        self._queued_plans = remaining

    def get_status(self) -> dict:
        return {
            "active_plans": len(self._active_plans),
            "completed_plans": len(self._completed_plans),
            "queued_plans": len(self._queued_plans),
        }

    def to_dict(self, plan: Plan) -> dict:
        return {
            "goal": plan.goal,
            "plan": [
                {
                    "step": step.step,
                    "description": step.description,
                    "tool": step.tool,
                    "agent": step.agent,
                    "args": step.args or {},
                    "requires_online": step.requires_online,
                    "can_offline_fallback": step.can_offline_fallback,
                    "estimated_duration_ms": step.estimated_duration_ms,
                    "completed": step.completed,
                    "result": step.result,
                }
                for step in plan.plan
            ],
            "priority": plan.priority.value,
            "status": plan.status,
        }

    def _generate_steps(self, goal: str, context: str) -> list[PlanStep]:
        provider = self._ctx.get("provider")
        if provider is None:
            return []

        registry = self._ctx.get("registry")
        tool_names: list[str] = []
        agent_names: list[str] = []
        if registry is not None:
            try:
                tool_names = sorted(getattr(registry, "names", lambda: [])())
            except Exception:
                tool_names = []
        agent_names = sorted(getattr(self._ctx.get("agent_registry", {}), "keys", lambda: [])())

        lines = [f"Goal: {goal}"]
        if context:
            lines.append(f"Context: {context}")
        lines.append("Available tools: " + ", ".join(tool_names[:80]))
        lines.append("Available agents: " + ", ".join(agent_names[:40]))
        prompt = "\n".join(lines)

        try:
            raw = provider.plan_json(
                prompt,
                system=PLAN_SYSTEM_PROMPT,
            )
        except TypeError:
            raw = None

        if not isinstance(raw, dict):
            try:
                raw = provider.chat(
                    prompt,
                    system=PLAN_SYSTEM_PROMPT,
                    max_tokens=2048,
                    temperature=0.2,
                )
                if not raw:
                    return []
            except Exception:
                return []
            try:
                clean = str(raw).strip()
                if clean.startswith("```"):
                    parts = clean.split("```")
                    clean = parts[1] if len(parts) > 1 else clean
                    if clean.startswith("json"):
                        clean = clean[4:]
                raw = json.loads(clean.strip().rstrip("`").strip())
            except Exception:
                return []

        if not isinstance(raw, dict) or not isinstance(raw.get("plan"), list):
            return []

        steps: list[PlanStep] = []
        for item in raw.get("plan", []):
            if not isinstance(item, dict):
                continue
            step = PlanStep(
                step=int(item.get("step", 0) or 0),
                description=str(item.get("description", "")),
                tool=item.get("tool"),
                agent=item.get("agent"),
                args=item.get("args") or {},
                requires_online=bool(item.get("requires_online", False)),
                can_offline_fallback=bool(item.get("can_offline_fallback", False)),
                estimated_duration_ms=int(item.get("estimated_duration_ms", 0) or 0),
                completed=bool(item.get("completed", False)),
                result=str(item.get("result", "")),
            )
            if step.description:
                steps.append(step)
        return steps

    def _infer_priority(self, goal: str) -> TaskPriority:
        goal_lower = goal.lower()
        if any(k in goal_lower for k in ["urgent", "now", "critical", "emergency"]):
            return TaskPriority.CRITICAL
        if any(k in goal_lower for k in ["important", "priority", "asap"]):
            return TaskPriority.HIGH
        return TaskPriority.MEDIUM

    def _requires_internet(self, goal: str) -> bool:
        internet_keywords = [
            "search", "browse", "web", "email", "send", "api",
            "download", "upload", "online", "google", "github",
            "lookup", "fetch", "url", "http", "website",
        ]
        goal_lower = goal.lower()
        return any(k in goal_lower for k in internet_keywords)
