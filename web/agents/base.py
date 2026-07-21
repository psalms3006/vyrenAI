"""
agents/base.py — Base agent class for VYREN's multi-agent system.

Every specialized agent (Executive, Planner, Developer, Researcher, etc.)
inherits from BaseAgent. The coordinator dispatches work to agents
and combines their results.

Each agent:
  - Has a name, description, and capabilities
  - Can receive tasks and return results
  - Has access to VYREN's shared context (memory, knowledge graph, world model)
  - Logs its activity to the audit trail
  - Can request help from other agents
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger("vyren.agents")


@dataclass
class AgentResult:
    """Result from an agent's task execution."""
    agent: str
    task: str
    success: bool
    output: str = ""
    data: dict = field(default_factory=dict)
    confidence: float = 1.0
    duration_ms: int = 0
    error: str | None = None
    needs_followup: bool = False
    suggested_agents: list[str] = field(default_factory=list)


@dataclass
class AgentCapability:
    """Describes what an agent can do."""
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)


class BaseAgent:
    """
    Abstract base for all VYREN agents.

    Subclass and implement handle_task() to create a specialized agent.

    Usage:
        class MyAgent(BaseAgent):
            name = "my_agent"
            description = "Does X and Y"
            capabilities = [AgentCapability("do_x", "Performs X")]

            async def handle_task(self, task: str, context: dict) -> AgentResult:
                # Do work
                return AgentResult(agent=self.name, task=task, success=True, output="...")

    The coordinator calls agents through this interface. Agents never call
    each other directly — they go through the coordinator.
    """

    name: str = "base"
    description: str = "Base agent"
    capabilities: list[AgentCapability] = []

    def __init__(self):
        self._context: dict = {}  # Shared context set by coordinator

    def set_context(self, context: dict):
        """Set shared context (memory, knowledge graph, etc.)."""
        self._context = context

    def get_context(self, key: str, default: Any = None) -> Any:
        return self._context.get(key, default)

    async def handle_task(self, task: str, context: dict | None = None) -> AgentResult:
        """
        Execute a task. Override this in subclasses.

        Args:
            task: Natural language description of what to do
            context: Additional context for this specific task

        Returns:
            AgentResult with the outcome
        """
        start = time.time()
        try:
            result = await self._execute(task, context or {})
            result.duration_ms = int((time.time() - start) * 1000)
            return result
        except Exception as e:
            logger.error(f"Agent {self.name} failed: {e}")
            return AgentResult(
                agent=self.name, task=task, success=False,
                error=f"{type(e).__name__}: {e}",
                duration_ms=int((time.time() - start) * 1000),
            )

    async def _execute(self, task: str, context: dict) -> AgentResult:
        """Override this in subclasses. Default raises NotImplementedError."""
        return AgentResult(
            agent=self.name, task=task, success=False,
            error="This agent does not implement direct task execution.",
        )

    def can_handle(self, task: str) -> float:
        """
        Return a confidence score (0-1) for how well this agent can handle
        a task. Override for custom routing logic.
        """
        task_lower = task.lower()
        score = 0.0
        for cap in self.capabilities:
            if cap.name.lower() in task_lower or any(
                word in task_lower for word in cap.description.lower().split()
            ):
                score = max(score, 0.7)
        return score

    def get_status(self) -> dict:
        """Return agent status for monitoring."""
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": [c.name for c in self.capabilities],
            "has_context": bool(self._context),
        }