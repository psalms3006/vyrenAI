"""audit.py -- Structured audit logging.

Every action VYREN takes is logged here: tool calls, confirmations,
errors, model turns, and cost tracking. The log is plain text,
human-readable, and append-only.

This is how you find out what happened when something surprises you.
"""

import os
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: str | None = None):
        self.path = Path(path or os.path.expanduser("~/.vyren/audit.log"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._total_cost_usd: float = 0.0

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _write(self, level: str, message: str):
        line = f"[{self._timestamp()}] [{level}] {message}\n"
        with open(self.path, "a", encoding="utf-8", errors="replace") as f:
            f.write(line)

    def info(self, message: str):
        self._write("INFO", message)

    def tool_call(self, tool_name: str, args: dict, result_summary: str):
        self._write("TOOL", f"{tool_name} | args={args} | result={result_summary}")

    def tool_error(self, tool_name: str, error: str):
        self._write("ERROR", f"TOOL {tool_name} failed: {error}")

    def confirmation(self, tool_name: str, args: dict, approved: bool):
        status = "APPROVED" if approved else "DECLINED"
        self._write("CONFIRM", f"{tool_name} | args={args} | {status}")

    def security(self, message: str):
        self._write("SECURITY", message)

    def cost(self, model: str, input_tokens: int, output_tokens: int, cost_usd: float):
        self._total_cost_usd += cost_usd
        self._write(
            "COST",
            f"model={model} in={input_tokens} out={output_tokens} "
            f"cost=${cost_usd:.6f} total=${self._total_cost_usd:.6f}",
        )

    def model_turn(self, role: str, text_preview: str):
        preview = text_preview[:100].replace("\n", " ")
        self._write("TURN", f"{role}: {preview}")
