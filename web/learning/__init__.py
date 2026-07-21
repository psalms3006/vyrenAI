"""
learning/ -- Continuous learning from interactions.

VYREN learns from: mistakes, corrections, successful plans, failed plans,
user habits, coding style, workflow preferences. Learning is transparent
and controllable -- the user can inspect, disable, or reset learning.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("vyren.learning")

LEARN_DIR = Path(os.path.expanduser("~/.vyren/learning"))


@dataclass
class Lesson:
    """A single learned lesson."""
    id: str
    category: str          # mistake, preference, pattern, correction, workflow
    content: str
    context: str = ""      # What was happening when this was learned
    confidence: float = 0.5
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reinforced: int = 0    # Times this lesson was reinforced
    applied: int = 0       # Times this lesson was applied
    tags: list[str] = field(default_factory=list)


class LessonStore:
    """Persistent lesson storage."""

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
                    self._lessons[lid] = Lesson(**{k: v for k, v in ld.items() if k in Lesson.__dataclass_fields__})
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
            self._save()

    def search(self, query: str, limit: int = 10) -> list[Lesson]:
        query_lower = query.lower()
        results = []
        for l in self._lessons.values():
            if query_lower in l.content.lower() or query_lower in l.context.lower():
                results.append(l)
            elif any(query_lower in t.lower() for t in l.tags):
                results.append(l)
        results.sort(key=lambda x: -x.confidence * (1 + x.reinforced * 0.1))
        return results[:limit]

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
        logger.info(f"Learned from correction: {correction[:60]}")

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
        logger.info(f"Learned preference: {preference[:60]}")

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
        logger.info(f"Learned from mistake: {mistake[:60]}")

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
        logger.info(f"Learned pattern: {pattern[:60]}")

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