"""
post_confirmation.py -- Shared post-confirmation execution.

Some tool calls return sentinel values like "DELETE_REQUESTED" to indicate
that the action requires user confirmation before proceeding. After the user
approves, this module executes the actual side effect.

This centralizes logic that was previously duplicated across:
  - brain/__init__.py
  - server.py
  - runtime/terminal.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any


def execute_post_confirmation(name: str, args: dict[str, Any], sentinel: str) -> str:
    """Execute a tool action after user confirmation.

    Args:
        name: Tool name that returned the sentinel.
        args: Tool arguments dict.
        sentinel: The original sentinel string returned by the tool.

    Returns:
        Result string describing what happened, or the original sentinel
        if this tool has no post-confirmation handler.
    """
    try:
        if name == "shutdown_system":
            return _handle_shutdown()
        if name == "restart_system":
            return _handle_restart()
        if name == "delete_file":
            return _handle_delete(args)
        if name == "edit_file":
            return _handle_edit(args)
        if name == "run_python":
            return _handle_run_python(args)
    except Exception as e:
        return f"Error executing {name}: {type(e).__name__} -- {e}"

    return sentinel


def _handle_shutdown() -> str:
    subprocess.run(["shutdown", "/s", "/t", "5"], check=False, shell=True)
    return "Shutdown initiated."


def _handle_restart() -> str:
    subprocess.run(["shutdown", "/r", "/t", "5"], check=False, shell=True)
    return "Restart initiated."


def _handle_delete(args: dict[str, Any]) -> str:
    path = args.get("file_path", "")
    if not path:
        return "Error: delete_file requires file_path"
    resolved = os.path.realpath(path)
    if not os.path.isfile(resolved):
        return f"File not found: {resolved}"
    os.remove(resolved)
    return f"Deleted: {resolved}"


def _handle_edit(args: dict[str, Any]) -> str:
    path = args.get("file_path", "")
    content = args.get("content", "")
    if not path:
        return "Error: edit_file requires file_path"
    resolved = os.path.realpath(path)
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as f:
        f.write(content)
    lines = content.count("\n") + 1
    return f"File written: {resolved} ({lines} lines)"


def _handle_run_python(args: dict[str, Any]) -> str:
    code = args.get("code", "")
    timeout = int(args.get("timeout", 30))
    if not code:
        return "Error: run_python requires code"
    python_exe = sys.executable or "python"
    result = subprocess.run(
        [python_exe, "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr
    return output if output.strip() else "(no output)"
