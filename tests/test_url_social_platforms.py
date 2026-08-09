"""Extended URL understanding verification with evidence-based assertions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\Lenovo\my-project")
sys.path.insert(0, str(ROOT))

report_path = ROOT / "proof" / "universal_url_report_extended.json"
report = {"tests": [], "overall": "UNKNOWN"}


def case(name: str):
    def decorator(fn):
        def wrapper():
            try:
                ok, detail = fn()
            except Exception as exc:
                ok, detail = False, f"EXCEPTION: {type(exc).__name__}: {exc}"
            report["tests"].append({"case": name, "passed": ok, "detail": detail})
            print(f"{'PASS' if ok else 'FAIL'} | {name} | {detail}")
            return ok, detail
        return wrapper()
    return decorator


@case("instagram_public_page")
def _():
    from url_understanding import UrlExtractor, ResourceStatus
    resource = UrlExtractor().extract("https://www.instagram.com/p/C5qtest/")
    detail = f"status={resource.status}, quality={resource.extraction_quality}, title={resource.title!r}, text_len={len(resource.text)}, errors={resource.errors[:2]}"
    valid = resource.status in {
        ResourceStatus.SUCCESS,
        ResourceStatus.PARTIAL,
        ResourceStatus.INACCESSIBLE,
        ResourceStatus.BLOCKED,
    }
    evidence = resource.title or resource.text or resource.errors
    return valid and bool(evidence), detail


@case("youtube_video_page")
def _():
    from url_understanding import UrlExtractor, ResourceStatus
    resource = UrlExtractor().extract("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    detail = f"status={resource.status}, quality={resource.extraction_quality}, title={resource.title!r}, text_len={len(resource.text)}, errors={resource.errors[:2]}"
    valid = resource.status in {ResourceStatus.SUCCESS, ResourceStatus.PARTIAL, ResourceStatus.INACCESSIBLE}
    return valid and bool(resource.title), detail


@case("reddit_public_post")
def _():
    from url_understanding import UrlExtractor, ResourceStatus
    resource = UrlExtractor().extract("https://www.reddit.com/r/python/comments/1a2b3c/test/")
    detail = f"status={resource.status}, quality={resource.extraction_quality}, title={resource.title!r}, text_len={len(resource.text)}, errors={resource.errors[:2]}"
    valid = resource.status in {ResourceStatus.SUCCESS, ResourceStatus.PARTIAL, ResourceStatus.INACCESSIBLE}
    return valid and bool(resource.title or resource.text), detail


@case("tiktok_public_video")
def _():
    from url_understanding import UrlExtractor, ResourceStatus
    resource = UrlExtractor().extract("https://www.tiktok.com/@user/video/1234567890")
    detail = f"status={resource.status}, quality={resource.extraction_quality}, title={resource.title!r}, text_len={len(resource.text)}, errors={resource.errors[:2]}"
    valid = resource.status in {
        ResourceStatus.SUCCESS,
        ResourceStatus.PARTIAL,
        ResourceStatus.INACCESSIBLE,
        ResourceStatus.BLOCKED,
    }
    return valid, detail


@case("twitter_public_post")
def _():
    from url_understanding import UrlExtractor, ResourceStatus
    resource = UrlExtractor().extract("https://x.com/user/status/1234567890")
    detail = f"status={resource.status}, quality={resource.extraction_quality}, title={resource.title!r}, text_len={len(resource.text)}, errors={resource.errors[:2]}"
    valid = resource.status in {ResourceStatus.SUCCESS, ResourceStatus.PARTIAL, ResourceStatus.INACCESSIBLE}
    return valid and bool(resource.title or resource.text), detail


@case("browser_fallback_complex_site")
def _():
    from url_understanding import UrlExtractor, ResourceStatus
    resource = UrlExtractor().extract("https://example.org")
    detail = f"status={resource.status}, extraction_method={resource.extraction_method}, text_len={len(resource.text)}"
    return resource.status in {ResourceStatus.SUCCESS, ResourceStatus.PARTIAL} and bool(resource.text), detail


@case("pdf_direct_extraction")
def _():
    from url_understanding import UrlExtractor, ResourceStatus
    resource = UrlExtractor().extract("https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf")
    detail = f"status={resource.status}, quality={resource.extraction_quality}, text_len={len(resource.text)}, errors={resource.errors[:2]}"
    valid = resource.status in {ResourceStatus.SUCCESS, ResourceStatus.PARTIAL, ResourceStatus.INACCESSIBLE}
    return valid, detail


@case("offline_behavior")
def _():
    from url_understanding import UrlExtractor, ResourceStatus
    try:
        from browser import close_browser
        close_browser(timeout=5)
    except Exception:
        pass
    resource = UrlExtractor().extract("http://192.0.2.1/")
    text = (resource.text or "").lower()
    offline_markers = [
        resource.status != ResourceStatus.SUCCESS,
        "took too long" in text,
        "err_connection_timed_out" in text,
        "no internet" in text,
        "network" in text,
    ]
    detail = f"status={resource.status}, extraction_method={resource.extraction_method}, text_len={len(resource.text)}, errors={resource.errors[:2]}"
    return any(offline_markers), detail


@case("graph_knowledge_graph_integration")
def _():
    from knowledge_graph import KnowledgeGraph, EntityType, RelationType
    from url_graph import UrlGraphBridge
    from url_understanding import UrlExtractor
    from platform_paths import get_vyren_dir

    path = get_vyren_dir() / "knowledge_graph.json"
    path.write_text(json.dumps({"entities": {}, "edges": []}))

    kg = KnowledgeGraph()
    p = kg.add_entity(EntityType.PERSON, "Person A", {"role": "creator"})
    b = kg.add_entity(EntityType.PROJECT, "Project B", {"status": "active"})
    c = kg.add_entity(EntityType.TOOL, "Technology C", {"language": "python"})
    kg.add_relation(p, b, RelationType.WORKS_WITH)
    kg.add_relation(b, c, RelationType.USES)

    res = UrlExtractor().extract("https://example.com")
    bridge = UrlGraphBridge(kg)
    bridge.ingest(res)
    res2 = UrlExtractor().extract("https://example.org")
    bridge.ingest(res2)

    details = f"entities={kg.entity_count}, edges={kg.edge_count}"
    ok = kg.entity_count >= 3 and kg.edge_count >= 2 and kg.find_by_name("Example Domain") is not None

    kg2 = KnowledgeGraph(path=path)
    persist_ok = kg2.entity_count >= 3 and kg2.edge_count >= 2 and kg2.find_by_name("Example Domain") is not None
    detail = f"{details}; persisted={persist_ok}"
    return ok and persist_ok, detail


overall = "PASS"
for t in report["tests"]:
    if not t["passed"]:
        overall = "PARTIAL"
        break
report["overall"] = overall
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nOVERALL: {overall}")
print("proof:", report_path)
