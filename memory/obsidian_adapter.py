"""Obsidian-secondbrain adapter for VYREN memory.

Reads an Obsidian vault and exposes entities/relationships compatible with
the knowledge graph layer. This is intentionally local-only and does NOT
upload vault contents anywhere.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ObsidianEntity:
    id: str
    name: str
    type: str = "concept"
    source: str = "obsidian"
    properties: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ObsidianRelation:
    source: str
    target: str
    relation: str = "related_to"
    source_backend: str = "obsidian"
    properties: dict[str, object] = field(default_factory=dict)


_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)(?:[|#][^\[\]\n]*?)?\]\]")
_TAG_RE = re.compile(r"#[^\s#]{2,}")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


class ObsidianSecondBrain:
    def __init__(self, vault_root: str | Path) -> None:
        self.root = Path(vault_root)
        self._name = self.root.name or "obsidian"

    def _walk_markdown(self) -> Iterable[tuple[Path, str]]:
        if not self.root.exists():
            return []
        out = []
        for p in self.root.rglob("*.md"):
            try:
                rel = p.relative_to(self.root)
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            out.append((p, text))
        return out

    def entities(self) -> list[ObsidianEntity]:
        seen: dict[str, ObsidianEntity] = {}
        for path, text in self._walk_markdown():
            file_id = f"obsidian://{self._name}/note/{path.name}"
            entity = ObsidianEntity(
                id=file_id,
                name=path.stem,
                type="note",
                properties={"path": str(path), "chars": len(text)},
            )
            seen[file_id] = entity
            for link in set(_WIKILINK_RE.findall(text)):
                eid = f"obsidian://{self._name}/concept/{link}"
                seen.setdefault(
                    eid,
                    ObsidianEntity(id=eid, name=link, type="concept", properties={"kind": "wikilink"}),
                )
            for tag in set(_TAG_RE.findall(text)):
                eid = f"obsidian://{self._name}/tag/{tag}"
                seen.setdefault(
                    eid,
                    ObsidianEntity(id=eid, name=tag, type="tag", properties={"kind": "tag"}),
                )
            for heading in set(_HEADING_RE.findall(text)):
                eid = f"obsidian://{self._name}/heading/{heading}"
                seen.setdefault(
                    eid,
                    ObsidianEntity(id=eid, name=heading, type="heading", properties={"kind": "heading"}),
                )
        return list(seen.values())

    def relations(self) -> list[ObsidianRelation]:
        rels: dict[tuple[str, str, str], ObsidianRelation] = {}
        note_ids = {e.id: e for e in self.entities() if e.type == "note"}
        for path, text in self._walk_markdown():
            src = f"obsidian://{self._name}/note/{path.name}"
            if src not in note_ids:
                continue
            for link in set(_WIKILINK_RE.findall(text)):
                target = f"obsidian://{self._name}/concept/{link}"
                key = (src, target, "links_to")
                rels.setdefault(key, ObsidianRelation(source=src, target=target, relation="links_to"))
            for tag in _TAG_RE.findall(text):
                target = f"obsidian://{self._name}/tag/{tag}"
                key = (src, target, "tagged_with")
                rels.setdefault(key, ObsidianRelation(source=src, target=target, relation="tagged_with"))
        return list(rels.values())

    def to_graph_payload(self) -> dict:
        entities = self.entities()
        links = [
            {
                "source": r.source,
                "target": r.target,
                "relation": r.relation,
                "source_backend": r.source_backend,
            }
            for r in self.relations()
        ]
        return {
            "nodes": [
                {
                    "id": e.id,
                    "label": e.name,
                    "type": e.type,
                    "importance": 1,
                    "properties": e.properties,
                }
                for e in entities
            ],
            "links": links,
            "stats": {
                "entities": len(entities),
                "edges": len(links),
                "types": {
                    k: sum(1 for e in entities if e.type == k)
                    for k in sorted({e.type for e in entities})
                },
            },
        }
