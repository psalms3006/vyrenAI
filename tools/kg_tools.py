"""tools/kg_tools.py -- Knowledge graph tools for VYREN.

Lets VYREN create entities, link them, search the graph,
and find relationships between people, projects, concepts, etc.
"""

from tools import ToolDef, ToolRegistry


def register(registry: ToolRegistry, kg=None):
    """Register all knowledge graph tools."""

    def add_entity(name: str, entity_type: str, properties: str = "",
                   importance: float = 0.5) -> str:
        """Add an entity (person, project, concept, etc.) to the knowledge graph."""
        if kg is None:
            return "Error: Knowledge graph not initialized."
        try:
            from knowledge_graph import EntityType
            et = EntityType(entity_type)
        except ValueError:
            valid = [e.value for e in __import__("knowledge_graph", fromlist=["EntityType"]).EntityType]
            return f"Invalid type '{entity_type}'. Valid types: {', '.join(valid)}"

        props = {}
        if properties:
            import json
            try:
                props = json.loads(properties)
            except json.JSONDecodeError:
                props = {"description": properties}

        eid = kg.add_entity(et, name, properties=props, importance=importance)
        return f"Entity '{name}' created (id: {eid}, type: {entity_type})."

    def add_relation(source_name: str, target_name: str, relation: str) -> str:
        """Create a relationship between two entities."""
        if kg is None:
            return "Error: Knowledge graph not initialized."
        src = kg.find_by_name(source_name)
        tgt = kg.find_by_name(target_name)
        if not src:
            return f"Entity '{source_name}' not found. Create it first with add_entity."
        if not tgt:
            return f"Entity '{target_name}' not found. Create it first with add_entity."
        try:
            from knowledge_graph import RelationType
            rt = RelationType(relation)
        except ValueError:
            return f"Invalid relation '{relation}'. Use standard relations like 'works_with', 'part_of', 'uses', 'interested_in', 'depends_on'."

        rid = kg.add_relation(src.id, tgt.id, rt)
        if rid:
            return f"Relation created: {source_name} --[{relation}]--> {target_name}"
        return "Relation already exists."

    def search_knowledge(query: str) -> str:
        """Search the knowledge graph for entities matching a query."""
        if kg is None:
            return "Error: Knowledge graph not initialized."
        results = kg.search(query)
        if not results:
            return f"No entities found matching '{query}'."
        lines = [f"Found {len(results)} entity(ies):"]
        for e in results:
            neighbors = kg.get_neighbors(e.id)[:5]
            n_str = ", ".join(n.name for n in neighbors) if neighbors else "none"
            lines.append(f"  [{e.type.value}] {e.name} (importance: {e.importance}, connected to: {n_str})")
        return "\n".join(lines)

    def get_entity_info(name: str) -> str:
        """Get detailed info about an entity including its relationships."""
        if kg is None:
            return "Error: Knowledge graph not initialized."
        entity = kg.find_by_name(name)
        if not entity:
            return f"Entity '{name}' not found."
        lines = [f"Entity: {entity.name}", f"Type: {entity.type.value}",
                 f"Importance: {entity.importance}", f"Created: {entity.created}"]
        if entity.properties:
            lines.append("Properties:")
            for k, v in entity.properties.items():
                lines.append(f"  {k}: {v}")
        neighbors = kg.get_neighbors(entity.id, direction="both")
        if neighbors:
            lines.append(f"Connections ({len(neighbors)}):")
            for n in neighbors:
                lines.append(f"  - {n.name} [{n.type.value}]")
        return "\n".join(lines)

    def graph_stats() -> str:
        """Get statistics about the knowledge graph."""
        if kg is None:
            return "Error: Knowledge graph not initialized."
        stats = kg.get_stats()
        return (f"Knowledge Graph: {stats['entities']} entities, "
                f"{stats['edges']} edges\n"
                f"Types: {stats['types']}")

    registry.register(ToolDef(
        name="add_entity",
        description=(
            "Add an entity to the knowledge graph. Entities represent people, projects, "
            "concepts, files, tasks, tools, websites, etc. Each has a type, name, and optional properties."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the entity"},
                "entity_type": {
                    "type": "string",
                    "description": "Type: person, project, file, concept, task, meeting, device, location, research, idea, tool, website, application, organization, event"
                },
                "properties": {"type": "string", "description": "Optional JSON string of additional properties"},
                "importance": {"type": "number", "description": "Importance 0-1 (default 0.5)"},
            },
            "required": ["name", "entity_type"],
        },
        handler=add_entity,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="add_relation",
        description=(
            "Create a relationship between two entities in the knowledge graph. "
            "Both entities must already exist (create with add_entity first). "
            "Relations: works_with, part_of, contains, depends_on, related_to, uses, produces, interested_in, located_in, belongs_to, manages, reports_to"
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_name": {"type": "string", "description": "Name of the source entity"},
                "target_name": {"type": "string", "description": "Name of the target entity"},
                "relation": {"type": "string", "description": "The relationship type"},
            },
            "required": ["source_name", "target_name", "relation"],
        },
        handler=add_relation,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="search_knowledge",
        description=(
            "Search the knowledge graph for entities matching a query. "
            "Searches entity names and properties. Returns matching entities with their relationships."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
        handler=search_knowledge,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="get_entity_info",
        description=(
            "Get detailed information about a specific entity in the knowledge graph, "
            "including all its properties and relationships."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the entity to look up"},
            },
            "required": ["name"],
        },
        handler=get_entity_info,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="graph_stats",
        description=(
            "Get statistics about the knowledge graph: entity count, edge count, type breakdown."
        ),
        parameters={"type": "object", "properties": {}},
        handler=graph_stats,
        safety_level="safe",
    ))
