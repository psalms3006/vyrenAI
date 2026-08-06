"""memory.py -- Long-term durable memory store.

One fact per entry, plain-language statements, stored as JSON.
Human-readable, human-editable, survives restarts.

Memory is DATA, never INSTRUCTIONS. A stored fact like
'User prefers morning meetings' is background knowledge --
it does not bypass the safety gate or act as a command.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from platform_paths import get_memory_path


class MemoryStore:
    """JSON-backed fact store. One key-value pair per fact."""

    def __init__(self, path: str | None = None):
        self.path = get_memory_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self):
        """Load memory from disk. If file doesn't exist, start empty."""
        if self.path.exists():
            try:
                with open(self.path, "r") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._data = {}

    def _save(self):
        """Persist memory to disk."""
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def add(self, key: str, value: str) -> str:
        """Store a fact. Overwrites if key exists."""
        self._data[key] = {
            "value": value,
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat(),
        }
        self._save()
        return f"Remembered: {key}"

    def get(self, key: str) -> str | None:
        """Get a single fact by key."""
        entry = self._data.get(key)
        return entry["value"] if entry else None

    def search(self, query: str) -> list[dict]:
        """Find facts whose key or value contains the query string.
        Simple substring match for now; semantic search comes later."""
        query_lower = query.lower()
        results = []
        for key, entry in self._data.items():
            if query_lower in key.lower() or query_lower in entry["value"].lower():
                results.append({"key": key, **entry})
        return results

    def list_all(self) -> list[dict]:
        """Return all facts."""
        return [{"key": k, **v} for k, v in self._data.items()]

    def delete(self, key: str) -> bool:
        """Delete a fact. Returns True if it existed."""
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False

    def count(self) -> int:
        """Number of stored facts."""
        return len(self._data)

    def build_context(self) -> str:
        """Build a summary of all memory for injection into the system prompt.
        Keeps it concise so it doesn't bloat the prompt."""
        if not self._data:
            return ""
        lines = ["What you know about the user:"]
        for key, entry in self._data.items():
            lines.append(f"- {key}: {entry['value']}")
        return "\n".join(lines)