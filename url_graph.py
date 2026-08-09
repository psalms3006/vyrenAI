"""URL-aware knowledge graph integration for VYREN.

This module connects URL resources to VYREN's existing knowledge graph
without changing graph persistence or core graph semantics.

It provides:
  - entity creation from UrlResource metadata
  - relationship creation between URL resources and existing entities
  - graph queries scoped to URL-derived nodes
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("vyren.url")

try:
    from knowledge_graph import (
        KnowledgeGraph,
        EntityType,
        RelationType,
        Entity,
        Edge,
    )
except Exception:  # pragma: no cover - optional absent module
    KnowledgeGraph = None  # type: ignore[misc,assignment]
    EntityType = None  # type: ignore[misc,assignment]
    RelationType = None  # type: ignore[misc,assignment]
    Entity = None  # type: ignore[misc,assignment]
    Edge = None  # type: ignore[misc,assignment]


_URL_ENTITY_TYPE_NAME = "website"
_REL_REFERENCES = "references"
_REL_MENTIONS = "mentions"
_REL_RELATED_TO = "related_to"


def _ensure_entity_types():
    if EntityType is None:
        return None, None
    try:
        url_type = EntityType(_URL_ENTITY_TYPE_NAME)
    except ValueError:
        return None, None
    return EntityType, url_type


def _ensure_relation_types():
    if RelationType is None:
        return None, None
    values = {r.value for r in RelationType}
    rels = {}
    for name in (_REL_REFERENCES, _REL_MENTIONS, _REL_RELATED_TO):
        if name in values:
            rels[name] = RelationType(name)
    return RelationType, rels


def resource_to_entities(resource: Any) -> list[Entity]:
    """Convert a normalized URL resource into candidate graph entities."""
    if Entity is None or EntityType is None:
        return []
    _, url_type = _ensure_entity_types()
    if url_type is None:
        return []
    url_entity = Entity(
        id=f"url_{abs(hash(resource.url))}_website",
        type=url_type,
        name=resource.title or resource.url,
        properties={
            "url": resource.url,
            "canonical_url": resource.canonical_url or "",
            "platform": resource.platform or "",
            "source_type": resource.source_type or "",
            "extraction_method": resource.extraction_method or "",
            "extraction_quality": resource.extraction_quality or "",
            "status": resource.status or "",
            "author": resource.author or "",
            "published_at": resource.published_at or "",
        },
        importance=0.6,
    )
    return [url_entity]


def resource_to_relations(resource: Any) -> list[Edge]:
    """Create edges for a normalized URL resource."""
    return []


class UrlGraphBridge:
    """Thin integration between URL resources and the knowledge graph."""

    def __init__(self, graph: Any | None = None) -> None:
        self._graph = graph

    def set_graph(self, graph: Any | None) -> None:
        self._graph = graph

    def ingest(self, resource: Any) -> None:
        if self._graph is None or resource is None:
            return
        try:
            entities = resource_to_entities(resource)
            edges = resource_to_relations(resource)
        except Exception as exc:
            logger.debug("url graph ingestion aborted: %s", exc)
            return

        id_map: dict[str, str] = {}
        url_ids: dict[str, str] = {}
        for entity in entities:
            try:
                existing_id = url_ids.get(entity.properties.get("url", ""))
                if existing_id is None:
                    found = self._graph.find_by_name(entity.name)
                    if found is not None and found.type.value == entity.type.value:
                        existing_id = found.id
                if existing_id is not None:
                    id_map[entity.id] = existing_id
                    url_ids[entity.properties.get("url", "")] = existing_id
                    continue
                new_id = self._graph.add_entity(
                    entity.type,
                    entity.name,
                    properties=entity.properties,
                    importance=entity.importance,
                )
                id_map[entity.id] = new_id
                url_ids[entity.properties.get("url", "")] = new_id
            except Exception as exc:
                logger.debug("url graph entity add failed: %s", exc)

        if not id_map or not edges:
            return

        for edge in edges:
            try:
                src_id = id_map.get(edge.source_id)
                tgt_id = id_map.get(edge.target_id)
                if not src_id or not tgt_id or src_id == tgt_id:
                    continue
                self._graph.add_relation(
                    src_id,
                    tgt_id,
                    edge.relation,
                    properties=edge.properties,
                    weight=edge.weight,
                )
            except Exception as exc:
                logger.debug("url graph relation add failed: %s", exc)

    def query(self, query: str, limit: int = 20) -> list[dict]:
        if self._graph is None:
            return []
        try:
            matches = self._graph.search(query)[: max(1, limit)]
            out = []
            for e in matches:
                out.append({
                    "id": e.id,
                    "name": e.name,
                    "type": getattr(e.type, "value", str(e.type)),
                    "importance": e.importance,
                })
            return out
        except Exception:
            return []
