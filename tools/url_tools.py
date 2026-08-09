"""tools/url_tools.py -- Universal URL understanding tools."""

from __future__ import annotations

import re

from tools import ToolDef, ToolRegistry

_URL_RE = re.compile(r"https?://(?:[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+)", re.IGNORECASE)


def register(registry: ToolRegistry, url_store=None):
    from url_understanding import (
        UrlExtractor,
        UrlMemory,
        classify_url,
        detect_urls,
    )

    store = url_store or UrlMemory()

    def _get_extractor() -> UrlExtractor:
        try:
            reg = registry
            return UrlExtractor(registry=reg)
        except Exception:
            return UrlExtractor()

    def understand_url(url: str = "", remember: bool = False) -> str:
        """Inspect a URL and return a normalized understanding of the resource.

        - Detects malformed input.
        - Extracts via HTTP first, then browser fallback, then document parsing.
        - Optionally stores the resource for later conversation recall.
        """
        url = (url or "").strip()
        if not url:
            return "Error: provide a URL to inspect."
        urls = detect_urls(url)
        if not urls:
            return "Error: no valid http/https URL found in input."
        target = urls[0]
        resource = _get_extractor().extract(target)

        if remember:
            try:
                store.put(resource)
            except Exception:
                pass

        context = resource.to_conversation_context()
        if not context:
            return (
                f"[TOOL_STATUS: FAILED] I could not extract readable content from {target}. "
                f"Status={resource.status}; quality={resource.extraction_quality}. "
                + ("Errors: " + "; ".join(resource.errors[:3]) if resource.errors else "")
            )
        return f"[TOOL_STATUS: SUCCESS] {context}"

    def recall_url(url: str = "") -> str:
        """Recall a previously inspected URL from session memory."""
        url = (url or "").strip()
        if not url:
            return "Error: provide the exact URL to recall."
        urls = detect_urls(url)
        if not urls:
            return "Error: no valid http/https URL found."
        resource = store.get(urls[0])
        if not resource:
            return f"No previously inspected URL found for {urls[0]}."
        return resource.to_conversation_context()

    registry.register(ToolDef(
        name="understand_url",
        description=(
            "Inspect a URL and return normalized extracted content. "
            "Use this when the user shares a link and expects VYREN to read, "
            "watch, or summarize it."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "url": {
                    "type": "STRING",
                    "description": "The URL to inspect",
                },
                "remember": {
                    "type": "BOOLEAN",
                    "description": "Store this resource for later recall in this session",
                },
            },
            "required": ["url"],
        },
        handler=understand_url,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="recall_url",
        description="Recall a previously inspected URL from session memory.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "url": {
                    "type": "STRING",
                    "description": "Exact URL previously inspected with understand_url",
                },
            },
            "required": ["url"],
        },
        handler=recall_url,
        safety_level="safe",
    ))
