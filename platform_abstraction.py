"""
platform_abstraction.py -- Cross-platform environment detection and OS abstractions.

This is the single source of truth for platform-specific behavior in VYREN.
Other modules should import from here instead of checking `sys.platform` or
hardcoding paths like ``C:\\`` or ``~/.vyren`` directly.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("vyren.platform")


class Platform:
    """Detected host platform."""

    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    ANDROID = "android"
    UNKNOWN = "unknown"


class VYRENEnvironment:
    """Resolved VYREN environment for the current host."""

    def __init__(self) -> None:
        self.platform = _detect_platform()
        self.home = Path.home()
        self.config_dir = _get_config_dir(self.platform, self.home)
        self.data_dir = _get_data_dir(self.platform, self.home)
        self.cache_dir = _get_cache_dir(self.platform, self.home)
        self.runtime_dir = _get_runtime_dir(self.platform, self.home)
        self.disk_root = _get_disk_root(self.platform)
        self.default_shell = _get_default_shell(self.platform)
        self.supports_autostart = _supports_autostart(self.platform)
        self.supports_system_tray = _supports_system_tray(self.platform)

    def ensure_directories(self) -> None:
        """Create platform directories if they do not exist."""
        for directory in (self.config_dir, self.data_dir, self.cache_dir, self.runtime_dir):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                logger.debug("Platform directory creation skipped for %s: %s", directory, exc)

    def path_for(self, name: str) -> Path:
        """Resolve a well-known VYREN data path in a platform-safe way."""
        mapping = {
            "audit": self.data_dir / "audit.log",
            "notices": self.data_dir / "notices.json",
            "memory": self.data_dir / "memory.json",
            "memory_working": self.data_dir / "memory_working.json",
            "memory_episodic": self.data_dir / "memory_episodic.json",
            "memory_semantic": self.data_dir / "memory_semantic.json",
            "memory_procedural": self.data_dir / "memory_procedural.json",
            "memory_preference": self.data_dir / "memory_preference.json",
            "memory_project": self.data_dir / "memory_project.json",
            "learning": self.data_dir / "learning" / "lessons.json",
            "reflections": self.data_dir / "reflections.json",
            "plans": self.data_dir / "plans",
            "checkpoints": self.data_dir / "checkpoints",
            "jobs": self.data_dir / "jobs.json",
            "security": self.data_dir / "security",
            "greeting_history": self.data_dir / "greeting_history.json",
            "offline_queue": self.data_dir / "offline_task_queue.json",
            "screenshots": self.cache_dir / "screenshots",
            "generated": self.cache_dir / "generated",
        }
        return mapping.get(name, self.data_dir / name)


_ENV: Optional[VYRENEnvironment] = None


def get_env() -> VYRENEnvironment:
    """Return the cached environment, creating it once per process."""
    global _ENV
    if _ENV is None:
        _ENV = VYRENEnvironment()
        _ENV.ensure_directories()
    return _ENV


def reset_env() -> None:
    """Reset cached environment. Mainly useful for tests."""
    global _ENV
    _ENV = None


def _detect_platform() -> str:
    raw = sys.platform.lower()
    if raw == "win32" or raw == "cygwin":
        return Platform.WINDOWS
    if raw == "darwin":
        return Platform.MACOS
    if raw == "linux" or raw == "linux2":
        if _looks_like_android():
            return Platform.ANDROID
        return Platform.LINUX
    if raw.startswith("aix") or raw.startswith("freebsd") or raw.startswith("openbsd"):
        return Platform.UNKNOWN
    return Platform.UNKNOWN


def _looks_like_android() -> bool:
    try:
        return (
            os.path.isdir("/system/app")
            or os.path.isdir("/system/priv-app")
            or "Android" in platform.version()
        )
    except Exception:
        return False


def _get_config_dir(platform_name: str, home: Path) -> Path:
    if platform_name == Platform.WINDOWS:
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "vyren"
    if platform_name == Platform.MACOS:
        return home / "Library" / "Application Support" / "vyren"
    if platform_name == Platform.ANDROID:
        base = Path(os.environ.get("EXTERNAL_STORAGE", home))
        return base / "Android" / "data" / "vyren" / "config"
    return Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "vyren"


def _get_data_dir(platform_name: str, home: Path) -> Path:
    if platform_name == Platform.WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "vyren"
    if platform_name == Platform.MACOS:
        return home / "Library" / "Application Support" / "vyren"
    if platform_name == Platform.ANDROID:
        base = Path(os.environ.get("EXTERNAL_STORAGE", home))
        return base / "Android" / "data" / "vyren"
    return home / ".local" / "share" / "vyren"


def _get_cache_dir(platform_name: str, home: Path) -> Path:
    if platform_name == Platform.WINDOWS:
        return Path(os.environ.get("TEMP", home / "AppData" / "Local" / "Temp")) / "vyren"
    if platform_name == Platform.MACOS:
        return home / "Library" / "Caches" / "vyren"
    if platform_name == Platform.ANDROID:
        base = Path(os.environ.get("EXTERNAL_STORAGE", home))
        return base / "Android" / "data" / "vyren" / "cache"
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    return Path(xdg_cache) / "vyren" if xdg_cache else home / ".cache" / "vyren"


def _get_runtime_dir(platform_name: str, home: Path) -> Path:
    if platform_name == Platform.WINDOWS:
        return Path(os.environ.get("TEMP", home / "AppData" / "Local" / "Temp")) / "vyren"
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        return Path(xdg_runtime) / "vyren"
    return home / ".local" / "run" / "vyren"


def _get_disk_root(platform_name: str) -> str:
    return "C:\\" if platform_name == Platform.WINDOWS else "/"


def _get_default_shell(platform_name: str) -> Optional[str]:
    if platform_name == Platform.WINDOWS:
        return os.environ.get("COMSPEC") or shutil.which("cmd.exe") or "cmd.exe"
    shell = shutil.which("bash") or shutil.which("sh")
    return shell


def _supports_autostart(platform_name: str) -> bool:
    return platform_name in {Platform.WINDOWS, Platform.LINUX, Platform.MACOS}


def _supports_system_tray(platform_name: str) -> bool:
    return platform_name in {Platform.WINDOWS, Platform.LINUX, Platform.MACOS}


def get_platform() -> str:
    return get_env().platform


def get_data_dir() -> Path:
    return get_env().data_dir


def get_config_dir() -> Path:
    return get_env().config_dir


def get_cache_dir() -> Path:
    return get_env().cache_dir


def get_runtime_dir() -> Path:
    return get_env().runtime_dir


def get_disk_root() -> str:
    return get_env().disk_root


def get_default_shell() -> Optional[str]:
    return get_env().default_shell


def is_windows() -> bool:
    return get_env().platform == Platform.WINDOWS


def is_linux() -> bool:
    return get_env().platform == Platform.LINUX


def is_macos() -> bool:
    return get_env().platform == Platform.MACOS


def is_android() -> bool:
    return get_env().platform == Platform.ANDROID


def is_desktop() -> bool:
    return get_env().platform in {Platform.WINDOWS, Platform.LINUX, Platform.MACOS}
