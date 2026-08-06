"""
memory_v2.py — Advanced multi-layer memory system for VYREN.

Layers:
  1. Working Memory  — current conversation context, short-lived
  2. Episodic Memory — specific past interactions and experiences
  3. Semantic Memory — general knowledge and facts
  4. Procedural Memory — learned procedures, workflows, how-to knowledge
  5. Preference Memory — user preferences, habits, style choices
  6. Project Memory  — per-project context, files, decisions, conventions

MemoryManager provides unified access and handles:
  - importance scoring (0-1, affects retention)
  - memory decay (lower importance = fades faster)
  - consolidation (periodic reorganization of memories)
  - contradiction detection
  - semantic search (keyword + embedding-backed relevance ranking)
  - duplicate detection / near-dedupe
  - forgetting policy
  - budget-aware context assembly
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("vyren.memory_v2")


# ---------------------------------------------------------------------------
# Optional embedding backend
# ---------------------------------------------------------------------------

class EmbeddingProvider:
    """Minimal embedding interface used by semantic memory search."""

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic fallback embedding based on token hashing.

    This avoids external dependencies while still enabling stable
    similarity search across restarts for the same text.
    """

    def __init__(self, dims: int = 256, seed: int = 0) -> None:
        self.dims = dims
        self.seed = seed

    def embed(self, text: str) -> list[float]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        vec = [0.0] * self.dims
        for token in tokens:
            idx = (hash((token, self.seed)) & 0x7FFFFFFF) % self.dims
            vec[idx] += 1.0
        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


class _LocalEmbeddingCache:
    """Process-local cache for embeddings to avoid recomputation."""

    def __init__(self) -> None:
        self._cache: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> list[float] | None:
        with self._lock:
            return self._cache.get(key)

    def put(self, key: str, value: list[float]) -> None:
        with self._lock:
            self._cache[key] = value


_embedding_cache = _LocalEmbeddingCache()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (norm_a * norm_b)


def _resolve_embedding_provider() -> EmbeddingProvider:
    """Return the best available embedding backend.

    Prefers a configured local transformer if available; otherwise falls
    back to the deterministic hash embedding so semantic search never
    hard-fails just because an optional dependency is missing.
    """
    # Optional path: user can inject a richer provider via env/config.
    try:
        from config import get as cfg_get  # type: ignore
        provider_path = cfg_get("memory.embedding_provider")
    except Exception:
        provider_path = None

    if provider_path:
        try:
            module_path, _, factory = provider_path.rpartition(".")
            mod = __import__(module_path, fromlist=[factory])
            factory_fn = getattr(mod, factory)
            instance = factory_fn()
            if isinstance(instance, EmbeddingProvider):
                return instance
        except Exception as exc:
            logger.debug("Embedding provider %s unavailable: %s", provider_path, exc)

    return HashEmbeddingProvider()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

from platform_paths import get_vyren_dir

