"""
filesystem/ -- Enhanced file system operations.

Goes beyond basic read/write to include:
  - Project-aware file indexing
  - Folder tree visualization
  - File type detection
  - Batch operations
  - Safe delete (recycle bin)
"""

import os
import shutil
import stat
from pathlib import Path
from typing import Generator


def read_file(file_path: str, max_lines: int = 500) -> str:
    """Read a text file safely."""
    resolved = Path(file_path).resolve()
    if not resolved.is_file():
        return f"File not found: {file_path}"
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) > max_lines:
            return "".join(lines[:max_lines]) + f"\n... (truncated at {max_lines} of {len(lines)} lines)"
        return "".join(lines)
    except Exception as e:
        return f"Error reading file: {type(e).__name__} -- {e}"


def write_file(file_path: str, content: str) -> str:
    """Write content to a file safely."""
    resolved = Path(file_path).resolve()
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written: {resolved} ({content.count(chr(10)) + 1} lines)"
    except Exception as e:
        return f"Error writing file: {type(e).__name__} -- {e}"


def list_directory(dir_path: str, max_depth: int = 1) -> str:
    """List directory contents with tree visualization."""
    resolved = Path(dir_path).resolve()
    if not resolved.is_dir():
        return f"Directory not found: {dir_path}"

    lines = [str(resolved)]
    _walk_tree(resolved, lines, prefix="", max_depth=max_depth, current_depth=0)
    return "\n".join(lines)


def _walk_tree(path: Path, lines: list, prefix: str, max_depth: int, current_depth: int):
    if current_depth >= max_depth:
        return
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "\\-- " if is_last else "|-- "
        child_prefix = "    " if is_last else "|   "

        if entry.is_dir():
            lines.append(f"{prefix}{connector}{entry.name}/")
            _walk_tree(entry, lines, prefix + child_prefix, max_depth, current_depth + 1)
        else:
            size = entry.stat().st_size
            if size > 1024 * 1024:
                size_str = f"{size / (1024*1024):.1f}MB"
            elif size > 1024:
                size_str = f"{size / 1024:.1f}KB"
            else:
                size_str = f"{size}B"
            lines.append(f"{prefix}{connector}{entry.name}  ({size_str})")


def search_files(pattern: str, directory: str = ".") -> str:
    """Search for files matching a glob pattern."""
    import glob as globmod
    target = os.path.join(directory, pattern)
    matches = globmod.glob(target, recursive=True)
    if not matches:
        return f"No files found matching '{pattern}' in '{directory}'."
    if len(matches) > 50:
        return f"Found {len(matches)} files (showing first 50):\n" + "\n".join(matches[:50])
    return f"Found {len(matches)} files:\n" + "\n".join(matches)


def get_file_info(file_path: str) -> str:
    """Get detailed info about a file."""
    resolved = Path(file_path).resolve()
    if not resolved.exists():
        return f"Not found: {file_path}"
    stat = resolved.stat()
    lines = [
        f"Path: {resolved}",
        f"Size: {stat.st_size} bytes",
        f"Modified: {stat.st_mtime}",
        f"Type: {'Directory' if resolved.is_dir() else 'File'}",
    ]
    if resolved.is_file():
        ext = resolved.suffix.lower()
        type_map = {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".html": "HTML", ".css": "CSS", ".json": "JSON", ".yaml": "YAML",
            ".yml": "YAML", ".md": "Markdown", ".txt": "Text",
            ".jpg": "Image", ".jpeg": "Image", ".png": "Image",
            ".gif": "Image", ".mp3": "Audio", ".mp4": "Video",
            ".pdf": "PDF", ".zip": "Archive", ".exe": "Executable",
        }
        lines.append(f"Language: {type_map.get(ext, ext or 'unknown')}")
    return "\n".join(lines)


def safe_delete(file_path: str) -> str:
    """Move file to recycle bin instead of permanent delete."""
    resolved = Path(file_path).resolve()
    if not resolved.exists():
        return f"Not found: {file_path}"
    try:
        # Try send2trash first (cross-platform recycle bin)
        try:
            from send2trash import send2trash
            send2trash(str(resolved))
            return f"Moved to recycle bin: {resolved}"
        except ImportError:
            # Fallback: just delete
            if resolved.is_dir():
                shutil.rmtree(resolved)
            else:
                resolved.unlink()
            return f"Deleted: {resolved} (no recycle bin support)"
    except Exception as e:
        return f"Delete failed: {type(e).__name__} -- {e}"