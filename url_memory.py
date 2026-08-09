"""url_memory.py -- URL resource store and graph hooks."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("vyren.url")

try:
    from url_understanding import (
        UrlExtractor,
        UrlMemory,
        classify_url,
        detect_urls,
        ExtractionQuality,
        ResourceStatus,
        UrlResource,
    )
except Exception:  # pragma: no cover - optional absent module
    UrlExtractor = None  # type: ignore[misc,assignment]
    UrlMemory = None  # type: ignore[misc,assignment]
    UrlResource = None  # type: ignore[misc,assignment]


class UrlStore:
    """Shared URL store with optional persistence."""

    def __init__(self, persist: bool = False, path: Path | None = None) -> None:
        if UrlMemory is None:
            self._memory = None
        else:
            self._memory = UrlMemory(persist=persist, storage_path=path)

    def put(self, resource: Any) -> None:
        if self._memory is None or resource is None:
            return
        try:
            self._memory.put(resource)
        except Exception as exc:
            logger.debug("url store put failed: %s", exc)

    def get(self, url: str) -> Any | None:
        if not self._memory:
            return None
        try:
            return self._memory.get(url)
        except Exception:
            return None

    def recent(self, limit: int = 20) -> list[Any]:
        if not self._memory:
            return []
        try:
            return self._memory.recent(limit=limit)
        except Exception:
            return []

    def all(self) -> list[Any]:
        if not self._memory:
            return []
        try:
            return self._memory.all()
        except Exception:
            return []