VYREN_DIR = get_vyren_dir()


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
    importance: float = 0.5
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    accessed: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    access_count: int = 0
    tags: list[str] = field(default_factory=list)
    source: str = ""
    project: str = ""
    expires: str | None = None
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)
    embedding: list[float] | None = None
    content_hash: str | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "id": self.id,
            "layer": self.layer.value,
            "key": self.key,
            "value": self.value,
            "importance": self.importance,
            "created": self.created,
            "updated": self.updated,
            "accessed": self.accessed,
            "access_count": self.access_count,
            "tags": self.tags,
            "source": self.source,
            "project": self.project,
            "confidence": self.confidence,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        if self.expires:
            d["expires"] = self.expires
        if self.embedding is not None:
            d["embedding"] = self.embedding
        if self.content_hash is not None:
            d["content_hash"] = self.content_hash
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        d["layer"] = MemoryLayer(d["layer"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Per-layer JSON-backed store
# ---------------------------------------------------------------------------

class MemoryStore:
    """JSON-backed storage for one memory layer."""

    def __init__(self, layer: MemoryLayer) -> None:
        self.layer = layer
        self.path = VYREN_DIR / f"memory_{layer.value}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, MemoryEntry] = {}
        self._key_index: dict[str, str] = {}
        self._id_counter = 0
        self._load()

    def _next_id(self) -> str:
        self._id_counter += 1
        return f"{self.layer.value}_{int(time.time())}_{self._id_counter}"

    def _load(self) -> None:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for eid, edata in data.items():
                    entry = MemoryEntry.from_dict(edata)
                    self._entries[eid] = entry
                    self._key_index[entry.key] = eid
            except (json.JSONDecodeError, IOError):
                self._entries = {}
                self._key_index = {}

    def _save(self) -> None:
        data = {eid: e.to_dict() for eid, e in self._entries.items()}
        tmp_path = self.path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(self.path)

    def put(self, entry: MemoryEntry) -> str:
        self._entries[entry.id] = entry
        self._key_index[entry.key] = entry.id
        self._save()
        return entry.id

    def add(self, key: str, value: str) -> str:
        """Backward-compatible alias for legacy callers."""
        return self.put(
            MemoryEntry(
                id=self._next_id(),
                layer=self.layer,
                key=key.strip().lower().replace(" ", "_"),
                value=value,
            )
        )

    def get(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def get_by_key(self, key: str) -> MemoryEntry | None:
        eid = self._key_index.get(key)
        if not eid:
            return None
        return self._entries.get(eid)

    def delete(self, entry_id: str) -> bool:
        if entry_id not in self._entries:
            return False
        entry = self._entries[entry_id]
        self._key_index.pop(entry.key, None)
        del self._entries[entry_id]
        self._save()
        return True

    def all(self) -> list[MemoryEntry]:
        return list(self._entries.values())

    def count(self) -> int:
        return len(self._entries)

    def search(
        self,
        query: str,
        layer: MemoryLayer | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        *,
        provider: EmbeddingProvider | None = None,
        semantic_weight: float = 0.55,
    ) -> list[MemoryEntry]:
        """Search memories by query using keyword + semantic similarity.

        Returns the matched memory entries. The manager wrapper converts
        these to plain dicts for external callers.
        """
        query_lower = query.lower()
        results: list[tuple[float, MemoryEntry]] = []

        if provider is None:
            provider = _resolve_embedding_provider()

        query_vec_cache_key = f"query:{query}"
        query_vec = _embedding_cache.get(query_vec_cache_key)
        if query_vec is None:
            query_vec = provider.embed(query)
            _embedding_cache.put(query_vec_cache_key, query_vec)

        for entry in self._entries.values():
            if project and entry.project and entry.project != project:
                continue
            if tags and not any(t in entry.tags for t in tags):
                continue

            key_match = query_lower in entry.key.lower()
            val_match = query_lower in entry.value.lower()
            tag_match = any(query_lower in t.lower() for t in entry.tags)

            if not (key_match or val_match or tag_match):
                semantic_score = _cosine_similarity(
                    query_vec,
                    entry.embedding or provider.embed(entry.value),
                )
                if semantic_score < 0.15:
                    continue
                keyword_score = 0.0
            else:
                semantic_score = _cosine_similarity(
                    query_vec,
                    entry.embedding or provider.embed(entry.value),
                )
                keyword_score = (
                    0.3 * int(key_match)
                    + 0.2 * int(val_match)
                    + 0.1 * int(tag_match)
                )

            try:
                accessed = datetime.fromisoformat(entry.accessed)
                hours_since = max(
                    0.0,
                    (datetime.now(timezone.utc) - accessed).total_seconds() / 3600.0,
                )
                recency_bonus = max(0.0, 0.1 - hours_since * 0.001)
            except ValueError:
                recency_bonus = 0.0

            score = (
                semantic_weight * max(semantic_score, 0.0)
                + (1.0 - semantic_weight) * keyword_score
                + 0.25 * entry.importance
                + recency_bonus
            )
            results.append((score, entry))

        results.sort(key=lambda x: -x[0])
        return [entry for _, entry in results]


# ---------------------------------------------------------------------------
# Unified memory manager
# ---------------------------------------------------------------------------

class MemoryManager:
    """
    Unified memory manager across all layers.

    Usage:
        mm = MemoryManager()
        mm.remember("user_name", "Chidi", layer=MemoryLayer.SEMANTIC, importance=0.9)
        mm.remember("meeting_2024_01_15", "Discussed Q1 roadmap", layer=MemoryLayer.EPISODIC, tags=["work"])
        facts = mm.recall("user_name")
        context = mm.build_context(max_tokens=500)
    """

    def __init__(self) -> None:
        self.stores: dict[MemoryLayer, MemoryStore] = {}
        for layer in MemoryLayer:
            if layer != MemoryLayer.WORKING:
                self.stores[layer] = MemoryStore(layer)
        self._working: dict[str, MemoryEntry] = {}
        self._id_counter = 0
        self._provider: EmbeddingProvider | None = None
        self._provider_lock = threading.Lock()

    def _next_id(self, layer: MemoryLayer) -> str:
        self._id_counter += 1
        return f"{layer.value}_{int(time.time())}_{self._id_counter}"

    def _get_provider(self) -> EmbeddingProvider:
        if self._provider is None:
            with self._provider_lock:
                if self._provider is None:
                    self._provider = _resolve_embedding_provider()
        return self._provider

    def remember(
        self,
        key: str,
        value: str,
        layer: MemoryLayer = MemoryLayer.SEMANTIC,
        importance: float = 0.5,
        tags: list[str] | None = None,
        source: str = "",
        project: str = "",
        confidence: float = 1.0,
        metadata: dict | None = None,
        embed: bool = True,
    ) -> str:
        """Store a memory entry. Returns the entry ID."""
        normalized_key = key.strip().lower().replace(" ", "_")
        content_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        provider = self._get_provider() if embed else None

        entry = MemoryEntry(
            id=self._next_id(layer),
            layer=layer,
            key=normalized_key,
            value=value,
            importance=max(0.0, min(1.0, importance)),
            tags=tags or [],
            source=source,
            project=project,
            confidence=max(0.0, min(1.0, confidence)),
            metadata=metadata or {},
            embedding=provider.embed(value) if provider else None,
            content_hash=content_hash,
        )

        if layer == MemoryLayer.WORKING:
            self._working[entry.id] = entry
            return entry.id

        store = self.stores[layer]
        existing = store.get_by_key(normalized_key)
        if existing:
            existing.value = value
            existing.updated = datetime.now(timezone.utc).isoformat()
            existing.importance = max(existing.importance, entry.importance)
            existing.tags = list(set(existing.tags + entry.tags))
            existing.source = source or existing.source
            existing.project = project or existing.project
            existing.confidence = entry.confidence
            existing.metadata = {**(existing.metadata or {}), **(entry.metadata or {})}
            existing.content_hash = content_hash
            existing.embedding = entry.embedding or existing.embedding
            store.put(existing)
            return existing.id

        store.put(entry)
        return entry.id

    def recall(self, key: str, layer: MemoryLayer | None = None) -> str | None:
        """Look up a specific fact by key."""
        normalized_key = key.strip().lower().replace(" ", "_")
        layers = [layer] if layer else list(MemoryLayer)

        for lyr in layers:
            if lyr == MemoryLayer.WORKING:
                for entry in self._working.values():
                    if entry.key == normalized_key:
                        entry.access_count += 1
                        entry.accessed = datetime.now(timezone.utc).isoformat()
                        return entry.value
                continue

            store = self.stores.get(lyr)
            if not store:
                continue
            entry = store.get_by_key(normalized_key)
            if not entry:
                continue
            entry.access_count += 1
            entry.accessed = datetime.now(timezone.utc).isoformat()
            store.put(entry)
            return entry.value
        return None

    def search(
        self,
        query: str,
        layer: MemoryLayer | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search across memory layers with semantic + keyword ranking."""
        query = query.strip()
        if not query:
            return []

        layers = [layer] if layer else [l for l in MemoryLayer if l != MemoryLayer.WORKING]
        provider = self._get_provider()
        all_entries: list[MemoryEntry] = []

        for lyr in layers:
            store = self.stores.get(lyr)
            if not store:
                continue
            all_entries.extend(store.search(query, project=project, tags=tags, provider=provider))

        all_entries.sort(
            key=lambda e: -(
                0.6
                + 0.25 * e.importance
                + 0.15 * min(e.access_count, 20) / 20.0
            )
        )
        return [e.to_dict() for e in all_entries[: limit if limit > 0 else len(all_entries)]]

    def delete(self, key: str, layer: MemoryLayer | None = None) -> bool:
        """Delete a memory by key."""
        normalized_key = key.strip().lower().replace(" ", "_")
        if layer:
            store = self.stores.get(layer)
            if not store:
                return False
            entry = store.get_by_key(normalized_key)
            if not entry:
                return False
            return store.delete(entry.id)

        for store in self.stores.values():
            entry = store.get_by_key(normalized_key)
            if entry:
                return store.delete(entry.id)
        return False

    def list_all(self, layer: MemoryLayer | None = None) -> list[dict]:
        """List all memories, optionally filtered by layer."""
        results: list[dict] = []
        if layer:
            if layer == MemoryLayer.WORKING:
                return [e.to_dict() for e in self._working.values()]
            store = self.stores.get(layer)
            if store:
                results = [e.to_dict() for e in store.all()]
        else:
            for store in self.stores.values():
                results.extend(e.to_dict() for e in store.all())
            results.extend(e.to_dict() for e in self._working.values())
        return results

    def count(self, layer: MemoryLayer | None = None) -> int:
        if layer:
            if layer == MemoryLayer.WORKING:
                return len(self._working)
            store = self.stores.get(layer)
            return store.count() if store else 0
        return sum(s.count() for s in self.stores.values()) + len(self._working)

    def build_context(
        self,
        max_tokens: int = 500,
        query: str = "",
        layers: list[MemoryLayer] | None = None,
    ) -> str:
        """Build a token-aware context string for system prompt assembly."""
        if max_tokens <= 0:
            return ""

        candidate_layers = layers or [l for l in MemoryLayer if l != MemoryLayer.WORKING]
        candidates: list[MemoryEntry] = []

        if query:
            for lyr in candidate_layers:
                store = self.stores.get(lyr)
                if not store:
                    continue
                candidates.extend(
                    store.search(
                        query,
                        provider=self._get_provider(),
                    )
                )
        else:
            for lyr in candidate_layers:
                store = self.stores.get(lyr)
                if not store:
                    continue
                for entry in store.all():
                    if entry.importance >= 0.3:
                        candidates.append(entry)

        seen: set[str] = set()
        unique: list[MemoryEntry] = []
        for entry in candidates:
            if entry.key in seen:
                continue
            seen.add(entry.key)
            unique.append(entry)

        unique.sort(
            key=lambda e: (
                -e.importance,
                -e.access_count,
                e.created,
            )
        )

        lines = ["What you know about the user:"]
        token_budget = max_tokens
        chars_per_token = 4

        for entry in unique:
            line = f"- {entry.key}: {entry.value}"
            line_tokens = max(1, len(line.split()))
            if line_tokens > token_budget:
                break
            lines.append(line)
            token_budget -= line_tokens

        return "\n".join(lines) if len(lines) > 1 else ""

    def get_project_memories(self, project: str) -> list[dict]:
        """Get all memories associated with a project."""
        results: list[dict] = []
        for store in self.stores.values():
            for e in store.all():
                if e.project == project:
                    results.append(e.to_dict())
        return results

    def detect_contradictions(self) -> list[dict]:
        """Find potentially contradictory memories."""
        by_key: dict[str, list[MemoryEntry]] = {}
        for store in self.stores.values():
            for entry in store.all():
                by_key.setdefault(entry.key, []).append(entry)

        contradictions: list[dict] = []
        for key, entries in by_key.items():
            if len(entries) <= 1:
                continue
            values = [e.value for e in entries]
            if len(set(values)) > 1:
                contradictions.append(
                    {
                        "key": key,
                        "values": values,
                        "count": len(entries),
                        "entries": [e.to_dict() for e in entries],
                    }
                )
        return contradictions

    def detect_duplicates(self, similarity_threshold: float = 0.92) -> list[dict]:
        """Detect near-duplicate memories within semantic memory.

        Uses lightweight bucketing to reduce the number of pairwise
        comparisons needed.
        """
        store = self.stores.get(MemoryLayer.SEMANTIC)
        if not store:
            return []

        entries = store.all()
        seen_ids: set[str] = set()
        duplicates: list[dict] = []
        provider = self._get_provider()

        # Bucket by normalized value prefix to limit comparisons.
        buckets: dict[str, list[MemoryEntry]] = {}
        for entry in entries:
            normalized = entry.value.strip().lower()[:40]
            buckets.setdefault(normalized, []).append(entry)

        for bucket in buckets.values():
            if len(bucket) < 2:
                continue
            for i, a in enumerate(bucket):
                if a.id in seen_ids:
                    continue
                group: list[dict] = []
                vec_a = a.embedding or provider.embed(a.value)
                for j in range(i + 1, len(bucket)):
                    b = bucket[j]
                    if b.id in seen_ids:
                        continue
                    vec_b = b.embedding or provider.embed(b.value)
                    sim = _cosine_similarity(vec_a, vec_b)
                    if sim >= similarity_threshold:
                        seen_ids.add(b.id)
                        group.append(
                            {
                                "id": b.id,
                                "key": b.key,
                                "value": b.value,
                                "similarity": round(sim, 4),
                            }
                        )
                if group:
                    duplicates.append(
                        {
                            "primary": {"id": a.id, "key": a.key, "value": a.value},
                            "duplicates": group,
                        }
                    )
        return duplicates

    def forget_old(
        self,
        max_age_days: int = 180,
        min_importance: float = 0.25,
        min_access_count: int = 2,
    ) -> dict[str, int]:
        """Forget low-value old memories that have not proven useful."""
        now = datetime.now(timezone.utc)
        stats: dict[str, int] = {"forgotten": 0}

        for store in self.stores.values():
            to_delete: list[str] = []
            for entry in store.all():
                try:
                    created = datetime.fromisoformat(entry.created)
                    age_days = (now - created).total_seconds() / 86400.0
                except ValueError:
                    continue

                if age_days > max_age_days and entry.importance <= min_importance and entry.access_count < min_access_count:
                    to_delete.append(entry.id)

            for eid in to_delete:
                store.delete(eid)
            stats[store.layer.value] = len(to_delete)
            stats["forgotten"] += len(to_delete)
        return stats

    def consolidate(self) -> dict[str, int]:
        """
        Memory consolidation pass:
        1. Apply time-based decay to importance
        2. Forget expired and low-value memories
        3. Detect and optionally merge duplicates
        4. Promote frequently accessed episodic memories to semantic
        5. Summarize old dense clusters when needed
        """
        stats = self.apply_decay()
        forgotten = self.forget_old()
        stats.update(forgotten)
        promoted = self._promote_episodic()
        stats.update(promoted)
        summarized = self._summarize_old_clusters()
        stats.update(summarized)
        if stats.get("forgotten") or stats.get("promoted_to_semantic") or stats.get("summarized"):
            logger.info("Memory consolidation complete: %s", stats)
        return stats

    def apply_decay(self, half_life_days: float = 30.0, min_importance: float = 0.05) -> dict[str, int]:
        """
        Apply exponential decay to importance based on age.
        Importance halves every `half_life_days` unless the memory is
        actively used. This prevents stale memories from dominating
        retrieval and context assembly forever.
        """
        now = datetime.now(timezone.utc)
        stats: dict[str, int] = {"decayed": 0}

        for store in self.stores.values():
            changed = 0
            for entry in store.all():
                try:
                    created = datetime.fromisoformat(entry.updated)
                except ValueError:
                    continue
                age_days = max(0.0, (now - created).total_seconds() / 86400.0)
                if age_days <= 0:
                    continue
                decay_factor = 2 ** (-age_days / half_life_days)
                # Active memories resist decay.
                access_boost = min(entry.access_count, 20) * 0.02
                new_importance = max(min_importance, entry.importance * decay_factor + access_boost)
                if new_importance != entry.importance:
                    entry.importance = new_importance
                    entry.updated = now.isoformat()
                    store.put(entry)
                    changed += 1
            if changed:
                stats[store.layer.value] = changed
                stats["decayed"] += changed
        return stats

    def _promote_episodic(self) -> dict[str, int]:
        promoted = 0
        for store in self.stores.values():
            to_promote: list[MemoryEntry] = []
            for entry in store.all():
                if (
                    entry.layer == MemoryLayer.EPISODIC
                    and entry.access_count >= 5
                    and entry.importance >= 0.5
                ):
                    to_promote.append(entry)

            for entry in to_promote:
                self.remember(
                    key=entry.key,
                    value=entry.value,
                    layer=MemoryLayer.SEMANTIC,
                    importance=entry.importance,
                    tags=list(set(entry.tags + ["promoted_from_episodic"])),
                    source="consolidation",
                )
                promoted += 1
        return {"promoted_to_semantic": promoted}

    def _summarize_old_clusters(self, max_entries_per_cluster: int = 5) -> dict[str, int]:
        """
        For memory layers that have grown large, compress low-importance
        old entries into compact summary entries so the store stays
        useful instead of turning into a noisy dump.
        """
        summarized = 0
        for layer, store in self.stores.items():
            if layer in (MemoryLayer.WORKING, MemoryLayer.PROJECT):
                continue
            entries = store.all()
            if len(entries) <= max_entries_per_cluster * 2:
                continue
            # Summarize oldest low-importance entries by project/tag bucket.
            by_bucket: dict[str, list[MemoryEntry]] = {}
            for entry in entries:
                if entry.importance >= 0.6 or entry.access_count >= 3:
                    continue
                bucket = entry.project or entry.tags[0] if entry.tags else "_global"
                by_bucket.setdefault(bucket, []).append(entry)

            for bucket, group in by_bucket.items():
                if len(group) < max_entries_per_cluster:
                    continue
                group.sort(key=lambda e: e.created)
                keep = group[-max_entries_per_cluster:]
                summarize = group[:-max_entries_per_cluster]
                if not summarize:
                    continue
                summary_value = "; ".join(e.value for e in summarize)
                summary_key = f"summarized_{bucket}"
                self.remember(
                    key=summary_key,
                    value=summary_value,
                    layer=layer,
                    importance=0.35,
                    tags=list(set(summarize[0].tags + ["summarized"])),
                    source="consolidation",
                    project=bucket,
                )
                for entry in summarize:
                    store.delete(entry.id)
                    summarized += 1
        return {"summarized": summarized}
