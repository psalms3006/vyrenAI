"""
world_model.py — VYREN's internal model of the user's world.

Builds and maintains a structured representation of:
  - Projects, files, and their relationships
  - Installed applications and their purposes
  - Hardware devices and their status
  - Schedule and recurring patterns
  - Workflows and habits
  - Development environments
  - Connected services and accounts

The world model is updated by:
  - Direct observation (file system scans, process lists)
  - User interactions (things the user tells VYREN)
  - Inference (detecting patterns from repeated behavior)
  - Event bus notifications (file changes, app launches, etc.)

This replaces isolated prompts with a living context that VYREN
reasons over.
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platform_paths import get_vyren_dir

VYREN_DIR = get_vyren_dir()
WORLD_FILE = VYREN_DIR / "world_model.json"


@dataclass
class Project:
    """A project VYREN knows about."""
    name: str
    path: str = ""
    language: str = ""
    framework: str = ""
    description: str = ""
    status: str = "active"  # active, paused, completed, archived
    last_accessed: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class Application:
    """An installed application."""
    name: str
    path: str = ""
    purpose: str = ""
    category: str = ""  # development, communication, productivity, media, etc.
    frequency: str = "occasional"  # frequent, regular, occasional, rare
    last_used: str | None = None


@dataclass
class Device:
    """A hardware device."""
    name: str
    type: str = ""  # laptop, phone, tablet, monitor, headset, etc.
    role: str = ""  # primary, secondary, peripheral
    status: str = "unknown"  # active, idle, offline, unknown
    capabilities: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class Schedule:
    """A recurring schedule item."""
    name: str
    pattern: str = ""  # "daily 9:00", "weekdays 8:30", "weekly monday 10:00"
    description: str = ""
    category: str = ""  # work, meeting, exercise, personal
    importance: float = 0.5
    last_occurred: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Workflow:
    """A repeated pattern of actions."""
    name: str
    steps: list[str] = field(default_factory=list)
    trigger: str = ""  # What starts this workflow
    frequency: str = "occasional"
    context: str = ""  # When/where this typically happens
    success_count: int = 0
    last_executed: str | None = None


@dataclass
class DevEnvironment:
    """A development environment configuration."""
    name: str
    path: str = ""
    language: str = ""
    runtime: str = ""
    package_manager: str = ""
    test_runner: str = ""
    linter: str = ""
    metadata: dict = field(default_factory=dict)


class WorldModel:
    """
    VYREN's internal model of the user's world.

    Usage:
        wm = WorldModel()

        # Add a project
        wm.add_project(Project(name="VYREN", path="/home/user/vyren", language="Python"))

        # Record an observation
        wm.observe("user frequently opens VS Code at 9am on weekdays")

        # Query
        projects = wm.get_active_projects()
        morning_routine = wm.get_workflows_by_context("morning")
    """

    def __init__(self, path: Path = WORLD_FILE):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._projects: dict[str, Project] = {}
        self._applications: dict[str, Application] = {}
        self._devices: dict[str, Device] = {}
        self._schedules: dict[str, Schedule] = {}
        self._workflows: dict[str, Workflow] = {}
        self._dev_environments: dict[str, DevEnvironment] = {}
        self._observations: list[dict] = []
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            with open(self.path, "r") as f:
                data = json.load(f)

            for name, pd in data.get("projects", {}).items():
                self._projects[name] = Project(**{k: v for k, v in pd.items() if k in Project.__dataclass_fields__})
            for name, ad in data.get("applications", {}).items():
                self._applications[name] = Application(**{k: v for k, v in ad.items() if k in Application.__dataclass_fields__})
            for name, dd in data.get("devices", {}).items():
                self._devices[name] = Device(**{k: v for k, v in dd.items() if k in Device.__dataclass_fields__})
            for name, sd in data.get("schedules", {}).items():
                self._schedules[name] = Schedule(**{k: v for k, v in sd.items() if k in Schedule.__dataclass_fields__})
            for name, wd in data.get("workflows", {}).items():
                wf_data = {k: v for k, v in wd.items() if k in Workflow.__dataclass_fields__}
                self._workflows[name] = Workflow(**wf_data)
            for name, ed in data.get("dev_environments", {}).items():
                self._dev_environments[name] = DevEnvironment(**{k: v for k, v in ed.items() if k in DevEnvironment.__dataclass_fields__})
            self._observations = data.get("observations", [])
        except (json.JSONDecodeError, IOError, TypeError):
            pass

    def _save(self):
        data = {
            "projects": {n: p.__dict__ for n, p in self._projects.items()},
            "applications": {n: a.__dict__ for n, a in self._applications.items()},
            "devices": {n: d.__dict__ for n, d in self._devices.items()},
            "schedules": {n: s.__dict__ for n, s in self._schedules.items()},
            "workflows": {n: w.__dict__ for n, w in self._workflows.items()},
            "dev_environments": {n: e.__dict__ for n, e in self._dev_environments.items()},
            "observations": self._observations[-200:],  # Keep last 200
        }
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # --- Projects ---

    def add_project(self, project: Project):
        self._projects[project.name] = project
        self._save()

    def get_project(self, name: str) -> Project | None:
        return self._projects.get(name)

    def get_active_projects(self) -> list[Project]:
        return [p for p in self._projects.values() if p.status == "active"]

    # --- Applications ---

    def add_application(self, app: Application):
        self._applications[app.name] = app
        self._save()

    # --- Devices ---

    def add_device(self, device: Device):
        self._devices[device.name] = device
        self._save()

    def get_device(self, name: str) -> Device | None:
        return self._devices.get(name)

    # --- Schedules ---

    def add_schedule(self, schedule: Schedule):
        self._schedules[schedule.name] = schedule
        self._save()

    # --- Workflows ---

    def add_workflow(self, workflow: Workflow):
        self._workflows[workflow.name] = workflow
        self._save()

    def get_workflows_by_context(self, context: str) -> list[Workflow]:
        """Find workflows matching a context string."""
        ctx_lower = context.lower()
        return [
            w for w in self._workflows.values()
            if ctx_lower in w.context.lower() or ctx_lower in w.trigger.lower()
        ]

    # --- Dev Environments ---

    def add_dev_environment(self, env: DevEnvironment):
        self._dev_environments[env.name] = env
        self._save()

    # --- Observations ---

    def observe(self, observation: str, source: str = "system"):
        """Record an observation about the user's world."""
        self._observations.append({
            "text": observation,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Auto-save every 10 observations
        if len(self._observations) % 10 == 0:
            self._save()

    def ingest_observation(self, observation: Any) -> None:
        """Ingest a structured vision observation into the world model."""
        try:
            text = getattr(observation, "summary", "") or ""
            if not text and hasattr(observation, "__dict__"):
                text = str(observation.__dict__)
            self._observations.append({
                "text": text,
                "source": getattr(observation, "source", "vision"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            if len(self._observations) % 10 == 0:
                self._save()
        except Exception:
            pass

    # --- Context Building ---

    def to_context_string(self) -> str:
        """Build a context summary for the system prompt."""
        lines = []

        if self._projects:
            lines.append("Projects:")
            for p in self.get_active_projects():
                lang = f" ({p.language})" if p.language else ""
                desc = f" — {p.description}" if p.description else ""
                lines.append(f"  - {p.name}{lang}{desc}")

        if self._schedules:
            lines.append("Schedule:")
            for s in self._schedules.values():
                lines.append(f"  - {s.name}: {s.pattern} [{s.category}]")

        if self._devices:
            lines.append("Devices:")
            for d in self._devices.values():
                status = f" ({d.status})" if d.status != "unknown" else ""
                lines.append(f"  - {d.name} [{d.type}]{status}")

        if self._observations:
            lines.append("Observations:")
            for obs in self._observations[-10:]:
                text = obs.get("text", "") if isinstance(obs, dict) else str(obs)
                lines.append(f"  - {text}")

        return "\n".join(lines) if lines else ""

    @property
    def stats(self) -> dict:
        return {
            "projects": len(self._projects),
            "applications": len(self._applications),
            "devices": len(self._devices),
            "schedules": len(self._schedules),
            "workflows": len(self._workflows),
            "dev_environments": len(self._dev_environments),
            "observations": len(self._observations),
        }