"""
environment.py -- Execution environment adaptation.

Detects host capabilities and exposes capability flags so the rest of
VYREN can degrade safely on platforms like Android, headless servers,
or restricted environments.

This keeps platform checks out of business logic: subsystems query
capabilities instead of checking ``sys.platform`` themselves.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Callable

from platform_abstraction import get_env

logger = logging.getLogger("vyren.environment")


@dataclass
class HostCapabilities:
    platform: str = "unknown"
    is_desktop: bool = False
    is_android: bool = False
    is_windows: bool = False
    is_linux: bool = False
    is_macos: bool = False
    has_gui: bool = False
    has_clipboard: bool = False
    has_system_tray: bool = False
    has_autostart: bool = False
    has_screen_capture: bool = False
    has_battery: bool = False
    has_terminal_emulator: bool = False
    can_open_apps: bool = False
    can_run_background_service: bool = False
    notes: list[str] = field(default_factory=list)


def _probe_capabilities() -> HostCapabilities:
    env = get_env()
    caps = HostCapabilities(
        platform=env.platform,
        is_desktop=env.supports_system_tray,
        is_android=env.platform == env.platform if False else env.platform == "android",
        is_windows=env.platform == "windows",
        is_linux=env.platform == "linux",
        is_macos=env.platform == "macos",
        has_gui=_has_gui(env.platform),
        has_clipboard=_has_clipboard(env.platform),
        has_system_tray=env.supports_system_tray,
        has_autostart=env.supports_autostart,
        has_screen_capture=_has_screen_capture(env.platform),
        has_battery=_has_battery(),
        has_terminal_emulator=bool(env.default_shell),
        can_open_apps=_can_open_apps(env.platform),
        can_run_background_service=_can_run_background_service(env.platform),
    )
    return caps


def _has_gui(platform_name: str) -> bool:
    if platform_name in {"linux", "windows", "macos"}:
        display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        if platform_name == "linux" and not display:
            return False
        return True
    return False


def _has_clipboard(platform_name: str) -> bool:
    return platform_name in {"windows", "linux", "macos"}


def _has_screen_capture(platform_name: str) -> bool:
    if platform_name == "android":
        return False
    return True


def _has_battery() -> bool:
    try:
        import psutil
        return psutil.sensors_battery() is not None
    except Exception:
        return False


def _can_open_apps(platform_name: str) -> bool:
    return platform_name in {"windows", "linux", "macos"}


def _can_run_background_service(platform_name: str) -> bool:
    return platform_name in {"windows", "linux", "macos"}


_capabilities: HostCapabilities | None = None


def get_capabilities() -> HostCapabilities:
    global _capabilities
    if _capabilities is None:
        _capabilities = _probe_capabilities()
        logger.debug("Host capabilities: %s", _capabilities)
    return _capabilities


def reset_capabilities() -> None:
    global _capabilities
    _capabilities = None


def require(*names: str) -> None:
    """Raise if any required capability is missing."""
    caps = get_capabilities()
    missing = [name for name in names if not getattr(caps, name)]
    if missing:
        raise EnvironmentError(
            f"Missing host capabilities: {', '.join(missing)} "
            f"(platform={caps.platform})"
        )
