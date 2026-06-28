"""tools/web_tools.py -- Web search tool for VYREN.

Uses a free, no-API-key-required approach to search the web.
Falls back gracefully if the search fails.
"""

import json
import urllib.request
import urllib.parse

from tools import ToolDef, ToolRegistry


def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    """Search using DuckDuckGo's lite HTML endpoint. No API key needed."""
    url = (
        "https://lite.duckduckgo.com/lite/?"
        + urllib.parse.urlencode({"q": query, "kl": "wt-wt"})
    )
    req = urllib.request.Request(url, headers={"User-Agent": "VYREN/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    # Parse the lite HTML — extract result links and snippets
    results = []
    # DDG lite wraps results in <a class="result-link"> and next line has snippet
    import re
    # Simple extraction: find all links that look like search results
    links = re.findall(r'<a[^>]+class="result-link"[^>]*href="([^"]+)"', html)
    snippets = re.findall(
        r'<td[^>]+class="result-snippet"[^>]*>(.*?)</td>',
        html, re.DOTALL
    )
    # Clean HTML tags from snippets
    clean = re.compile(r"<[^>]+>")

    for i in range(min(max_results, len(links))):
        result = {"url": links[i]}
        if i < len(snippets):
            result["snippet"] = clean.sub("", snippets[i]).strip()[:200]
        else:
            result["snippet"] = ""
        results.append(result)

    return results


def register(registry: ToolRegistry):

    def web_search(query: str) -> str:
        """Search the web for information."""
        results = _ddg_search(query)
        if not results:
            return (
                f"Search returned no results for '{query}'. "
                "This could be a network issue or the query was too specific. "
                "Try rephrasing."
            )

        lines = [f"Web search results for '{query}':\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('snippet', 'No snippet')}")
            lines.append(f"   {r['url']}")
            lines.append("")

        # Cross-reference reminder for the model
        lines.append(
            "Note: These results are from a single search engine. "
            "For important decisions, consider cross-referencing with other sources."
        )
        return "\n".join(lines)

    registry.register(ToolDef(
        name="web_search",
        description=(
            "Search the web for current information, news, facts, or research. "
            "Returns a list of relevant results with URLs and snippets. "
            "Use this for anything that needs up-to-date information."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query — be specific for best results",
                },
            },
            "required": ["query"],
        },
        handler=web_search,
        safety_level="safe",
    ))