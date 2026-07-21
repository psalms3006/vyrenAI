"""
brain/reasoning.py -- Reasoning Engine.

Provides the ONE reasoning engine shared by all interfaces.
Manages context windows, conversation history, and model interaction.

The reasoning engine handles:
  - Context budget management
  - Conversation history compression
  - Multi-step reasoning coordination
  - Provider selection (Gemini vs Ollama) based on connectivity
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("vyren.brain.reasoning")


@dataclass
class ReasoningResult:
    """Result from a reasoning pass."""
    text: str = ""
    function_calls: list = field(default_factory=list)
    provider: str = "gemini"
    duration_ms: int = 0
    context_used: int = 0


class ReasoningEngine:
    """
    Central reasoning engine. ONE engine for all interfaces.

    Voice, text, UI, and API all use this same engine.
    It selects the appropriate provider based on connectivity
    and manages context efficiently.
    """

    def __init__(self, ctx: dict):
        self._ctx = ctx
        self._max_history_tokens = 8000  # Approximate token budget

    def reason(self, messages: list, system_prompt: str = "",
               tools: list | None = None,
               on_chunk: Callable[[str], None] | None = None) -> ReasoningResult:
        """
        Execute a reasoning pass using the best available provider.

        Automatically selects Gemini (online) or Ollama (offline).
        """
        from provider import run_turn, TurnResult

        # Determine provider based on connectivity
        connectivity = self._ctx.get("connectivity")
        if connectivity and connectivity.is_offline:
            # Offline: use Ollama, no tools
            tools = None
            provider = "ollama"
        else:
            provider = "gemini"

        # Refresh system prompt if needed
        if not system_prompt:
            system_prompt = self._ctx.get("system_prompt", "")
        if not tools:
            tools = self._ctx.get("gemini_tools", [])

        # Compress context if too long
        messages = self._manage_context(messages)

        start = time.time()
        try:
            result = run_turn(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                on_chunk=on_chunk,
            )
        except Exception as e:
            logger.error(f"Reasoning error: {e}")
            result = TurnResult(text=f"[Reasoning error: {e}]")

        duration = int((time.time() - start) * 1000)

        return ReasoningResult(
            text=result.text,
            function_calls=result.function_calls,
            provider=provider,
            duration_ms=duration,
            context_used=sum(
                len(str(m)) for m in messages
            ),
        )

    def refresh_system_prompt(self):
        """Rebuild the system prompt with fresh context."""
        from system_prompt import build_system_prompt

        memory = self._ctx.get("memory")
        world_model = self._ctx.get("world_model")
        knowledge_graph = self._ctx.get("knowledge_graph")

        memory_context = memory.build_context() if memory else ""
        world_context = world_model.to_context_string() if world_model else ""
        kg_context = knowledge_graph.to_context_string() if knowledge_graph else ""

        self._ctx["system_prompt"] = build_system_prompt(
            memory_context=memory_context,
            world_context=world_context,
            kg_context=kg_context,
        )

    def _manage_context(self, messages: list) -> list:
        """
        Manage context window size.

        If the conversation exceeds the budget, summarize older messages.
        This prevents context overflow while preserving recent context.
        """
        if len(messages) <= 10:
            return messages

        # Keep the last N messages, summarize older ones
        max_messages = 10
        if len(messages) > max_messages:
            old_messages = messages[:-max_messages]
            recent_messages = messages[-max_messages:]

            # Create a summary placeholder for older messages
            summary_parts = []
            for msg in old_messages:
                role = msg.get("role", "?")
                parts = msg.get("parts", [])
                for part in parts:
                    if "text" in part:
                        summary_parts.append(f"[{role}] {part['text'][:100]}")

            summary_text = "Earlier conversation summary:\n" + "\n".join(summary_parts[-6:])

            messages = [
                {"role": "user", "parts": [{"text": summary_text}]},
                {"role": "model", "parts": [{"text": "Understood. I have context from earlier in our conversation."}]},
            ] + recent_messages

        return messages

    def get_status(self) -> dict:
        connectivity = self._ctx.get("connectivity")
        provider = "ollama" if connectivity and connectivity.is_offline else "gemini"
        return {
            "provider": provider,
            "max_history_tokens": self._max_history_tokens,
        }