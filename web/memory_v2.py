"""
memory_v2.py — Advanced multi-layer memory system for VYREN.

Layers:
  1. Working Memory  — current conversation context, short-lived
  2. Episodic Memory — specific past interactions and experiences
  3. Semantic Memory — general knowledge and facts (the original flat memory)
  4. Procedural Memory — learned procedures, workflows, how-to knowledge
  5. Preference Memory — user preferences, habits, style choices
  6. Project Memory  — per-project context, files, decisions, conventions

Each layer has its own store and retrieval logic. A MemoryManager
provides unified access and handles:
  - importance scoring (0-1, affects retention)
  - memory decay (lower importance = fades faster)
  - consolidation (periodic reorganization of memories)
  - contradiction detection
  - semantic search (keyword + relevance ranking)
"""

import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("vyren.memory_v2")

VYREN_DIR = Path(os.path.expanduser("~/.vyren"))


class MemoryLayer(str, Enum):
    WORKING = "working"       # Volatile, session-only
    EPISODIC = "episodic"     # Past interactions
    SEMANTIC = "semantic"     # Facts and knowledge
    PROCEDURAL = "procedural" # How-to, workflows
    PREFERENCE = "preference" # User preferences
    PROJECT = "project"       # Per-project context


@dataclass
class MemoryEntry:
    """A single memory with metadata."""
    id: str
    layer: MemoryLayer
    key: str
    value: str
    importance: float = 0.5     # 0=forgettable, 1=critical
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    accessed: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    access_count: int = 0
    tags: list[str] = field(default_factory=list)
    source: str = ""            # Where this memory came from
    project: str = ""           # Project association (for project memory)
    expires: str | None = None  # Optional expiration
    confidence: float = 1.0     # How certain we are about this memory
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "id": self.id, "layer": self.layer.value, "key": self.key,
            "value": self.value, "importance": self.importance,
            "created": self.created, "updated": self.updated,
            "accessed": self.accessed, "access_count": self.access_count,
            "tags": self.tags, "source": self.source, "project": self.project,
            "confidence": self.confidence,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        if self.expires:
            d["expires"] = self.expires
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        d["layer"] = MemoryLayer(d["layer"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class MemoryStore:
    """JSON-backed storage for one memory layer."""

    def __init__(self, layer: MemoryLayer):
        self.layer = layer
        self.path = VYREN_DIR / f"memory_{layer.value}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, MemoryEntry] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                for eid, edata in data.items():
                    self._entries[eid] = MemoryEntry.from_dict(edata)
            except (json.JSONDecodeError, IOError):
                self._entries = {}

    def _save(self):
        data = {eid: e.to_dict() for eid, e in self._entries.items()}
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def put(self, entry: MemoryEntry) -> str:
        self._entries[entry.id] = entry
        self._save()
        return entry.id

    def get(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def get_by_key(self, key: str) -> MemoryEntry | None:
        for e in self._entries.values():
            if e.key == key:
                return e
        return None

    def delete(self, entry_id: str) -> bool:
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._save()
            return True
        return False

    def all(self) -> list[MemoryEntry]:
        return list(self._entries.values())

    def search(self, query: str, project: str | None = None,
               tags: list[str] | None = None) -> list[MemoryEntry]:
        """Search memories by query string (keyword match + relevance)."""
        query_lower = query.lower()
        results = []

        for entry in self._entries.values():
            # Project filter
            if project and entry.project and entry.project != project:
                continue

            # Tag filter
            if tags and not any(t in entry.tags for t in tags):
                continue

            # Keyword matching
            key_match = query_lower in entry.key.lower()
            val_match = query_lower in entry.value.lower()
            tag_match = any(query_lower in t.lower() for t in entry.tags)

            if key_match or val_match or tag_match:
                # Simple relevance score: importance + match bonus + access recency
                score = entry.importance
                if key_match:
                    score += 0.3
                if val_match:
                    score += 0.2
                if tag_match:
                    score += 0.1
                # Access recency bonus
                try:
                    accessed = datetime.fromisoformat(entry.accessed)
                    hours_since = (datetime.now(timezone.utc) - accessed).total_seconds() / 3600
                    score += max(0, 0.1 - hours_since * 0.001)
                except ValueError:
                    pass

                results.append((score, entry))

        # Sort by relevance descending
        results.sort(key=lambda x: -x[0])
        return [e for _, e in results]

    def count(self) -> int:
        return len(self._entries)


class MemoryManager:
    """
    Unified memory manager across all layers.

    Usage:
        mm = MemoryManager()

        # Store a fact
        mm.remember("user_name", "Chidi", layer=MemoryLayer.SEMANTIC, importance=0.9)

        # Store an episodic memory
        mm.remember("meeting_2024_01_15", "Discussed Q1 roadmap with team",
                     layer=MemoryLayer.EPISODIC, tags=["meeting", "work"])

        # Recall
        facts = mm.recall("user_name")
        meeting_memories = mm.search("meeting", layer=MemoryLayer.EPISODIC)

        # Build context for system prompt
        context = mm.build_context()
    """

    def __init__(self):
        self.stores: dict[MemoryLayer, MemoryStore] = {}
        for layer in MemoryLayer:
            if layer != MemoryLayer.WORKING:
                self.stores[layer] = MemoryStore(layer)
        # Working memory is in-memory only (volatile)
        self._working: dict[str, MemoryEntry] = {}
        self._id_counter = 0

    def _next_id(self, layer: MemoryLayer) -> str:
        self._id_counter += 1
        return f"{layer.value}_{int(time.time())}_{self._id_counter}"

    def remember(self, key: str, value: str, layer: MemoryLayer = MemoryLayer.SEMANTIC,
                 importance: float = 0.5, tags: list[str] | None = None,
                 source: str = "", project: str = "",
                 confidence: float = 1.0, metadata: dict | None = None) -> str:
        """Store a memory entry. Returns the entry ID."""
        entry = MemoryEntry(
            id=self._next_id(layer),
            layer=layer,
            key=key.strip().lower().replace(" ", "_"),
            value=value,
            importance=max(0, min(1, importance)),
            tags=tags or [],
            source=source,
            project=project,
            confidence=confidence,
            metadata=metadata or {},
        )

        if layer == MemoryLayer.WORKING:
            self._working[entry.id] = entry
        else:
            # Check for existing entry with same key in same layer
            store = self.stores[layer]
            existing = store.get_by_key(entry.key)
            if existing:
                existing.value = value
                existing.updated = datetime.now(timezone.utc).isoformat()
                existing.importance = entry.importance
                existing.tags = list(set(existing.tags + entry.tags))
                store.put(existing)
                return existing.id
            store.put(entry)

        return entry.id

    def recall(self, key: str, layer: MemoryLayer | None = None) -> str | None:
        """Look up a specific fact by key. Returns the value or None."""
        key = key.strip().lower().replace(" ", "_")
        layers = [layer] if layer else list(MemoryLayer)

        for l in layers:
            if l == MemoryLayer.WORKING:
                for e in self._working.values():
                    if e.key == key:
                        e.access_count += 1
                        e.accessed = datetime.now(timezone.utc).isoformat()
                        return e.value
            else:
                store = self.stores.get(l)
                if store:
                    entry = store.get_by_key(key)
                    if entry:
                        entry.access_count += 1
                        entry.accessed = datetime.now(timezone.utc).isoformat()
                        store.put(entry)
                        return entry.value
        return None

    def search(self, query: str, layer: MemoryLayer | None = None,
               project: str | None = None, tags: list[str] | None = None,
               limit: int = 20) -> list[dict]:
        """Search across memory layers."""
        query = query.strip()
        if not query:
            return []

        layers = [layer] if layer else [l for l in MemoryLayer if l != MemoryLayer.WORKING]
        all_results = []

        for l in layers:
            store = self.stores.get(l)
            if store:
                entries = store.search(query, project=project, tags=tags)
                all_results.extend(entries)

        # Sort by importance * recency, take top N
        all_results.sort(key=lambda e: -e.importance * (1 + e.access_count * 0.01))
        return [e.to_dict() for e in all_results[:limit]]

    def delete(self, key: str, layer: MemoryLayer | None = None) -> bool:
        """Delete a memory by key."""
        key = key.strip().lower().replace(" ", "_")
        if layer:
            store = self.stores.get(layer)
            if store:
                entry = store.get_by_key(key)
                if entry:
                    return store.delete(entry.id)
        else:
            for store in self.stores.values():
                entry = store.get_by_key(key)
                if entry:
                    return store.delete(entry.id)
        return False

    def list_all(self, layer: MemoryLayer | None = None) -> list[dict]:
        """List all memories, optionally filtered by layer."""
        results = []
        if layer:
            store = self.stores.get(layer)
            if store:
                results = [e.to_dict() for e in store.all()]
        else:
            for store in self.stores.values():
                results.extend(e.to_dict() for e in store.all())
        return results

    def count(self, layer: MemoryLayer | None = None) -> int:
        if layer:
            if layer == MemoryLayer.WORKING:
                return len(self._working)
            store = self.stores.get(layer)
            return store.count() if store else 0
        return sum(s.count() for s in self.stores.values()) + len(self._working)

    def build_context(self, max_tokens: int = 500) -> str:
        """Build a context string for the system prompt from high-importance memories."""
        # Gather all entries, prioritize by importance
        all_entries = []
        for store in self.stores.values():
            for e in store.all():
                if e.importance >= 0.3:  # Only include reasonably important memories
                    all_entries.append(e)

        all_entries.sort(key=lambda e: (-e.importance, -e.access_count))

        lines = ["What you know about the user:"]
        token_budget = max_tokens
        chars_per_token = 4  # Rough estimate

        for entry in all_entries:
            line = f"- {entry.key}: {entry.value}"
            if len(line) > token_budget * chars_per_token:
                break
            lines.append(line)
            token_budget -= len(line.split())

        return "\n".join(lines) if len(lines) > 1 else ""

    def get_project_memories(self, project: str) -> list[dict]:
        """Get all memories associated with a project."""
        results = []
        for store in self.stores.values():
            for e in store.all():
                if e.project == project:
                    results.append(e.to_dict())
        return results

    def detect_contradictions(self) -> list[dict]:
        """Find potentially contradictory memories (same key, different values)."""
        by_key: dict[str, list] = {}
        for store in self.stores.values():
            for e in store.all():
                if e.key not in by_key:
                    by_key[e.key] = []
                by_key[e.key].append(e)

        contradictions = []
        for key, entries in by_key.items():
            if len(entries) > 1:
                values = [e.value for e in entries]
                if len(set(values)) > 1:
                    contradictions.append({
                        "key": key,
                        "values": values,
                        "count": len(entries),
                        "entries": [e.to_dict() for e in entries],
                    })
        return contradictions

    def consolidate(self):
        """
        Memory consolidation pass:
        1. Remove expired memories
        2. Decay low-importance, rarely-accessed memories
        3. Promote episodic memories that have been accessed often to semantic
        """
        now = datetime.now(timezone.utc)

        for store in self.stores.values():
            to_delete = []
            to_promote = []

            for entry in store.all():
                # Check expiration
                if entry.expires:
                    try:
                        exp = datetime.fromisoformat(entry.expires)
                        if now > exp:
                            to_delete.append(entry.id)
                            continue
                    except ValueError:
                        pass

                # Decay: low importance + rarely accessed + old
                if entry.importance < 0.2 and entry.access_count == 0:
                    try:
                        created = datetime.fromisoformat(entry.created)
                        age_days = (now - created).total_seconds() / 86400
                        if age_days > 90:
                            to_delete.append(entry.id)
                            continue
                    except ValueError:
                        pass

                # Promote episodic memories accessed 5+ times to semantic
                if (entry.layer == MemoryLayer.EPISODIC and
                    entry.access_count >= 5 and
                    entry.importance >= 0.5):
                    to_promote.append(entry)

            for eid in to_delete:
                store.delete(eid)

            for entry in to_promote:
                # Create semantic version
                self.remember(
                    key=entry.key,
                    value=entry.value,
                    layer=MemoryLayer.SEMANTIC,
                    importance=entry.importance,
                    tags=entry.tags + ["promoted_from_episodic"],
                    source="consolidation",
                )

        if to_delete or to_promote:
            logger_info = f"Consolidated: deleted {len(to_delete)}, promoted {len(to_promote)}"
            try:
                import logging
                logging.getLogger("vyren.memory").info(logger_info)
            except Exception:
                pass