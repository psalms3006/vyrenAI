"""tools/browser_tools.py -- Browser automation tools.

Uses VYREN's browser singleton to open pages, search, click, type,
scroll, read page text, fill forms, and close the browser.
"""

from tools import ToolDef, ToolRegistry


def register(registry: ToolRegistry):
    from browser import (
        close_browser,
        click,
        fill_form,
        get_text,
        go_to,
        press,
        screenshot,
        scroll,
        search,
        smart_click,
        smart_type,
        type_text,
    )

    def browser_control(
        action: str = "",
        url: str = "",
        query: str = "",
        selector: str = "",
        text: str = "",
        description: str = "",
        key: str = "",
        direction: str = "down",
        amount: int = 500,
        fields: dict | None = None,
        timeout: int = 30,
    ) -> str:
        """Control the web browser.

        action: go_to | search | click | type | scroll | press |
                get_text | fill_form | smart_click | smart_type | screenshot | close
        """
        action = (action or "").strip().lower()
        try:
            if action == "go_to":
                if not url:
                    return "browser_control requires url for go_to"
                return go_to(url=url, timeout=timeout)
            if action == "search":
                if not query:
                    return "browser_control requires query for search"
                return search(query=query, timeout=timeout)
            if action == "click":
                return click(selector=selector or None, text=text or None, timeout=timeout)
            if action == "type":
                if not text:
                    return "browser_control requires text for type"
                return type_text(selector=selector or None, text=text, timeout=timeout)
            if action == "scroll":
                return scroll(direction=direction, amount=int(amount), timeout=timeout)
            if action == "press":
                if not key:
                    return "browser_control requires key for press"
                return press(key=key, timeout=timeout)
            if action == "get_text":
                return get_text(timeout=timeout)
            if action == "screenshot":
                return screenshot(timeout=timeout)
            if action == "fill_form":
                return fill_form(fields=fields or {}, timeout=max(timeout, 60))
            if action == "smart_click":
                if not description:
                    return "browser_control requires description for smart_click"
                return smart_click(description=description, timeout=timeout)
            if action == "smart_type":
                if not description or not text:
                    return "browser_control requires description and text for smart_type"
                return smart_type(description=description, text=text, timeout=timeout)
            if action == "close":
                return close_browser(timeout=timeout)
            return f"Unknown browser action: {action}"
        except Exception as e:
            return f"Browser control failed: {type(e).__name__} -- {e}"

    registry.register(
        ToolDef(
            name="browser_control",
            description=(
                "Control the web browser with Playwright. "
                "Actions: go_to, search, click, type, scroll, press, "
                "get_text, fill_form, smart_click, smart_type, screenshot, close."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Browser action name"},
                    "url": {"type": "string", "description": "URL for go_to"},
                    "query": {"type": "string", "description": "Search query"},
                    "selector": {"type": "string", "description": "CSS selector"},
                    "text": {"type": "string", "description": "Text to type or click"},
                    "description": {"type": "string", "description": "Element description for smart actions"},
                    "key": {"type": "string", "description": "Key name for press"},
                    "direction": {"type": "string", "description": "Scroll direction"},
                    "amount": {"type": "integer", "description": "Scroll amount"},
                    "fields": {"type": "object", "description": "Form fields for fill_form"},
                    "timeout": {"type": "integer", "description": "Timeout seconds"},
                },
                "required": ["action"],
            },
            handler=browser_control,
            safety_level="consequential",
        )
    )
