"""tools/memory_tools.py -- Memory tools for VYREN.

These let VYREN remember, recall, search, and delete facts about you
across restarts. All are safe (read/write to your own memory store).

Backed by memory_v2.MemoryManager (SEMANTIC layer) so explicit
"remember this" facts get the same importance scoring, decay, and
automatic build_context() surfacing that episodic auto-memorize
already gets — instead of living in a separate store that only
resurfaces if the model happens to call recall/search_memory itself.
"""

from tools import ToolDef, ToolRegistry

# Facts saved explicitly by the user/model live in SEMANTIC. Importance
# is set above the 0.3 build_context() threshold so they're always in
# ambient context, and above the 0.5 auto-memorize default so an
# explicit "remember X" outranks an inferred episodic snippet.
EXPLICIT_FACT_IMPORTANCE = 0.8


def register(registry: ToolRegistry, memory_v2):
    """Register all memory tools against the MemoryManager (v2)."""
    from memory_v2 import MemoryLayer

    def remember(key: str, value: str) -> str:
        """Save a fact to long-term memory."""
        if memory_v2 is None:
            return "Error: Memory store not initialized."
        key = key.strip().lower().replace(" ", "_")
        memory_v2.remember(
            key=key,
            value=value,
            layer=MemoryLayer.SEMANTIC,
            importance=EXPLICIT_FACT_IMPORTANCE,
            source="remember_tool",
        )
        return f"Remembered: {key}"

    def recall(key: str) -> str:
        """Look up a specific fact by its key."""
        if memory_v2 is None:
            return "Error: Memory store not initialized."
        fact = memory_v2.recall(key.strip().lower().replace(" ", "_"))
        if fact:
            return fact
        return f"No fact found with key '{key}'. Use search_memory to look for it."

    def search_memory(query: str) -> str:
        """Search memory for any facts matching a query."""
        if memory_v2 is None:
            return "Error: Memory store not initialized."
        results = memory_v2.search(query)
        if not results:
            return f"No memories found matching '{query}'."
        lines = []
        for r in results:
            lines.append(f"- {r['key']}: {r['value']}")
        return "\n".join(lines)

    def list_memory() -> str:
        """List all stored memories."""
        if memory_v2 is None:
            return "Error: Memory store not initialized."
        facts = memory_v2.list_all()
        if not facts:
            return "Memory is empty. Nothing stored yet."
        lines = [f"Memory has {len(facts)} entries:"]
        for f in facts:
            lines.append(f"- {f['key']} [{f['layer']}]: {f['value']}")
        return "\n".join(lines)

    def delete_memory(key: str) -> str:
        """Delete a specific fact from memory."""
        if memory_v2 is None:
            return "Error: Memory store not initialized."
        key = key.strip().lower().replace(" ", "_")
        if memory_v2.delete(key):
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