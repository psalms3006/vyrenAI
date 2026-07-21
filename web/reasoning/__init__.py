"""
reasoning/ -- Multi-mode reasoning engine.

VYREN doesn't think the same way for every problem. The reasoning engine
selects the appropriate cognitive mode based on the task:
  - fast: simple questions, small tasks
  - deep: complex analysis, multi-step problems
  - creative: brainstorming, design, writing
  - research: fact-finding, verification
  - debug: error analysis, troubleshooting
  - architectural: system design, refactoring decisions
"""

import logging
import re

logger = logging.getLogger("vyren.reasoning")


class ReasoningMode:
    FAST = "fast"
    DEEP = "deep"
    CREATIVE = "creative"
    RESEARCH = "research"
    DEBUG = "debug"
    ARCHITECTURAL = "architectural"
    STRATEGIC = "strategic"
    MATH = "math"

    ALL = [FAST, DEEP, CREATIVE, RESEARCH, DEBUG, ARCHITECTURAL, STRATEGIC, MATH]

    HINTS = {
        "fast": "",
        "deep": "Think step-by-step. Consider multiple angles before concluding. Show your reasoning chain.",
        "creative": "Think broadly. Generate multiple alternatives before selecting the best one. Challenge assumptions.",
        "research": "Verify claims with evidence. Cross-reference sources. Distinguish facts from opinions. Cite specifics.",
        "debug": "Systematically eliminate possibilities. Check assumptions. Reproduce the error. Test hypotheses.",
        "architectural": "Consider trade-offs. Think about scalability, maintainability, and extensibility. Document decisions.",
        "strategic": "Think long-term. Consider second-order effects. Identify risks and mitigations. Prioritize ruthlessly.",
        "math": "Show every step of the calculation. Verify intermediate results. State the final answer clearly with units.",
    }


class ReasoningEngine:
    """
    Selects and applies the appropriate reasoning mode.
    """

    # Patterns that trigger specific reasoning modes
    MODE_PATTERNS = {
        ReasoningMode.DEBUG: [
            r"\b(error|bug|crash|exception|traceback|failed|broken|not working)\b",
            r"\b(debug|fix|troubleshoot|diagnose)\b",
            r"\b(why isn't|why does|why can't|what's wrong)\b",
        ],
        ReasoningMode.RESEARCH: [
            r"\b(research|find out|look up|investigate|verify|fact.?check)\b",
            r"\b(what is|who is|when did|how does.*work)\b",
            r"\b(compare|versus|vs\.?|difference between)\b",
        ],
        ReasoningMode.ARCHITECTURAL: [
            r"\b(design|architect|refactor|restructure|reorganize)\b",
            r"\b(system|framework|infrastructure|platform)\b",
            r"\b(scale|performance|optimize|bottleneck)\b",
        ],
        ReasoningMode.CREATIVE: [
            r"\b(idea|brainstorm|suggest|create|design|invent)\b",
            r"\b(how might|what if|imagine|alternativ)\b",
            r"\b(write|draft|compose|story|narrative)\b",
        ],
        ReasoningMode.STRATEGIC: [
            r"\b(strategy|plan|roadmap|goal|objective|milestone)\b",
            r"\b(priority|trade.?off|risk|mitigation)\b",
            r"\b(long.?term|future|vision|direction)\b",
        ],
        ReasoningMode.MATH: [
            r"\b(calculate|compute|solve|equation|formula)\b",
            r"\b(how many|how much|what.*percent|what.*ratio)\b",
            r"\b\d+\s*[\+\-\*\/\^]\s*\d+",  # Math expression
        ],
        ReasoningMode.DEEP: [
            r"\b(analyze|analysis|evaluate|assess|review)\b",
            r"\b(comprehensive|thorough|detailed|in.?depth)\b",
            r"\b(explain why|reason through|walk me through)\b",
            r"\b(implication|consequence|impact)\b",
        ],
    }

    def select_mode(self, user_input: str, context: dict | None = None) -> str:
        """Select the best reasoning mode for the given input."""
        text = user_input.lower()

        # Score each mode
        scores = {}
        for mode, patterns in self.MODE_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    score += 1
            scores[mode] = score

        # Pick the highest scoring mode
        best_mode = ReasoningMode.FAST
        best_score = 0
        for mode, score in scores.items():
            if score > best_score:
                best_score = score
                best_mode = mode

        # Only switch from fast if we have at least 2 pattern matches
        if best_score < 2:
            return ReasoningMode.FAST

        return best_mode

    def get_mode_hint(self, mode: str) -> str:
        """Get the system prompt hint for a reasoning mode."""
        return ReasoningMode.HINTS.get(mode, "")

    def get_available_modes(self) -> list[str]:
        """List all available reasoning modes."""
        return ReasoningMode.ALL