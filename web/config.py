"""
config.py — Loads and provides access to VYREN's configuration.

All tuneable values live in config.yaml. This module loads it once and
makes it available to every other module. Change behavior by editing
the YAML file, never by changing code.
"""

import os
from pathlib import Path
from typing import Any

import yaml


_config: dict | None = None
_config_path: Path | None = None


def _find_config() -> Path:
    """Locate config.yaml, searching from the script's directory upward."""
    # First: explicit env override
    env_path = os.environ.get("VYREN_CONFIG")
    if env_path:
        return Path(env_path)

    # Second: same directory as this file
    here = Path(__file__).parent
    candidate = here / "config.yaml"
    if candidate.exists():
        return candidate

    raise FileNotFoundError(
        "config.yaml not found. Copy config.yaml from the project if it's missing."
    )


def load() -> dict:
    """Load config.yaml and cache it. Call this once at startup."""
    global _config, _config_path
    _config_path = _find_config()
    with open(_config_path, "r") as f:
        _config = yaml.safe_load(f)
    return _config


def get(key: str, default: Any = None) -> Any:
    """Get a config value by dot-separated key (e.g. 'model.name')."""
    if _config is None:
        load()
    keys = key.split(".")
    val = _config
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return default
    return val


def get_consequential_tools() -> list[str]:
    """Return the list of tool names that require confirmation."""
    return get("safety.consequential_tools", [])


def is_consequential(tool_name: str) -> bool:
    """Check if a tool requires confirmation."""
    return tool_name in get_consequential_tools()