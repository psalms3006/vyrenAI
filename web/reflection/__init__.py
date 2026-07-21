"""
reflection/ -- Self-assessment and improvement.

After completing tasks, VYREN reflects on:
  - What went well
  - What could be improved
  - What was learned
  - What to do differently next time
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("vyren.reflection")

REFLECT_DIR = Path(os.path.expanduser("~/.vyren/reflections"))


@dataclass
class Reflection:
    id: str
    task: str
    what_went_well: str = ""
    what_to_improve: str = ""
    lessons_learned: str = ""
    next_steps: str = ""
    confidence_before: float = 0.5
    confidence_after: float = 0.5
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ReflectionStore:
    """Persistent reflection storage."""

    def __init__(self):
        REFLECT_DIR.mkdir(parents=True, exist_ok=True)
        self.path = REFLECT_DIR / "reflections.json"
        self._reflections: dict[str, Reflection] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for rid, rd in data.items():
                    self._reflections[rid] = Reflection(**{k: v for k, v in rd.items() if k in Reflection.__dataclass_fields__})
            except Exception:
                pass

    def _save(self):
        data = {rid: r.__dict__ for rid, r in self._reflections.items()}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def add(self, reflection: Reflection) -> str:
        self._reflections[reflection.id] = reflection
        self._save()
        return reflection.id

    def recent(self, limit: int = 10) -> list[Reflection]:
        refs = list(self._reflections.values())
        refs.sort(key=lambda r: r.created, reverse=True)
        return refs[:limit]

    def all(self) -> list[Reflection]:
        return list(self._reflections.values())


class Reflector:
    """Self-assessment engine."""

    def __init__(self, store: ReflectionStore):
        self.store = store

    def reflect(self, task: str, outcome: str, confidence_before: float = 0.5) -> Reflection:
        """Create a reflection on a completed task."""
        reflection = Reflection(
            id=f"ref_{int(time.time())}",
            task=task,
            confidence_before=confidence_before,
            confidence_after=min(1.0, confidence_before + 0.1),  # Assume slight improvement
        )
        self.store.add(reflection)
        return reflection

    def get_recent_insights(self, limit: int = 5) -> list[str]:
        """Get recent lessons learned."""
        refs = self.store.recent(limit)
        return [r.lessons_learned for r in refs if r.lessons_learned]