"""
agent/executor.py -- Step-by-step autonomous task executor for VYREN.

Takes a goal, creates an AI-generated plan, then executes each step
using VYREN's tool registry. On failure, uses AI to classify the error
and decide: RETRY, SKIP, REPLAN, or ABORT.

Inspired by Mark-XXXIX-OR's agent/executor.py and agent/error_handler.py,
but uses VYREN's provider.py for model calls and VYREN's ToolRegistry
for tool execution.
"""

import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

logger = logging.getLogger("vyren.agent.executor")

MAX_RETRIES_PER_STEP = 3
MAX_REPLAN_ATTEMPTS = 2


class ErrorAction(str, Enum):
    RETRY = "retry"
    SKIP = "skip"
    REPLAN = "replan"
    ABORT = "abort"


@dataclass
class PlanStep:
    step: int
    tool: str
    description: str
    parameters: dict
    critical: bool = True


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep]


class AgentExecutor:
    """
    Executes autonomous multi-step tasks.

    Pipeline:
      1. create_plan(goal) → list[PlanStep]
      2. For each step:
         a. Execute tool via registry
         b. On failure → analyze_error() → RETRY / SKIP / REPLAN / ABORT
         c. If REPLAN → regenerate remaining steps
      3. Summarize results
    """

    def __init__(self, ctx: dict):
        self._ctx = ctx
        self._registry = ctx.get("registry")
        self._event_bus = ctx.get("event_bus")

    def execute(
        self,
        goal: str,
        speak: Callable[[str], None] | None = None,
        cancel_flag=None,
    ) -> str:
        """Execute a goal end-to-end. Returns the final result text."""
        # Step 1: Plan
        plan = self._create_plan(goal)
        if not plan or not plan.steps:
            return self._fallback_execute(goal, speak)

        logger.info(
            "Plan created: %d steps for '%s'",
            len(plan.steps), goal[:60],
        )
        if speak:
            speak(f"I've broken this into {len(plan.steps)} steps. Starting now.")

        # Step 2: Execute each step
        step_results: list[str] = []
        replan_attempts = 0

        for i, step in enumerate(plan.steps):
            if cancel_flag and cancel_flag.is_set():
                return "Task cancelled."

            logger.info(
                "Step %d/%d: %s(%s)",
                step.step, len(plan.steps), step.tool, step.description[:60],
            )

            if speak and i == 0:
                speak(f"Step one: {step.description}")

            # Try execution with retries
            success = False
            last_error = ""

            for attempt in range(1, MAX_RETRIES_PER_STEP + 1):
                if cancel_flag and cancel_flag.is_set():
                    return "Task cancelled."

                result = self._call_tool(step.tool, step.parameters, step_results)

                if not result.startswith("Error"):
                    step_results.append(result)
                    success = True
                    break

                last_error = result
                logger.warning(
                    "Step %d attempt %d/%d failed: %s",
                    step.step, attempt, MAX_RETRIES_PER_STEP, result[:100],
                )

                # Analyze the error
                if attempt < MAX_RETRIES_PER_STEP:
                    action = self._analyze_error(step, last_error, attempt)
                    logger.info("Error analysis: %s", action.value)

                    if action == ErrorAction.ABORT:
                        if step.critical:
                            return f"Critical step failed: {step.description}. {last_error}"
                        break
                    elif action == ErrorAction.SKIP:
                        if not step.critical:
                            step_results.append(f"(Skipped: {step.description})")
                            success = True
                            break
                        # Critical step can't be skipped, will retry
                    elif action == ErrorAction.REPLAN:
                        break  # Exit retry loop, go to replan
                    # RETRY: continue the for loop

            if not success:
                # Decide: replan or abort
                if replan_attempts < MAX_REPLAN_ATTEMPTS and not step.critical:
                    replan_attempts += 1
                    remaining_goal = f"{goal}\n\nAlready completed:\n" + "\n".join(
                        f"- {r[:100]}" for r in step_results
                    ) + f"\n\nFailed at: {step.description}\nError: {last_error}"

                    new_plan = self._replan(remaining_goal, step_results, step, last_error)
                    if new_plan and new_plan.steps:
                        logger.info("Replan: %d new steps", len(new_plan.steps))
                        if speak:
                            speak(f"Adjusting plan. {len(new_plan.steps)} new steps.")
                        # Replace remaining steps
                        plan.steps = new_plan.steps
                        continue
                    else:
                        return f"Failed to replan after step '{step.description}'. {last_error}"
                else:
                    return f"Failed at step '{step.description}' after {MAX_RETRIES_PER_STEP} attempts. {last_error}"

        # Step 3: Summarize
        summary = self._summarize(goal, step_results)
        return summary

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _create_plan(self, goal: str) -> Plan | None:
        """Use AI to break a goal into steps with tool calls."""
        if not self._registry:
            return None

        # Build available tools list for the planner
        tools_desc = []
        for tool in self._registry.all_tools():
            params_summary = ", ".join(
                f"{k}: {v.get('type', '?')}" for k, v in
                tool.parameters.get("properties", {}).items()
            )
            tools_desc.append(
                f"- {tool.name}({params_summary}): {tool.description}"
            )

        tools_text = "\n".join(tools_desc)

        prompt = (
            "Break this goal into specific steps using the available tools. "
            "Each step must call exactly ONE tool.\n\n"
            f"Available tools:\n{tools_text}\n\n"
            f"Goal: {goal}\n\n"
            "Return ONLY a JSON object with this exact format:\n"
            '{"goal": "...", "steps": [{"step": 1, "tool": "tool_name", '
            '"description": "what this step does", "parameters": {}, '
            '"critical": true}]}\n\n'
            "Rules:\n"
            "- Use tool names EXACTLY as listed above.\n"
            "- Parameters must match the tool's schema.\n"
            "- Mark a step critical=false only if failure is acceptable.\n"
            "- Keep plans to 8 steps or fewer.\n"
            "- If the goal is simple (1 tool call), still return a plan with 1 step."
        )

        try:
            from provider import run_turn_lightweight
            result = run_turn_lightweight(
                messages=[{"role": "user", "parts": [{"text": prompt}]}],
                system_prompt=(
                    "You are a task planner. Return ONLY valid JSON. "
                    "No markdown, no explanation."
                ),
            )

            raw = (result.text or "").strip()
            # Clean markdown fences
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1] if len(parts) > 1 else raw
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip().rstrip("`").strip()

            data = json.loads(raw)
            steps = []
            for s in data.get("steps", []):
                steps.append(PlanStep(
                    step=s.get("step", len(steps) + 1),
                    tool=s.get("tool", ""),
                    description=s.get("description", ""),
                    parameters=s.get("parameters", {}),
                    critical=s.get("critical", True),
                ))
            return Plan(goal=data.get("goal", goal), steps=steps)

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Plan parsing failed: %s", e)
            return None
        except Exception as e:
            logger.warning("Plan creation failed: %s", e)
            return None

    def _replan(
        self, goal: str, completed_results: list[str],
        failed_step: PlanStep, error: str,
    ) -> Plan | None:
        """Generate a revised plan after a failure."""
        prompt = (
            f"The original goal was: {goal}\n\n"
            f"Steps already completed successfully:\n"
            + "\n".join(f"- {r[:150]}" for r in completed_results)
            + f"\n\nThe step that failed: {failed_step.tool} - {failed_step.description}\n"
            f"Error: {error}\n\n"
            "Create a NEW plan to complete the remaining work. "
            "You may use different tools or a different approach.\n"
            "Return ONLY JSON: {\"goal\": \"...\", \"steps\": [...]}"
        )

        try:
            from provider import run_turn_lightweight
            result = run_turn_lightweight(
                messages=[{"role": "user", "parts": [{"text": prompt}]}],
                system_prompt="You are a task planner. Return ONLY valid JSON.",
            )

            raw = (result.text or "").strip()
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1] if len(parts) > 1 else raw
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip().rstrip("`").strip()

            data = json.loads(raw)
            steps = []
            for s in data.get("steps", []):
                steps.append(PlanStep(
                    step=s.get("step", len(steps) + 1),
                    tool=s.get("tool", ""),
                    description=s.get("description", ""),
                    parameters=s.get("parameters", {}),
                    critical=s.get("critical", True),
                ))
            return Plan(goal=data.get("goal", goal), steps=steps)

        except Exception as e:
            logger.warning("Replan failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _call_tool(
        self, tool_name: str, parameters: dict,
        step_results: list[str],
    ) -> str:
        """Execute a single tool via the registry."""
        if not self._registry:
            return f"Error: No tool registry available"

        # Context injection: if writing to a file, include prior results
        if tool_name in ("write_file", "edit_file") and step_results:
            existing_content = "\n".join(f"--- Result {i+1} ---\n{r[:2000]}" for i, r in enumerate(step_results))
            # Don't override explicit content, just add context
            if "content" not in parameters or not parameters["content"]:
                parameters["content"] = existing_content

        self._publish_event("agent.step_start", {
            "tool": tool_name,
            "params": {k: str(v)[:100] for k, v in parameters.items()},
        })

        try:
            result = self._registry.execute(tool_name, parameters)
            self._publish_event("agent.step_complete", {
                "tool": tool_name,
                "success": True,
                "result_preview": result[:200] if result else "",
            })
            return result
        except Exception as e:
            error_msg = f"Error in {tool_name}: {type(e).__name__} -- {e}"
            self._publish_event("agent.step_complete", {
                "tool": tool_name,
                "success": False,
                "error": error_msg,
            })
            return error_msg

    # ------------------------------------------------------------------
    # Error Analysis
    # ------------------------------------------------------------------

    def _analyze_error(
        self, step: PlanStep, error: str, attempt: int,
    ) -> ErrorAction:
        """Use AI to classify an error and decide the recovery action."""
        # If this is the last attempt and step is critical, force replan
        if attempt >= MAX_RETRIES_PER_STEP:
            return ErrorAction.REPLAN if step.critical else ErrorAction.SKIP

        prompt = (
            f"A tool call failed during an autonomous task.\n\n"
            f"Tool: {step.tool}\n"
            f"Description: {step.description}\n"
            f"Parameters: {json.dumps(step.parameters)}\n"
            f"Error: {error}\n"
            f"Attempt: {attempt}/{MAX_RETRIES_PER_STEP}\n"
            f"Is critical step: {step.critical}\n\n"
            "Decide the recovery action:\n"
            '- RETRY: transient error, trying again might work\n'
            '- SKIP: non-critical step, we can continue without it\n'
            '- REPLAN: fundamental issue, need a different approach\n'
            '- ABORT: unrecoverable error\n\n'
            "Reply with ONLY ONE of: RETRY, SKIP, REPLAN, ABORT"
        )

        try:
            from provider import run_turn_lightweight
            result = run_turn_lightweight(
                messages=[{"role": "user", "parts": [{"text": prompt}]}],
                system_prompt="You are an error recovery classifier. Reply ONLY with one word: RETRY, SKIP, REPLAN, or ABORT.",
            )
            text = (result.text or "").strip().upper()

            for action in ErrorAction:
                if action.value in text:
                    # Override: critical steps can't be skipped
                    if action == ErrorAction.SKIP and step.critical:
                        return ErrorAction.REPLAN
                    return action

        except Exception:
            pass

        # Default: retry if we have attempts left
        return ErrorAction.RETRY

    # ------------------------------------------------------------------
    # Summarization
    # ------------------------------------------------------------------

    def _summarize(self, goal: str, step_results: list[str]) -> str:
        """Generate a concise summary of what was accomplished."""
        combined = "\n".join(
            f"Step {i+1}: {r[:300]}" for i, r in enumerate(step_results)
        )

        prompt = (
            f"Goal: {goal}\n\n"
            f"Results from each step:\n{combined}\n\n"
            "Provide a concise summary (2-3 sentences) of what was accomplished."
        )

        try:
            from provider import run_turn_lightweight
            result = run_turn_lightweight(
                messages=[{"role": "user", "parts": [{"text": prompt}]}],
                system_prompt="You are a task summarizer. Be concise and factual.",
            )
            return result.text or "\n".join(step_results[-3:])
        except Exception:
            return "\n".join(step_results[-3:]) if step_results else "Done."

    def _fallback_execute(
        self, goal: str, speak: Callable[[str], None] | None = None,
    ) -> str:
        """Fallback: try to execute as a single web search if planning fails."""
        if self._registry and self._registry.get("web_search"):
            if speak:
                speak(f"Let me search for that.")
            result = self._registry.execute("web_search", {"query": goal})
            return result
        return f"Could not plan or execute: {goal}"

    def _publish_event(self, event_type: str, data: dict):
        """Publish an event to the bus (non-critical)."""
        if self._event_bus:
            try:
                from event_bus import Event
                self._event_bus.publish_sync(Event(
                    type=event_type,
                    source="agent.executor",
                    data=data,
                ))
            except Exception:
                pass