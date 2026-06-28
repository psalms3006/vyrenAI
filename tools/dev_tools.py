"""tools/dev_tools.py -- Development agent tools.

These give VYREN the ability to analyze, edit, and create code,
run scripts, and search through codebases. This is the dev agent —
VYREN acting as a senior software engineer on your behalf.

Destructive operations (edit_file, run_python) are consequential.
Read-only operations (search_files, analyze_code) are safe.
"""

import os
import subprocess
import glob as globmod

from tools import ToolDef, ToolRegistry


def register(registry: ToolRegistry):

    def search_files(pattern: str, directory: str = ".") -> str:
        """Search for files matching a glob pattern."""
        try:
            target = os.path.join(directory, pattern)
            matches = globmod.glob(target, recursive=True)
            if not matches:
                return f"No files found matching '{pattern}' in '{directory}'."
            # Limit output
            if len(matches) > 50:
                lines = [f"Found {len(matches)} files (showing first 50):"]
                matches = matches[:50]
            else:
                lines = [f"Found {len(matches)} files:"]
            for m in matches:
                if os.path.isfile(m):
                    size = os.path.getsize(m)
                    lines.append(f"  {m}  ({size}B)")
                else:
                    lines.append(f"  {m}/")
            return "\n".join(lines)
        except Exception as e:
            return f"Error searching: {type(e).__name__} — {e}"

    def edit_file(file_path: str, content: str, description: str = "") -> str:
        """Create or overwrite a file with the given content. REQUIRES CONFIRMATION."""
        try:
            resolved = os.path.realpath(file_path)
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
            lines = content.count("\n") + 1
            return f"EDIT_REQUESTED: {resolved} ({lines} lines)"
        except Exception as e:
            return f"Error writing file: {type(e).__name__} — {e}"

    def run_python(code: str, timeout: int = 30) -> str:
        """Execute Python code and return the output. REQUIRES CONFIRMATION."""
        return f"EXEC_REQUESTED: Python code ({len(code)} chars, timeout {timeout}s)"

    registry.register(ToolDef(
        name="search_files",
        description=(
            "Search for files matching a glob pattern (e.g. '**/*.py', "
            "'src/**/*.js'). Use this to find files in a project."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files (supports ** for recursive)",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to search in (default: current directory)",
                },
            },
            "required": ["pattern"],
        },
        handler=search_files,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="edit_file",
        description=(
            "Create a new file or overwrite an existing file with content. "
            "Use this to write code, create configs, or modify any text file. "
            "Always explain what the file does and why before creating it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path where the file should be created/overwritten",
                },
                "content": {
                    "type": "string",
                    "description": "The full content to write to the file",
                },
                "description": {
                    "type": "string",
                    "description": "Brief description of what this file does and why it's being created",
                },
            },
            "required": ["file_path", "content"],
        },
        handler=edit_file,
        safety_level="consequential",
    ))

    registry.register(ToolDef(
        name="run_python",
        description=(
            "Execute Python code and return stdout/stderr output. "
            "Use this for calculations, data processing, or any task "
            "that requires running code. The code runs in a subprocess "
            "with a timeout."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max execution time in seconds (default 30)",
                },
            },
            "required": ["code"],
        },
        handler=run_python,
        safety_level="consequential",
    ))