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

        # Step 1b: For complex/strategic questions, convene a board meeting
        board_advice = ""
        if self._is_boardworthy(user_input):
            board_advice = self._run_board_meeting(user_input)

        # Step 2: Decide reasoning mode
        reasoning_mode = self._select_reasoning_mode(user_input, context)

        # Step 3: Build augmented system prompt
        system_prompt = self._build_prompt(context, reasoning_mode, board_advice=board_advice)

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

    def _is_boardworthy(self, user_input: str) -> bool:
        text = user_input.lower()
        keywords = [
            "board", "advisor", "review", "strategy", "architecture",
            "decision", "tradeoff", "risk", "complex", "compare", "plan",
        ]
        return len(text.split()) >= 12 and any(k in text for k in keywords)

    def _run_board_meeting(self, user_input: str) -> str:
        try:
            registry = self.ctx.registry
            if registry is None:
                return ""
            tool = registry.get("convene_board")
            if tool is None:
                return ""
            output = registry.execute("convene_board", {
                "question": user_input,
                "store": True,
            })
            return f"\n\n[Board of Advisors]\n{output}\n"
        except Exception as exc:
            logger.debug("Board meeting skipped: %s", exc)
            return ""

    def _build_prompt(self, context: dict, reasoning_mode: str, board_advice: str = "") -> str:
        """Build the augmented system prompt with context and reasoning hints."""
        prompt = self.ctx.system_prompt

        if reasoning_mode and reasoning_mode != "fast":
            prompt += f"\n\n## Current Reasoning Mode: {reasoning_mode.upper()}"
            from reasoning import ReasoningEngine
            engine = ReasoningEngine()
            hint = engine.get_mode_hint(reasoning_mode)
            if hint:
                prompt += f"\n{hint}"

        if board_advice:
            prompt += f"\n\n## Advisory Board Output\n{board_advice}"

        return prompt

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
        from post_confirmation import execute_post_confirmation
        return execute_post_confirmation(name, args, sentinel)

    def _post_process(self, user_input: str, response: str, turn_start: float):
        """Post-process after a turn: auto-learn, update context, etc."""
        duration = time.time() - turn_start

        # Auto-remember important facts from the conversation
        self._auto_memorize(user_input, response)

        # Reflect on the turn and update lessons
        self._reflect_on_turn(user_input, response, duration)

        # Log the turn
        self.ctx.audit.model_turn("model", response[:200])

        # Persist identity facts once
        self._ensure_identity_memorized()

    def _auto_memorize(self, user_input: str, response: str):
        """Automatically extract and store important information from interactions."""
        try:
            from memory_v2 import MemoryLayer
            interaction_key = f"last_interaction_{int(time.time())}"
            self.ctx.memory_v2.remember(
                key=interaction_key,
                value=f"User: {user_input[:120]} | VYREN: {response[:120]}",
                layer=MemoryLayer.EPISODIC,
                importance=0.25,
                source="auto_memorize",
            )
            # Compact old interaction memories to avoid unbounded growth.
            self._compact_old_interactions()
        except Exception as e:
            logger.debug("Auto-memorize skipped: %s", e)

    def _compact_old_interactions(self, keep: int = 40):
        """Keep only the most recent interaction memories to save context budget."""
        try:
            from memory_v2 import MemoryLayer
            entries = self.ctx.memory_v2.stores.get(MemoryLayer.EPISODIC)
            if entries is None:
                return
            all_items = entries.all()
            if len(all_items) <= keep:
                return
            all_items.sort(key=lambda e: e.created, reverse=True)
            for entry in all_items[keep:]:
                if entry.key.startswith("last_interaction_"):
                    entries.delete(entry.id)
        except Exception as e:
            logger.debug("Interaction compaction skipped: %s", e)

    def _reflect_on_turn(self, user_input: str, response: str, duration: float):
        """Reflect briefly on the turn and store lessons when useful."""
        try:
            outcome = "success"
            if "error" in response.lower() or duration > 20:
                outcome = "failure"
            elif any(token in response.lower() for token in ["sorry", "retry", "could not"]):
                outcome = "partial"

            self.ctx.reflector.reflect(
                task=user_input[:180],
                outcome=outcome,
                confidence_before=0.5,
            )

            if outcome == "failure":
                self.ctx.learner.learn_mistake(
                    mistake=response[:180],
                    correct_approach="Prefer validation and concise recovery.",
                    context=user_input[:180],
                )
            elif outcome == "success" and len(user_input.strip()) > 20:
                self.ctx.learner.learn_pattern(
                    pattern=f"Successful pattern for: {user_input[:120]}",
                    context=user_input[:180],
                )
        except Exception as e:
            logger.debug("Turn reflection skipped: %s", e)

    def _ensure_identity_memorized(self):
        """Persist core identity facts if they are not already stored."""
        try:
            from memory_v2 import MemoryLayer
            from identity import get_assistant_name, get_product_name, get_company
            assistant_name = get_assistant_name()
            product_name = get_product_name()
            company = get_company()

            existing = self.ctx.memory_v2.recall("assistant_name")
            if not existing:
                self.ctx.memory_v2.remember(
                    "assistant_name",
                    assistant_name,
                    layer=MemoryLayer.SEMANTIC,
                    importance=0.9,
                )
            existing = self.ctx.memory_v2.recall("product_name")
            if not existing:
                self.ctx.memory_v2.remember(
                    "product_name",
                    product_name,
                    layer=MemoryLayer.SEMANTIC,
                    importance=0.9,
                )
            existing = self.ctx.memory_v2.recall("company")
            if not existing:
                self.ctx.memory_v2.remember(
                    "company",
                    company,
                    layer=MemoryLayer.SEMANTIC,
                    importance=0.9,
                )
        except Exception as e:
            logger.debug("Identity memory persistence skipped: %s", e)

    def _retrieve_context(self, user_input: str, history: list) -> dict:
        """Retrieve relevant context from memory, lessons, KG, and world model."""
        context = {}

        memory_results = self.ctx.memory_v2.search(user_input, limit=5)
        if memory_results:
            context["memory"] = memory_results

        try:
            lessons = self.ctx.learner.get_relevant_lessons(user_input, limit=4)
            if lessons:
                context["lessons"] = lessons
        except Exception as e:
            logger.debug("Lesson retrieval skipped: %s", e)

        kg_results = self.ctx.knowledge_graph.search(user_input)
        if kg_results:
            context["knowledge_graph"] = [
                {"name": e.name, "type": e.type.value, "importance": e.importance}
                for e in kg_results[:5]
            ]

        return context

    def get_status(self) -> dict:
        return {
            "turn_count": self._turn_count,
            "session_duration_seconds": int(time.time() - self._session_start),
        }