"""
agents/specialized.py -- Specialized agents for multi-agent collaboration.

Each agent has a specific responsibility and expertise area.
The coordinator routes tasks to the most appropriate agent.
"""

import logging
import time
from agents.base import BaseAgent, AgentResult, AgentCapability
from typing import Any

logger = logging.getLogger("vyren.agents")


class PlannerAgent(BaseAgent):
    """Breaks goals into executable steps."""

    name = "planner"
    description = "Breaks complex goals into step-by-step executable plans"
    capabilities = [
        AgentCapability("plan", "Create execution plans from goals"),
        AgentCapability("decompose", "Break down complex tasks"),
        AgentCapability("replan", "Adjust plans when execution fails"),
    ]

    async def _execute(self, task: str, context: dict) -> AgentResult:
        planner = context.get("planner")
        if not planner:
            return AgentResult(agent=self.name, task=task, success=False, error="Planner not in context")

        plan = planner.create_plan(task)
        return AgentResult(
            agent=self.name, task=task, success=True,
            output=f"Plan created: {plan.id} with 0 steps. Call add_step to populate.",
            data={"plan_id": plan.id},
        )



class ResearcherAgent(BaseAgent):
    """Finds information from the web and knowledge base."""

    name = "researcher"
    description = "Research agent: searches web, knowledge graph, and memory for information"
    capabilities = [
        AgentCapability("web_search", "Search the web for information"),
        AgentCapability("kg_search", "Search the knowledge graph"),
        AgentCapability("memory_search", "Search memory for relevant facts"),
        AgentCapability("fact_check", "Verify claims and cross-reference sources"),
    ]

    async def _execute(self, task: str, context: dict) -> AgentResult:
        kg = context.get("knowledge_graph")
        results = []
        if kg:
            entities = kg.search(task)
            results.append(f"KG: {len(entities)} entities found")
        return AgentResult(
            agent=self.name, task=task, success=True,
            output=f"Research results: {'; '.join(results) or 'No results yet'}",
        )


class ReviewAgent(BaseAgent):
    """Reviews code, plans, and decisions."""

    name = "reviewer"
    description = "Code and plan reviewer: checks quality, identifies issues, suggests improvements"
    capabilities = [
        AgentCapability("review_code", "Review code for quality and issues"),
        AgentCapability("review_plan", "Review execution plans for completeness"),
        AgentCapability("security_review", "Check for security concerns"),
    ]

    async def _execute(self, task: str, context: dict) -> AgentResult:
        return AgentResult(
            agent=self.name, task=task, success=True,
            output=f"Review queued for: {task[:80]}",
        )


def register_default_agents(registry) -> list:
    """Register all default specialized agents."""
    from agents.developer import DeveloperAgent
    agents = [PlannerAgent(), DeveloperAgent(), ResearcherAgent(), ReviewAgent()]
    for agent in agents:
        registry.register(agent)
    return agents
