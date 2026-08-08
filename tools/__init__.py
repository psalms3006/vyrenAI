"""
tools/__init__.py -- Tool registry and tool loading.

A tool is a named capability with a description, typed parameters,
a handler function, and a safety level. The registry is the single
place tools are registered and looked up.

Adding a new capability = write one tool file + register it here.
Never edit main.py or the core loop to add a tool.

v2.2 changes:
  - to_gemini_tools() now returns raw dicts (NOVA's proven format)
    instead of types.FunctionDeclaration objects. This avoids
    serialization issues with the google-genai SDK.
  - Added _sanitize_tool_name() to reject names that don't start
    with a letter (Gemini API requirement). Invalid tools are
    skipped with a warning instead of killing the entire session.
  - _dict_to_schema() now correctly filters to only Schema-safe keys.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("vyren.tools")

# Gemini API requires function names to start with a letter and
# contain only [a-zA-Z0-9_]. Enforce this at registration time.
_TOOL_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


def _sanitize_tool_name(name: str) -> str | None:
    """Validate a tool name against Gemini's requirements.

    Returns the name if valid, None if invalid.
    Gemini requires: starts with a letter, [a-zA-Z0-9_] only.
    """
    if _TOOL_NAME_RE.match(name):
        return name
    return None


@dataclass
class ToolDef:
    """Definition of a single tool."""
    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable[..., str]
    safety_level: str = "safe"  # "safe" or "consequential"


class ToolRegistry:
    """Registry of all available tools. Converts to Gemini format for the API."""

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef):
        # Validate name at registration time — fail fast
        clean = _sanitize_tool_name(tool.name)
        if clean is None:
            logger.error(
                "Tool name '%s' is invalid for Gemini API (must start with a letter, "
                "contain only [a-zA-Z0-9_]). Skipping registration.",
                tool.name,
            )
            return
        if clean != tool.name:
            logger.warning("Tool name '%s' normalized to '%s'", tool.name, clean)
            tool.name = clean
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def all_tools(self) -> list[ToolDef]:
        return list(self._tools.values())

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def is_consequential(self, name: str) -> bool:
        tool = self._tools.get(name)
        return tool.safety_level == "consequential" if tool else False

    def to_gemini_tools(self, names: list[str] | None = None) -> list[dict]:
        """Convert registered tools to Gemini's function declaration format.

        names: if given, only include tools whose name is in this list
        (order-preserving is not required; lookup is by name). Used to
        hand the voice session a small, curated tool subset instead of
        all 47 — the full set was previously excluded from voice
        entirely because of 1007 config-size errors and latency; a
        small named subset avoids both while still letting Gemini
        actually call real tools during a live conversation instead of
        just narrating that it did.

        Returns a list with a single dict: [{"function_declarations": [...]}]
        Each declaration is a raw dict (NOVA's proven pattern), NOT a
        types.FunctionDeclaration object. This avoids serialization issues
        where the SDK's __init__ validation rejects valid JSON Schema keys
        like "required" or "description" that don't map to Schema fields.

        Gemini's LiveConnectConfig accepts both formats, but raw dicts are
        more predictable and match how google-genai internally serializes them.
        """
        declarations = []
        wanted = set(names) if names is not None else None
        for tool in self._tools.values():
            if wanted is not None and tool.name not in wanted:
                continue
            # Double-check name validity (defensive)
            if not _sanitize_tool_name(tool.name):
                logger.warning("Skipping invalid tool name: '%s'", tool.name)
                continue

            # Convert parameters to Gemini-compatible dict format.
            # NOVA uses UPPERCASE type names ("STRING", "OBJECT", "INTEGER", etc.)
            # which is what the Gemini API expects in the JSON wire format.
            param_dict = _schema_to_gemini_dict(tool.parameters)

            declarations.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": param_dict,
            })

        if not declarations:
            return []

        return [{"function_declarations": declarations}]

    def execute(self, name: str, args: dict) -> str:
        """Run a tool by name with the given arguments.

        Returns a string prefixed with an explicit status tag —
        [TOOL_STATUS: SUCCESS], [TOOL_STATUS: FAILED], or
        [TOOL_STATUS: PARTIAL] — followed by the actual result. This is
        the verification layer: it doesn't stop the model from narrating
        badly, but it puts an honest, mechanically-determined signal in
        front of every result so the model has no ambiguity to exploit
        ("I don't know if it worked" is no longer a possible read of the
        function_response). Never crashes -- errors are returned as
        plain text for the model, tagged FAILED.
        """
        tool = self._tools.get(name)
        if not tool:
            return self._tag(
                "FAILED",
                f"Unknown tool '{name}'. No tool with that name is registered.",
            )
        try:
            result = tool.handler(**args)
        except TypeError as e:
            return self._tag("FAILED", f"Error calling {name}: wrong arguments. {e}")
        except Exception as e:
            return self._tag("FAILED", f"Error in {name}: {type(e).__name__} -- {e}")

        return self._tag(*self._classify(result))

    @staticmethod
    def _tag(status: str, text: str) -> str:
        return f"[TOOL_STATUS: {status}] {text}"

    _FAILURE_MARKERS = (
        "error", "failed", "failure", "not found", "not available",
        "not initialized", "does not exist", "no such", "denied",
        "unauthorized", "unable to", "could not", "invalid ",
        "permission denied", "timed out", "timeout",
    )

    @classmethod
    def _classify(cls, result: Any) -> tuple[str, str]:
        """Determine (status, text) from a raw handler return value.

        Handlers weren't written with SUCCESS/FAILED/PARTIAL in mind —
        most signal failure by convention (a plain string describing
        what went wrong) rather than by raising. Real conventions found
        across the tool files: "Error: ...", "X not found", "X not
        available", "X failed", "Permission denied: ...", etc. — not
        just an "Error:" prefix. Scan for the actual phrasing in use
        rather than assume one convention, or a whole class of real
        failures gets mistagged as SUCCESS just because nothing threw.
        """
        if result is None:
            return "SUCCESS", "Done."
        text = str(result)
        stripped = text.strip()
        if not stripped:
            return "PARTIAL", "(Tool ran but returned no output.)"
        lowered = stripped.lower()
        if any(marker in lowered for marker in cls._FAILURE_MARKERS):
            return "FAILED", text
        return "SUCCESS", text


def _schema_to_gemini_dict(d: dict) -> dict:
    """Convert a JSON Schema dict to Gemini's wire format.

    Gemini expects:
      - "type" as UPPERCASE: "STRING", "OBJECT", "INTEGER", "NUMBER", "BOOLEAN", "ARRAY"
      - "properties" as nested dicts (same format)
      - "required" as a list of strings
      - "description" as a string
      - "items" as nested dict (for arrays)

    This is the format NOVA uses (proven working with Gemini Live).
    """
    if not isinstance(d, dict):
        return d

    result = {}

    # Type conversion: lowercase JSON Schema → UPPERCASE Gemini format
    t = d.get("type")
    if isinstance(t, str):
        result["type"] = t.upper()

    # Properties: recurse
    props = d.get("properties")
    if isinstance(props, dict):
        result["properties"] = {
            pk: _schema_to_gemini_dict(pv) for pk, pv in props.items()
        }

    # Required: pass through as-is (list of strings)
    if "required" in d:
        result["required"] = d["required"]

    # Description: pass through
    if "description" in d:
        result["description"] = d["description"]

    # Items (for ARRAY type): recurse
    items = d.get("items")
    if isinstance(items, dict):
        result["items"] = _schema_to_gemini_dict(items)

    return result


def create_registry(
    memory_store=None,
    knowledge_graph=None,
    scheduler=None,
    world_model=None,
    event_bus=None,
    memory_v2=None,
) -> ToolRegistry:
    """Create and populate the tool registry with all available tools."""
    from tools.memory_tools import register as register_memory
    from tools.system_tools import register as register_system
    from tools.file_tools import register as register_file
    from tools.terminal_tools import register as register_terminal
    from tools.file_manager_tools import register as register_file_manager
    from tools.web_tools import register as register_web
    from tools.dev_tools import register as register_dev
    from tools.vision_tools import register as register_vision

    registry = ToolRegistry()

    register_memory(registry, memory_v2=memory_v2, memory_store=memory_store)
    register_system(registry)
    register_file(registry)
    register_terminal(registry)
    register_file_manager(registry)
    register_web(registry)
    register_dev(registry)
    register_vision(registry)

    # New subsystem tools
    try:
        from tools.kg_tools import register as register_kg
        register_kg(registry, knowledge_graph)
    except Exception as e:
        logger.warning("KG tools not loaded: %s", e)

    try:
        from tools.scheduler_tools import register as register_sched
        register_sched(registry, scheduler)
    except Exception as e:
        logger.warning("Scheduler tools not loaded: %s", e)

    try:
        from tools.world_tools import register as register_world
        register_world(registry, world_model)
    except Exception as e:
        logger.warning("World tools not loaded: %s", e)

    try:
        from tools.screen_tools import register as register_screen
        register_screen(registry)
    except Exception as e:
        logger.warning("Screen tools not loaded: %s", e)

    try:
        from tools.computer_tools import register as register_computer
        register_computer(registry)
    except Exception as e:
        logger.warning("Computer tools not loaded: %s", e)

    try:
        from tools.filesystem_tools import register as register_filesystem
        register_filesystem(registry)
    except Exception as e:
        logger.warning("Filesystem tools not loaded: %s", e)

    try:
        from tools.agent_tools import register as register_agent
        register_agent(registry)
    except Exception as e:
        logger.warning("Agent tools not loaded: %s", e)

    try:
        from tools.browser_tools import register as register_browser
        register_browser(registry)
    except Exception as e:
        logger.warning("Browser tools not loaded: %s", e)

    # Log final tool count (helps diagnose 1007 errors)
    names = registry.tool_names()
    logger.info("Tool registry ready: %d tools loaded", len(names))

    return registry
