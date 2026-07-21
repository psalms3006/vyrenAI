"""tools/memory_tools.py -- Memory tools for VYREN.

These let VYREN remember, recall, search, and delete facts about you
across restarts. All are safe (read/write to your own memory store).
"""

from tools import ToolDef, ToolRegistry


def register(registry: ToolRegistry, memory_store):
    """Register all memory tools."""

    def remember(key: str, value: str) -> str:
        """Save a fact to long-term memory."""
        if memory_store is None:
            return "Error: Memory store not initialized."
        # Clean up the key for usability
        key = key.strip().lower().replace(" ", "_")
        return memory_store.add(key, value)

    def recall(key: str) -> str:
        """Look up a specific fact by its key."""
        if memory_store is None:
            return "Error: Memory store not initialized."
        fact = memory_store.get(key.strip().lower().replace(" ", "_"))
        if fact:
            return fact
        return f"No fact found with key '{key}'. Use search_memory to look for it."

    def search_memory(query: str) -> str:
        """Search memory for any facts matching a query."""
        if memory_store is None:
            return "Error: Memory store not initialized."
        results = memory_store.search(query)
        if not results:
            return f"No memories found matching '{query}'."
        lines = []
        for r in results:
            lines.append(f"- {r['key']}: {r['value']}")
        return "\n".join(lines)

    def list_memory() -> str:
        """List all stored memories."""
        if memory_store is None:
            return "Error: Memory store not initialized."
        facts = memory_store.list_all()
        if not facts:
            return "Memory is empty. Nothing stored yet."
        lines = [f"Memory has {len(facts)} entries:"]
        for f in facts:
            lines.append(f"- {f['key']}: {f['value']}")
        return "\n".join(lines)

    def delete_memory(key: str) -> str:
        """Delete a specific fact from memory."""
        if memory_store is None:
            return "Error: Memory store not initialized."
        key = key.strip().lower().replace(" ", "_")
        if memory_store.delete(key):
            return f"Deleted: {key}"
        return f"No fact found with key '{key}'."

    registry.register(ToolDef(
        name="remember",
        description=(
            "Save a fact about the user to long-term memory so it persists "
            "across restarts. Use short, descriptive keys (e.g. 'location', "
            "'preferred_browser', 'project_name')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Short, unique label for this fact",
                },
                "value": {
                    "type": "string",
                    "description": "The fact to remember, written as a clear statement",
                },
            },
            "required": ["key", "value"],
        },
        handler=remember,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="recall",
        description=(
            "Look up a specific fact from memory by its exact key. "
            "If you're not sure of the key, use search_memory instead."
        ),
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The exact key of the fact to look up",
                },
            },
            "required": ["key"],
        },
        handler=recall,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="search_memory",
        description=(
            "Search through all stored memories for anything matching a query. "
            "Use this when you need to find what you know about a topic."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in memory",
                },
            },
            "required": ["query"],
        },
        handler=search_memory,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="list_memory",
        description=(
            "List all facts currently stored in memory. "
            "Use this to see everything VYREN knows about the user."
        ),
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=list_memory,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="delete_memory",
        description=(
            "Delete a specific fact from memory. The fact is permanently removed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key of the fact to delete",
                },
            },
            "required": ["key"],
        },
        handler=delete_memory,
        safety_level="safe",
    ))