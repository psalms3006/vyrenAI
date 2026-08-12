"""generation/budget.py -- Persistent budget tracking for generation requests."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from platform_paths import get_vyren_dir

logger = logging.getLogger("vyren.generation.budget")


class GenerationBudgetStore:
    def __init__(self) -> None:
        self._path = get_vyren_dir() / "generation_budget.json"
        self._lock = threading.Lock()
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Budget store save failed: %s", exc)

    def record(self, provider: str, model: str, cost: float | None) -> None:
        if cost is None:
            return
        with self._lock:
            day = time.strftime("%Y-%m-%d")
            key = f"{provider}:{model}:{day}"
            entry = self._state.setdefault(key, {"provider": provider, "model": model, "day": day, "total_cost": 0.0, "count": 0})
            entry["total_cost"] = float(entry.get("total_cost", 0.0)) + float(cost)
            entry["count"] = int(entry.get("count", 0)) + 1
            self._save()

    def daily_usage(self, provider: str, model: str, day: str | None = None) -> float:
        if day is None:
            day = time.strftime("%Y-%m-%d")
        key = f"{provider}:{model}:{day}"
        with self._lock:
            return float(self._state.get(key, {}).get("total_cost", 0.0))
