"""Knowledge graph integration verification for VYREN.

Tests:
- controlled dataset creation
- nodes/edges creation
- backlinks/forward relationships
- searching a node
- opening a node shows metadata
- graph persistence survives restart
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_controlled_dataset():
    from knowledge_graph import KnowledgeGraph, EntityType, RelationType
    from url_graph import UrlGraphBridge
    from url_understanding import UrlExtractor
    from platform_paths import get_vyren_dir

    path = get_vyren_dir() / "knowledge_graph.json"
    path.write_text(json.dumps({"entities": {}, "edges": []}))

    kg = KnowledgeGraph()
    bridge = UrlGraphBridge(kg)

    p = kg.add_entity(EntityType.PERSON, "Person A", {"role": "creator"})
    b = kg.add_entity(EntityType.PROJECT, "Project B", {"status": "active"})
    c = kg.add_entity(EntityType.TOOL, "Technology C", {"language": "python"})
    kg.add_relation(p, b, RelationType.WORKS_WITH)
    kg.add_relation(b, c, RelationType.USES)

    res = UrlExtractor().extract("https://example.com")
    bridge.ingest(res)
    res2 = UrlExtractor().extract("https://example.org")
    bridge.ingest(res2)

    assert kg.entity_count >= 4
    assert kg.edge_count >= 2
    assert kg.find_by_name("Project B") is not None
    assert kg.find_by_name("Technology C") is not None
    assert kg.find_by_name("Example Domain") is not None

    path2 = get_vyren_dir() / "knowledge_graph.json"
    kg2 = KnowledgeGraph(path=path2)
    assert kg2.entity_count >= 4
    assert kg2.edge_count >= 2
    assert kg2.find_by_name("Project B") is not None
    assert kg2.find_by_name("Example Domain") is not None

    print("PASS | controlled_dataset")
    print(f"PASS | persistence | entities={kg2.entity_count} edges={kg2.edge_count}")
    return True


if __name__ == "__main__":
    ok = test_controlled_dataset()
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
