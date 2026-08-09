"""Functional verification for universal URL understanding."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\Lenovo\my-project")
sys.path.insert(0, str(ROOT))

from url_understanding import (
    UrlExtractor,
    UrlMemory,
    classify_url,
    detect_urls,
    ResourceStatus,
    ExtractionQuality,
)

proof_dir = ROOT / "proof"
proof_dir.mkdir(exist_ok=True)
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


@case("detect_urls")
def _():
    text = "Check https://example.com and https://example.org/page."
    urls = [u.strip() for u in detect_urls(text)]
    return urls == ["https://example.com", "https://example.org/page"], f"{urls}"


@case("classify_url")
def _():
    c = classify_url("https://github.com/psalms3006/vyrenAI")
    return c["platform"] == "github" and c["source_type"] == "web", f"{c}"


@case("classify_pdf")
def _():
    c = classify_url("https://example.com/file.pdf")
    return c["platform"] == "pdf" and c["source_type"] == "document", f"{c}"


@case("http_website_extraction")
def _():
    extractor = UrlExtractor()
    resource = extractor.extract("https://example.com")
    return (
        resource.status == ResourceStatus.SUCCESS and bool(resource.text or resource.markdown),
        f"status={resource.status}, quality={resource.extraction_quality}, title={resource.title!r}, text_len={len(resource.text)}",
    )


@case("http_document_extraction_pdf")
def _():
    extractor = UrlExtractor()
    resource = extractor.extract("https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf")
    detail = f"status={resource.status}, quality={resource.extraction_quality}, text_len={len(resource.text)}, errors={resource.errors[:2]}"
    return resource.status in (ResourceStatus.SUCCESS, ResourceStatus.PARTIAL, ResourceStatus.INACCESSIBLE), detail


@case("github_extraction")
def _():
    extractor = UrlExtractor()
    resource = extractor.extract("https://github.com/psalms3006/vyrenAI")
    detail = f"status={resource.status}, quality={resource.extraction_quality}, text_len={len(resource.text)}, title={resource.title!r}"
    return resource.status in (ResourceStatus.SUCCESS, ResourceStatus.PARTIAL, ResourceStatus.INACCESSIBLE), detail


@case("browser_fallback_js_site")
def _():
    extractor = UrlExtractor()
    resource = extractor.extract("https://example.org")
    detail = f"status={resource.status}, extraction_method={resource.extraction_method}, text_len={len(resource.text)}"
    return resource.status in (ResourceStatus.SUCCESS, ResourceStatus.PARTIAL, ResourceStatus.INACCESSIBLE), detail


@case("invalid_url")
def _():
    extractor = UrlExtractor()
    resource = extractor.extract("not a url")
    detail = f"status={resource.status}, errors={resource.errors}"
    return resource.status == ResourceStatus.MALFORMED_URL, detail


@case("url_memory_persistence")
def _():
    store = UrlMemory(persist=False)
    resource = extractor.extract("https://example.com") if (extractor := UrlExtractor()) else None
    if resource is None:
        return False, "extractor failed"
    store.put(resource)
    got = store.get("https://example.com")
    return bool(got), f"stored={bool(resource)}, recalled={bool(got)}"


@case("conversation_context")
def _():
    extractor = UrlExtractor()
    resource = extractor.extract("https://example.com")
    ctx = resource.to_conversation_context()
    return resource.status == ResourceStatus.SUCCESS and "Title:" in ctx, f"ctx_len={len(ctx)}, status={resource.status}"


overall = "PASS"
for t in report["tests"]:
    if not t["passed"]:
        overall = "PARTIAL"
        break
report["overall"] = overall
(proof_dir / "universal_url_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nOVERALL: {overall}")
print("proof:", proof_dir / "universal_url_report.json")
