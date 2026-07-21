"""tools/world_tools.py -- World model tools for VYREN.

Lets VYREN track your projects, devices, schedules, workflows,
and development environments."""

import json

from tools import ToolDef, ToolRegistry


def register(registry: ToolRegistry, world_model=None):
    """Register all world model tools."""

    def add_project(name: str, path: str = "", language: str = "",
                   description: str = "") -> str:
        """Register a project in VYREN's world model."""
        if world_model is None:
            return "Error: World model not initialized."
        from world_model import Project
        project = Project(
            name=name, path=path, language=language,
            description=description, status="active",
        )
        world_model.add_project(project)
        return f"Project '{name}' registered." + (f" Path: {path}" if path else "")

    def get_projects() -> str:
        """List all active projects VYREN knows about."""
        if world_model is None:
            return "Error: World model not initialized."
        projects = world_model.get_active_projects()
        if not projects:
            return "No active projects registered. Use add_project to register one."
        lines = [f"Active projects ({len(projects)}):"]
        for p in projects:
            lang = f" [{p.language}]" if p.language else ""
            desc = f" - {p.description}" if p.description else ""
            path = f" ({p.path})" if p.path else ""
            lines.append(f"  {p.name}{lang}{desc}{path}")
        return "\n".join(lines)

    def add_device(name: str, device_type: str = "", role: str = "",
                   capabilities: str = "") -> str:
        """Register a device (laptop, phone, monitor, etc.)."""
        if world_model is None:
            return "Error: World model not initialized."
        from world_model import Device
        caps = capabilities.split(",") if capabilities else []
        device = Device(
            name=name, type=device_type, role=role,
            capabilities=[c.strip() for c in caps],
            status="active",
        )
        world_model.add_device(device)
        return f"Device '{name}' registered [{device_type}]."

    def add_schedule(name: str, pattern: str = "", category: str = "",
                    description: str = "") -> str:
        """Register a recurring schedule item."""
        if world_model is None:
            return "Error: World model not initialized."
        from world_model import Schedule
        sched = Schedule(
            name=name, pattern=pattern, category=category,
            description=description,
        )
        world_model.add_schedule(sched)
        return f"Schedule '{name}' registered: {pattern} [{category}]."

    def observe_world(observation: str) -> str:
        """Record an observation about the user's world for future reference."""
        if world_model is None:
            return "Error: World model not initialized."
        world_model.observe(observation)
        return f"Observation recorded: {observation[:80]}"

    def world_status() -> str:
        """Get an overview of VYREN's model of your world."""
        if world_model is None:
            return "Error: World model not initialized."
        stats = world_model.stats
        lines = ["VYREN's World Model:"]
        lines.append(f"  Projects: {stats['projects']}")
        lines.append(f"  Applications: {stats['applications']}")
        lines.append(f"  Devices: {stats['devices']}")
        lines.append(f"  Schedules: {stats['schedules']}")
        lines.append(f"  Workflows: {stats['workflows']}")
        lines.append(f"  Dev Environments: {stats['dev_environments']}")
        lines.append(f"  Observations: {stats['observations']}")
        ctx = world_model.to_context_string()
        if ctx:
            lines.append(f"\n{ctx}")
        return "\n".join(lines)

    registry.register(ToolDef(
        name="add_project",
        description=(
            "Register a project in VYREN's world model. Helps VYREN understand "
            "what you're working on, where the code lives, and what language it uses."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "path": {"type": "string", "description": "Path to the project directory"},
                "language": {"type": "string", "description": "Primary language (Python, JavaScript, etc.)"},
                "description": {"type": "string", "description": "What the project does"},
            },
            "required": ["name"],
        },
        handler=add_project,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="get_projects",
        description=(
            "List all active projects VYREN knows about from the world model."
        ),
        parameters={"type": "object", "properties": {}},
        handler=get_projects,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="add_device",
        description=(
            "Register a device (laptop, phone, monitor, headset, etc.) "
            "in VYREN's world model."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Device name"},
                "device_type": {"type": "string", "description": "Type: laptop, phone, tablet, monitor, headset, etc."},
                "role": {"type": "string", "description": "Role: primary, secondary, peripheral"},
                "capabilities": {"type": "string", "description": "Comma-separated capabilities"},
            },
            "required": ["name"],
        },
        handler=add_device,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="add_schedule",
        description=(
            "Register a recurring schedule (meeting, exercise, standup, etc.) "
            "in VYREN's world model so it can provide context-aware assistance."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Schedule item name"},
                "pattern": {"type": "string", "description": "Pattern like 'daily 9:00', 'weekdays 8:30', 'weekly monday 10:00'"},
                "category": {"type": "string", "description": "Category: work, meeting, exercise, personal"},
                "description": {"type": "string", "description": "Description of this schedule item"},
            },
            "required": ["name"],
        },
        handler=add_schedule,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="observe_world",
        description=(
            "Record an observation about the user's world. Use this to note patterns, "
            "preferences, or facts that don't fit in regular memory but provide useful context."
        ),
        parameters={
            "type": "object",
            "properties": {
                "observation": {"type": "string", "description": "The observation to record"},
            },
            "required": ["observation"],
        },
        handler=observe_world,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="world_status",
        description=(
            "Get an overview of everything VYREN knows about your world: "
            "projects, devices, schedules, workflows, observations."
        ),
        parameters={"type": "object", "properties": {}},
        handler=world_status,
        safety_level="safe",
    ))
