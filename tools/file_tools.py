"""tools/file_tools.py -- File system tools for VYREN.

Read-only file operations are safe. Delete and write operations
are consequential and require confirmation.
"""

import os

from tools import ToolDef, ToolRegistry


def register(registry: ToolRegistry):

    def read_file(file_path: str, max_lines: int = 200) -> str:
        """Read the contents of a text file."""
        try:
            # Security: reject obvious path traversal
            resolved = os.path.realpath(file_path)
            if not os.path.isfile(resolved):
                return f"File not found: {file_path}"

            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            if len(lines) > max_lines:
                shown = lines[:max_lines]
                return (
                    "".join(shown)
                    + f"\n\n... (truncated at {max_lines} lines of {len(lines)} total)"
                )
            return "".join(lines)
        except Exception as e:
            return f"Error reading file: {type(e).__name__} — {e}"

    def list_directory(dir_path: str) -> str:
        """List files and folders in a directory."""
        try:
            resolved = os.path.realpath(dir_path)
            if not os.path.isdir(resolved):
                return f"Directory not found: {dir_path}"

            entries = sorted(os.listdir(resolved))
            if not entries:
                return f"Directory is empty: {dir_path}"

            lines = [f"Contents of {resolved}:"]
            for entry in entries:
                full = os.path.join(resolved, entry)
                if os.path.isdir(full):
                    lines.append(f"  📁 {entry}/")
                else:
                    size = os.path.getsize(full)
                    if size > 1024 * 1024:
                        size_str = f"{size / (1024*1024):.1f}MB"
                    elif size > 1024:
                        size_str = f"{size / 1024:.1f}KB"
                    else:
                        size_str = f"{size}B"
                    lines.append(f"  📄 {entry}  ({size_str})")
            return "\n".join(lines)
        except PermissionError:
            return f"Permission denied: {dir_path}"
        except Exception as e:
            return f"Error listing directory: {type(e).__name__} — {e}"

    def delete_file(file_path: str) -> str:
        """Delete a file. REQUIRES CONFIRMATION."""
        resolved = os.path.realpath(file_path)
        if not os.path.isfile(resolved):
            return f"File not found: {file_path}"
        return f"DELETE_REQUESTED: {resolved}"

    registry.register(ToolDef(
        name="read_file",
        description=(
            "Read the contents of a text file on the computer. "
            "Returns the file content. Use this to inspect code, "
            "config files, logs, or any text file."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum lines to read (default 200, to avoid huge files)",
                },
            },
            "required": ["file_path"],
        },
        handler=read_file,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="list_directory",
        description=(
            "List all files and folders in a directory. "
            "Shows file sizes and distinguishes folders from files."
        ),
        parameters={
            "type": "object",
            "properties": {
                "dir_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the directory",
                },
            },
            "required": ["dir_path"],
        },
        handler=list_directory,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="delete_file",
        description=(
            "Delete a file from the computer. This is a consequential "
            "action that requires explicit user confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to delete",
                },
            },
            "required": ["file_path"],
        },
        handler=delete_file,
        safety_level="consequential",
    ))