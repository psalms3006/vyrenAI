"""
tools/__init__.py -- Tool registry and tool loading.

A tool is a named capability with a description, typed parameters,
a handler function, and a safety level. The registry is the single
place tools are registered and looked up.

Adding a new capability = write one tool file + register it here.
Never edit main.py or the core loop to add a tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from google.genai import types


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

    def to_gemini_tools(self) -> list[types.Tool]:
        """Convert all registered tools to Gemini's function declaration format."""
        declarations = []
        for tool in self._tools.values():
            # Convert our JSON Schema to Gemini's Schema type
            schema_dict = tool.parameters
            declarations.append(
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters=_dict_to_schema(schema_dict),
                )
            )
        return [types.Tool(function_declarations=declarations)]

    def execute(self, name: str, args: dict) -> str:
        """Run a tool by name with the given arguments.
        Returns the result as a string, or an error message.
        Never crashes — errors are returned as plain text for the model."""
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Unknown tool '{name}'. No tool with that name is registered."
        try:
            result = tool.handler(**args)
            return str(result) if result is not None else "Done."
        except TypeError as e:
            return f"Error calling {name}: wrong arguments. {e}"
        except Exception as e:
            return f"Error in {name}: {type(e).__name__} — {e}"


def _dict_to_schema(d: dict) -> types.Schema:
    """Recursively convert a JSON Schema dict to a Gemini Schema object."""
    if not isinstance(d, dict):
        return d
    kwargs = {}
    for k, v in d.items():
        if k.upper() == "TYPE" and isinstance(v, str):
            kwargs["type"] = getattr(types.Type, v.upper(), types.Type.STRING)
        elif k == "properties" and isinstance(v, dict):
            kwargs["properties"] = {pk: _dict_to_schema(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            kwargs["items"] = _dict_to_schema(v)
        else:
            kwargs[k] = v
    return types.Schema(**kwargs)


def create_registry(memory_store=None) -> ToolRegistry:
    """Create and populate the tool registry with all available tools."""
    from tools.memory_tools import register as register_memory
    from tools.system_tools import register as register_system
    from tools.file_tools import register as register_file
    from tools.web_tools import register as register_web
    from tools.dev_tools import register as register_dev
    from tools.vision_tools import register as register_vision

    registry = ToolRegistry()

    register_memory(registry, memory_store)
    register_system(registry)
    register_file(registry)
    register_web(registry)
    register_dev(registry)
    register_vision(registry)

    return registry