"""
brain/ -- VYREN's central cognition engine.

The brain is the orchestrator that receives input, decides the cognitive
strategy, and coordinates all other subsystems. It is NOT a chatbot
wrapper -- it is an autonomous decision-making system.

Pipeline: Input -> Understand -> Reason -> Plan -> Execute -> Reflect -> Output
"""

import logging
import time
from typing import Any, Callable

logger = logging.getLogger("vyren.brain")


class Brain:
    """
    Central cognition engine. Coordinates reasoning, planning, memory
    retrieval, tool execution, and reflection.

    The brain decides HOW to think, not just WHAT to think.
    """

    def __init__(self, ctx: "core.VYRENCtx"):
        self.ctx = ctx
        self._turn_count = 0
        self._session_start = time.time()

    def process(self, user_input: str, history: list,
                on_chunk: Callable[[str], None] | None = None) -> str:
        """
        Process a user input through the full cognitive pipeline.
        Returns the final text response.
        """
        self._turn_count += 1
        turn_start = time.time()

        # Step 1: Retrieve relevant context
        context = self._retrieve_context(user_input, history)

        # Step 2: Decide reasoning mode
        reasoning_mode = self._select_reasoning_mode(user_input, context)

        # Step 3: Build augmented system prompt
        system_prompt = self._build_prompt(context, reasoning_mode)

        # Step 4: Run model turn with tools
        from provider import run_turn
        result = run_turn(
            messages=history,
            system_prompt=system_prompt,
            tools=self.ctx.gemini_tools,
            on_chunk=on_chunk,
        )

        # Step 5: Tool execution loop
        max_rounds = 15
        tool_round = 0
        while result.function_calls and tool_round < max_rounds:
            tool_round += 1
            model_parts = []
            if result.text:
                model_parts.append({"text": result.text})
            for fc in result.function_calls:
                model_parts.append({
                    "function_call": {"name": fc.name, "args": fc.args}
                })
            history.append({"role": "model", "parts": model_parts})

            tool_results = self._execute_tools(result.function_calls)
            history.append({"role": "user", "parts": tool_results})

            result = run_turn(
                messages=history,
                system_prompt=system_prompt,
                tools=self.ctx.gemini_tools,
                on_chunk=on_chunk,
            )

        # Step 6: Post-processing
        final_text = result.text or ""
        if final_text:
            self._post_process(user_input, final_text, turn_start)

        return final_text

    def _retrieve_context(self, user_input: str, history: list) -> dict:
        """Retrieve relevant context from memory, KG, and world model."""
        context = {}

        # Search memory v2 for relevant entries
        memory_results = self.ctx.memory_v2.search(user_input, limit=5)
        if memory_results:
            context["memory"] = memory_results

        # Search knowledge graph for relevant entities
        kg_results = self.ctx.knowledge_graph.search(user_input)
        if kg_results:
            context["knowledge_graph"] = [
                {"name": e.name, "type": e.type.value, "importance": e.importance}
                for e in kg_results[:5]
            ]

        return context

    def _select_reasoning_mode(self, user_input: str, context: dict) -> str:
        """Select the appropriate reasoning mode based on the input."""
        from reasoning import ReasoningMode, ReasoningEngine

        engine = ReasoningEngine()
        return engine.select_mode(user_input, context)

    def _build_prompt(self, context: dict, reasoning_mode: str) -> str:
        """Build the augmented system prompt with context and reasoning hints."""
        prompt = self.ctx.system_prompt

        if reasoning_mode and reasoning_mode != "fast":
            prompt += f"\n\n## Current Reasoning Mode: {reasoning_mode.upper()}"
            from reasoning import ReasoningEngine
            engine = ReasoningEngine()
            hint = engine.get_mode_hint(reasoning_mode)
            if hint:
                prompt += f"\n{hint}"

        return prompt

    def _execute_tools(self, function_calls) -> list:
        """Execute tool calls with safety gating and audit logging."""
        import safety
        tool_results = []

        for fc in function_calls:
            # Safety gate
            if self.ctx.registry.is_consequential(fc.name):
                approved = safety.ask_confirmation(fc.name, fc.args)
                self.ctx.audit.confirmation(fc.name, fc.args, approved)
                if not approved:
                    tool_results.append({
                        "function_response": {
                            "name": fc.name,
                            "response": {"result": "User declined this action. Do not retry without asking again."},
                        }
                    })
                    continue

            self.ctx.audit.info(f"Executing tool: {fc.name}")
            self.ctx.watchdog.start(f"tool:{fc.name}")

            # Publish event
            from event_bus import Event
            self.ctx.event_bus.publish_sync(
                Event(type="vyren.tool_called", source="brain", data={"tool": fc.name})
            )

            tool_output = self.ctx.registry.execute(fc.name, fc.args)
            self.ctx.audit.tool_call(fc.name, fc.args, tool_output[:200])

            # Handle sentinel values
            if tool_output.endswith("_REQUESTED"):
                tool_output = self._execute_post_confirmation(fc.name, fc.args, tool_output)

            self.ctx.watchdog.stop(f"tool:{fc.name}")

            self.ctx.event_bus.publish_sync(
                Event(type="vyren.tool_result", source="brain", data={"tool": fc.name, "success": True})
            )

            tool_results.append({
                "function_response": {
                    "name": fc.name,
                    "response": {"result": tool_output},
                }
            })

        return tool_results

    def _execute_post_confirmation(self, name: str, args: dict, sentinel: str) -> str:
        """Execute actions that required confirmation."""
        import os, sys, subprocess
        try:
            if name == "shutdown_system":
                subprocess.run(["shutdown", "/s", "/t", "5"], check=False, shell=True)
                return "Shutdown initiated."
            elif name == "restart_system":
                subprocess.run(["shutdown", "/r", "/t", "5"], check=False, shell=True)
                return "Restart initiated."
            elif name == "delete_file":
                path = args.get("file_path", "")
                os.remove(path)
                return f"Deleted: {path}"
            elif name == "edit_file":
                path = args.get("file_path", "")
                content = args.get("content", "")
                resolved = os.path.realpath(path)
                os.makedirs(os.path.dirname(resolved), exist_ok=True)
                with open(resolved, "w", encoding="utf-8") as f:
                    f.write(content)
                lines = content.count("\n") + 1
                return f"File written: {resolved} ({lines} lines)"
            elif name == "run_python":
                code = args.get("code", "")
                timeout = args.get("timeout", 30)
                python_exe = sys.executable or "python"
                result = subprocess.run(
                    [python_exe, "-c", code],
                    capture_output=True, text=True, timeout=timeout,
                )
                output = result.stdout
                if result.stderr:
                    output += "\n" + result.stderr
                return output if output.strip() else "(no output)"
            else:
                return sentinel
        except Exception as e:
            return f"Error executing {name}: {type(e).__name__} -- {e}"

    def _post_process(self, user_input: str, response: str, turn_start: float):
        """Post-process after a turn: auto-learn, update context, etc."""
        duration = time.time() - turn_start

        # Auto-remember important facts from the conversation
        self._auto_memorize(user_input, response)

        # Log the turn
        self.ctx.audit.model_turn("model", response[:200])

    def _auto_memorize(self, user_input: str, response: str):
        """Automatically extract and store important information from interactions."""
        # This is a lightweight heuristic -- the model can also explicitly use remember() tool
        # For now, we track interaction patterns
        try:
            from memory_v2 import MemoryLayer
            self.ctx.memory_v2.remember(
                key=f"last_interaction_{int(time.time())}",
                value=f"User: {user_input[:100]} | VYREN: {response[:100]}",
                layer=MemoryLayer.EPISODIC,
                importance=0.2,
                source="auto_memorize",
            )
        except Exception as e:
            logger.debug(f"Auto-memorize skipped: {e}")

    def get_status(self) -> dict:
        return {
            "turn_count": self._turn_count,
            "session_duration_seconds": int(time.time() - self._session_start),
        }