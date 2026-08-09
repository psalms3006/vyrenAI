"""
platform_paths.py -- Shared path helpers derived from the platform environment.

This module centralizes all VYREN directory access for subsystems that
currently hardcode ``~/.vyren`` paths. It is intentionally lightweight so
it can be imported safely across the codebase without changing the
platform detection lifecycle.
"""

from __future__ import annotations

from pathlib import Path

from platform_abstraction import (
    get_env,
    get_platform,
    Platform,
    get_desktop_dir,
    get_documents_dir,
    get_downloads_dir,
    get_pictures_dir,
    get_music_dir,
    get_videos_dir,
    _resolve_system_dir,
    shutdown_system,
    restart_system,
    sleep_system,
    set_system_volume,
)


def get_vyren_dir() -> Path:
    """Return the platform-aware VYREN data directory."""
    return get_env().data_dir


def get_audit_log_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else get_env().path_for("audit")


def get_notices_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else get_env().path_for("notices")


def get_memory_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else get_env().path_for("memory")


def get_jobs_path() -> Path:
    return get_env().path_for("jobs")


def get_security_dir() -> Path:
    return get_env().path_for("security")


def get_checkpoints_dir() -> Path:
    return get_env().path_for("checkpoints")


def get_plans_dir() -> Path:
    return get_env().path_for("plans")


def get_reflections_path() -> Path:
    return get_env().path_for("reflections")


def get_learning_dir() -> Path:
    return get_env().path_for("learning").parent


def get_greeting_history_path() -> Path:
    return get_env().path_for("greeting_history")


def get_offline_queue_path() -> Path:
    return get_env().path_for("offline_queue")


def get_screenshot_dir() -> Path:
    return get_env().path_for("screenshots")


def get_generated_dir() -> Path:
    return get_env().path_for("generated")


def get_disk_root() -> str:
    return get_env().disk_root
