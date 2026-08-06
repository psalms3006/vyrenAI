"""
reflection/ -- Self-assessment and improvement.

After completing tasks, VYREN reflects on:
  - What went well
  - What could be improved
  - What was learned
  - What to do differently next time
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("vyren.reflection")
from platform_paths import get_reflections_path

REFLECT_DIR = get_reflections_path().parent
REFLECTIONS_FILE = get_reflections_path()


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
    outcome: str = "unknown"  # success | failure | partial
    metadata: dict = field(default_factory=dict)


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

    def search(self, query: str, limit: int = 10) -> list[Reflection]:
        query_lower = query.lower()
        results: list[Reflection] = []
        for r in self._reflections.values():
            text = f"{r.task} {r.what_went_well} {r.what_to_improve} {r.lessons_learned} {r.next_steps}".lower()
            if query_lower in text:
                results.append(r)
        results.sort(key=lambda r: r.created, reverse=True)
        return results[:limit]


class Reflector:
    """Self-assessment engine with outcome-aware adaptation."""

    def __init__(self, store: ReflectionStore):
        self.store = store

    def reflect(self, task: str, outcome: str, confidence_before: float = 0.5) -> Reflection:
        """Create a reflection on a completed task."""
        confidence_after = confidence_before
        if outcome == "success":
            confidence_after = min(1.0, confidence_before + 0.05)
        elif outcome == "failure":
            confidence_after = max(0.0, confidence_before - 0.1)

        reflection = Reflection(
            id=f"ref_{int(time.time())}",
            task=task,
            confidence_before=confidence_before,
            confidence_after=confidence_after,
            outcome=outcome,
            metadata={
                "confidence_delta": round(confidence_after - confidence_before, 4),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.store.add(reflection)
        return reflection

    def get_recent_insights(self, limit: int = 5) -> list[str]:
        refs = self.store.recent(limit)
        return [r.lessons_learned for r in refs if r.lessons_learned]

    def improvement_rate(self, window: int = 20) -> float:
        recent = self.store.recent(limit=window)
        if not recent:
            return 0.0
        deltas = [r.confidence_after - r.confidence_before for r in recent]
        return sum(deltas) / len(deltas)