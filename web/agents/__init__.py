"""
agents/__init__.py — Agent registry and coordinator.

The coordinator is the central dispatcher for VYREN's multi-agent system.
It receives tasks, routes them to the best agent, handles disagreements
between agents, and combines results.
"""

from agents.base import BaseAgent, AgentResult, AgentCapability


class AgentRegistry:
    """Registry of all available agents."""

    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent):
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent | None:
        return self._agents.get(name)

    def all_agents(self) -> list[BaseAgent]:
        return list(self._agents.values())

    def find_best_agent(self, task: str) -> BaseAgent | None:
        """Find the agent with the highest confidence for a task."""
        best = None
        best_score = 0.0
        for agent in self._agents.values():
            score = agent.can_handle(task)
            if score > best_score:
                best_score = score
                best = agent
        return best if best_score > 0.3 else None


class Coordinator:
    """
    Central coordinator for multi-agent collaboration.

    Routes tasks to specialized agents, handles multi-agent workflows,
    detects disagreements, and combines results.

    Usage:
        coordinator = Coordinator(registry)

        # Simple delegation
        result = await coordinator.delegate("analyze the VYREN codebase for bugs")

        # Multi-agent: get multiple perspectives
        results = await coordinator.collaborate("design a database schema", agents=["planner", "developer"])
    """

    def __init__(self, registry: AgentRegistry, shared_context: dict | None = None):
        self.registry = registry
        self._shared_context = shared_context or {}
        self._task_history: list[dict] = []

        # Inject shared context into all agents
        for agent in registry.all_agents():
            agent.set_context(self._shared_context)

    async def delegate(self, task: str, agent_name: str | None = None) -> AgentResult:
        """
        Delegate a task to an agent. If agent_name is None, auto-routes.
        """
        if agent_name:
            agent = self.registry.get(agent_name)
            if not agent:
                return AgentResult(
                    agent="coordinator", task=task, success=False,
                    error=f"Agent '{agent_name}' not found.",
                )
        else:
            agent = self.registry.find_best_agent(task)
            if not agent:
                return AgentResult(
                    agent="coordinator", task=task, success=False,
                    error="No agent available for this task.",
                )

        import logging
        logging.getLogger("vyren.coordinator").info(
            f"Delegating to {agent.name}: {task[:80]}"
        )

        result = await agent.handle_task(task, self._shared_context)
        self._task_history.append({
            "task": task, "agent": result.agent,
            "success": result.success, "timestamp": result.duration_ms,
        })
        return result

    async def collaborate(self, task: str,
                           agents: list[str] | None = None,
                           max_agents: int = 3) -> list[AgentResult]:
        """
        Get multiple agents' perspectives on a task.
        Returns results from each agent.
        """
        if not agents:
            # Auto-select top agents by confidence
            scored = []
            for agent in self.registry.all_agents():
                score = agent.can_handle(task)
                if score > 0.3:
                    scored.append((score, agent))
            scored.sort(key=lambda x: -x[0])
            agents = [a.name for _, a in scored[:max_agents]]

        results = []
        for name in agents:
            result = await self.delegate(task, agent_name=name)
            results.append(result)

        return results

    def detect_disagreements(self, results: list[AgentResult]) -> list[dict]:
        """
        Analyze results from multiple agents for disagreements.
        Returns a list of disagreement descriptors.
        """
        disagreements = []
        successful = [r for r in results if r.success and r.output]

        if len(successful) < 2:
            return disagreements

        # Simple disagreement detection: significantly different outputs
        for i in range(len(successful)):
            for j in range(i + 1, len(successful)):
                a, b = successful[i], successful[j]
                # If outputs are very different lengths or content, flag it
                len_diff = abs(len(a.output) - len(b.output))
                avg_len = (len(a.output) + len(b.output)) / 2
                if avg_len > 0 and len_diff / avg_len > 0.5:
                    disagreements.append({
                        "agents": [a.agent, b.agent],
                        "reason": "significantly different output lengths",
                        "outputs": [a.output[:200], b.output[:200]],
                    })

        return disagreements

    def get_status(self) -> dict:
        return {
            "registered_agents": len(self.registry.all_agents()),
            "agents": [a.get_status() for a in self.registry.all_agents()],
            "tasks_completed": len(self._task_history),
        }