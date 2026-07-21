"""
context/ -- Dynamic context management.

Avoids overflowing context windows by:
  - Hierarchical summarization
  - Conversation compression
  - Memory retrieval (only relevant memories)
  - Semantic chunking
  - Dynamic context assembly
  - Relevance scoring
  - Context budgeting
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("vyren.context")


@dataclass
class ContextBudget:
    """Token budget for context assembly."""
    total: int = 120000       # Max tokens for context
    system_prompt: int = 4000  # Base system prompt
    memory: int = 2000         # Retrieved memories
    knowledge_graph: int = 1000
    world_model: int = 500
    conversation: int = 80000  # Conversation history
    tools: int = 30000         # Tool definitions
    reserved: int = 1000       # Safety margin


@dataclass
class ContextBlock:
    """A block of context with relevance score."""
    source: str        # Where this context came from
    content: str       # The actual text
    relevance: float   # 0-1, how relevant to current input
    token_estimate: int = 0
    priority: int = 5  # 1=highest, 10=lowest


class ContextManager:
    """
    Manages what goes into the LLM context window.

    The goal: maximize relevant information while staying within
    the token budget. Never dump everything -- always curate.
    """

    def __init__(self, budget: ContextBudget | None = None):
        self.budget = budget or ContextBudget()
        self._blocks: list[ContextBlock] = []

    def add_block(self, source: str, content: str, relevance: float = 0.5, priority: int = 5):
        """Add a context block."""
        token_estimate = len(content.split()) * 1.3  # Rough estimate
        self._blocks.append(ContextBlock(
            source=source, content=content,
            relevance=relevance, token_estimate=int(token_estimate),
            priority=priority,
        ))

    def assemble(self, max_tokens: int | None = None) -> str:
        """Assemble the final context string within budget."""
        budget = max_tokens or self.budget.total

        # Sort by priority (lower first) then relevance (higher first)
        sorted_blocks = sorted(self._blocks, key=lambda b: (b.priority, -b.relevance))

        result_parts = []
        used_tokens = 0

        for block in sorted_blocks:
            if used_tokens + block.token_estimate > budget:
                # Try to include a truncated version
                remaining = budget - used_tokens
                if remaining > 50:  # At least 50 tokens worth
                    words = block.content.split()
                    truncated = " ".join(words[:int(remaining / 1.3)])
                    result_parts.append(truncated)
                    used_tokens += len(truncated.split()) * 1.3
                break
            result_parts.append(block.content)
            used_tokens += block.token_estimate

        return "\n\n".join(result_parts)

    def clear(self):
        """Clear all context blocks."""
        self._blocks.clear()

    def estimate_usage(self) -> dict:
        """Estimate current context usage."""
        total = sum(b.token_estimate for b in self._blocks)
        return {
            "estimated_tokens": int(total),
            "budget": self.budget.total,
            "utilization_percent": round(total / self.budget.total * 100, 1),
            "blocks": len(self._blocks),
        }

    def compress_history(self, history: list, max_turns: int = 20) -> list:
        """Compress conversation history to fit within budget."""
        if len(history) <= max_turns:
            return history

        # Keep the most recent turns, summarize older ones
        recent = history[-max_turns:]
        older = history[:-max_turns]

        if older:
            # Create a summary of older turns
            summary_parts = []
            for msg in older:
                role = msg.get("role", "?")
                parts = msg.get("parts", [])
                for part in parts:
                    if "text" in part:
                        text = part["text"][:100]
                        summary_parts.append(f"[{role}] {text}")

            summary_text = "Earlier conversation summary:\n" + "\n".join(summary_parts[-20:])
            summary_msg = {"role": "user", "parts": [{"text": summary_text}]}
            return [summary_msg] + recent

        return recent