"""
monitoring/ -- System and performance monitoring.

Tracks CPU, memory, disk, network, battery, process health,
and VYREN's own internal metrics.
"""

import logging
import os
import platform
import time
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger("vyren.monitoring")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


@dataclass
class SystemSnapshot:
    cpu_percent: float = 0
    memory_percent: float = 0
    memory_used_gb: float = 0
    memory_total_gb: float = 0
    disk_percent: float = 0
    disk_free_gb: float = 0
    battery_percent: float | None = None
    battery_charging: bool | None = None
    hostname: str = ""
    os: str = ""
    uptime_seconds: int = 0


from platform_abstraction import get_disk_root

def get_system_snapshot() -> SystemSnapshot:
    """Take a snapshot of current system state."""
    if not HAS_PSUTIL:
        return SystemSnapshot(os=platform.system(), hostname=platform.node())

    mem = psutil.virtual_memory()
    disk_root = get_disk_root()
    try:
        disk = psutil.disk_usage(disk_root)
        disk_data = {"percent": disk.percent, "free_gb": round(disk.free / (1024**3), 1)}
    except Exception:
        disk_data = {"percent": 0, "free_gb": 0}

    battery = psutil.sensors_battery()
    try:
        uptime = int(time.time() - psutil.boot_time())
    except Exception:
        uptime = 0

    return SystemSnapshot(
        cpu_percent=psutil.cpu_percent(interval=0.3),
        memory_percent=mem.percent,
        memory_used_gb=round(mem.used / (1024**3), 1),
        memory_total_gb=round(mem.total / (1024**3), 1),
        disk_percent=disk_data["percent"],
        disk_free_gb=disk_data["free_gb"],
        battery_percent=battery.percent if battery else None,
        battery_charging=battery.power_plugged if battery else None,
        hostname=platform.node(),
        os=f"{platform.system()} {platform.release()}",
        uptime_seconds=uptime,
    )


def format_snapshot(snapshot: SystemSnapshot) -> str:
    """Format a snapshot as readable text."""
    lines = [
        f"OS: {snapshot.os}",
        f"Hostname: {snapshot.hostname}",
        f"CPU: {snapshot.cpu_percent}%",
        f"RAM: {snapshot.memory_percent}% ({snapshot.memory_used_gb}GB / {snapshot.memory_total_gb}GB)",
        f"Disk: {snapshot.disk_percent}% ({snapshot.disk_free_gb}GB free)",
    ]
    if snapshot.battery_percent is not None:
        status = "charging" if snapshot.battery_charging else "on battery"
        lines.append(f"Battery: {snapshot.battery_percent}% ({status})")
    lines.append(f"Uptime: {snapshot.uptime_seconds}s")
    return "\n".join(lines)