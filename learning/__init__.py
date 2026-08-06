"""
learning/ -- Continuous learning from interactions.

VYREN learns from: mistakes, corrections, successful plans, failed plans,
user habits, coding style, workflow preferences. Learning is transparent
and controllable -- the user can inspect, disable, or reset learning.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("vyren.learning")
from platform_paths import get_learning_dir

LEARN_DIR = get_learning_dir()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (norm_a * norm_b)


@dataclass
class Lesson:
    """A single learned lesson with retrieval metadata."""
    id: str
    category: str          # mistake, preference, pattern, correction, workflow
    content: str
    context: str = ""      # What was happening when this was learned
    confidence: float = 0.5
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reinforced: int = 0    # Times this lesson was reinforced
    applied: int = 0       # Times this lesson was applied
    applied_successfully: int = 0
    tags: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    decay_half_life_days: float = 60.0


class LessonStore:
    """Persistent lesson storage with confidence-aware retrieval."""

    def __init__(self):
        LEARN_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LEARN_DIR / "lessons.json"
        self._lessons: dict[str, Lesson] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for lid, ld in data.items():
                    fields = {k: v for k, v in ld.items() if k in Lesson.__dataclass_fields__}
                    self._lessons[lid] = Lesson(**fields)
            except Exception:
                self._lessons = {}

    def _save(self):
        data = {lid: l.__dict__ for lid, l in self._lessons.items()}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def add(self, lesson: Lesson) -> str:
        self._lessons[lesson.id] = lesson
        self._save()
        return lesson.id

    def reinforce(self, lesson_id: str):
        lesson = self._lessons.get(lesson_id)
        if lesson:
            lesson.reinforced += 1
            lesson.confidence = min(1.0, lesson.confidence + 0.05)
            lesson.updated = datetime.now(timezone.utc).isoformat()
            self._save()

    def record_application(self, lesson_id: str, success: bool):
        lesson = self._lessons.get(lesson_id)
        if lesson:
            lesson.applied += 1
            if success:
                lesson.applied_successfully += 1
                lesson.confidence = min(1.0, lesson.confidence + 0.03)
            lesson.updated = datetime.now(timezone.utc).isoformat()
            self._save()

    def _effective_confidence(self, lesson: Lesson) -> float:
        try:
            updated = datetime.fromisoformat(lesson.updated)
        except ValueError:
            return lesson.confidence
        age_days = max(0.0, (datetime.now(timezone.utc) - updated).total_seconds() / 86400.0)
        decay = 2 ** (-age_days / lesson.decay_half_life_days)
        return max(0.0, lesson.confidence * decay)

    def search(self, query: str, limit: int = 10) -> list[Lesson]:
        query_lower = query.lower()
        results: list[tuple[float, Lesson]] = []
        for l in self._lessons.values():
            if query_lower in l.content.lower() or query_lower in l.context.lower():
                score = self._effective_confidence(l) * (1 + l.reinforced * 0.1)
                results.append((score, l))
            elif any(query_lower in t.lower() for t in l.tags):
                score = self._effective_confidence(l) * (1 + l.reinforced * 0.1)
                results.append((score, l))
        results.sort(key=lambda x: -x[0])
        return [l for _, l in results[:limit]]

    def get_by_category(self, category: str) -> list[Lesson]:
        return [l for l in self._lessons.values() if l.category == category]

    def all(self) -> list[Lesson]:
        return list(self._lessons.values())

    def delete(self, lesson_id: str) -> bool:
        if lesson_id in self._lessons:
            del self._lessons[lesson_id]
            self._save()
            return True
        return False

    def count(self) -> int:
        return len(self._lessons)


class Learner:
    """
    Continuous learning engine.

    Learns from interactions and applies lessons to future behavior.
    """

    def __init__(self, store: LessonStore):
        self.store = store
        self._id_counter = 0

    def _next_id(self) -> str:
        self._id_counter += 1
        return f"lesson_{int(time.time())}_{self._id_counter}"

    def learn_from_correction(self, original: str, correction: str, context: str = ""):
        """Learn when the user corrects VYREN."""
        lesson = Lesson(
            id=self._next_id(),
            category="correction",
            content=f"When VYREN says/does '{original[:100]}', the correct approach is: {correction[:200]}",
            context=context,
            confidence=0.7,
            tags=["correction", "user_feedback"],
        )
        self.store.add(lesson)
        logger.info("Learned from correction: %s", correction[:60])

    def learn_preference(self, preference: str, context: str = ""):
        """Learn a user preference."""
        lesson = Lesson(
            id=self._next_id(),
            category="preference",
            content=preference,
            context=context,
            confidence=0.6,
            tags=["preference"],
        )
        self.store.add(lesson)
        logger.info("Learned preference: %s", preference[:60])

    def learn_mistake(self, mistake: str, correct_approach: str, context: str = ""):
        """Learn from a mistake VYREN made."""
        lesson = Lesson(
            id=self._next_id(),
            category="mistake",
            content=f"Mistake: {mistake[:150]}. Correct: {correct_approach[:200]}",
            context=context,
            confidence=0.8,
            tags=["mistake"],
        )
        self.store.add(lesson)
        logger.info("Learned from mistake: %s", mistake[:60])

    def learn_pattern(self, pattern: str, context: str = ""):
        """Learn a behavioral pattern observed in the user."""
        lesson = Lesson(
            id=self._next_id(),
            category="pattern",
            content=pattern,
            context=context,
            confidence=0.4,
            tags=["pattern", "observation"],
        )
        self.store.add(lesson)
        logger.info("Learned pattern: %s", pattern[:60])

    def get_relevant_lessons(self, query: str, limit: int = 5) -> list[str]:
        """Get lessons relevant to the current context."""
        lessons = self.store.search(query, limit=limit)
        return [l.content for l in lessons]

    def get_status(self) -> dict:
        categories = {}
        for l in self.store.all():
            categories[l.category] = categories.get(l.category, 0) + 1
        return {
            "total_lessons": self.store.count(),
            "categories": categories,
        }