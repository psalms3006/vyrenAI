"""tools/system_tools.py -- System information and control tools.

Read-only system info tools are safe. Any tool that changes system state
(shutdown, restart, etc.) is marked consequential and requires confirmation.
"""

import platform
import psutil
import shutil

from tools import ToolDef, ToolRegistry


def register(registry: ToolRegistry):

    def get_system_info() -> str:
        """Get current system status: OS, CPU, RAM, disk, battery."""
        lines = []
        # OS
        lines.append(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")
        lines.append(f"Hostname: {platform.node()}")

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.5)
        lines.append(f"CPU: {cpu_percent}% used")
        lines.append(f"CPU cores: {psutil.cpu_count(logical=True)} logical, "
                     f"{psutil.cpu_count(logical=False)} physical")

        # RAM
        mem = psutil.virtual_memory()
        lines.append(f"RAM: {mem.percent}% used ({mem.used // (1024**3)}GB / "
                     f"{mem.total // (1024**3)}GB)")

        # Disk
        disk = psutil.disk_usage("/")
        lines.append(f"Disk: {disk.percent}% used ({disk.free // (1024**3)}GB free of "
                     f"{disk.total // (1024**3)}GB)")

        # Battery (may not exist on desktops)
        battery = psutil.sensors_battery()
        if battery:
            status = "charging" if battery.power_plugged else "on battery"
            lines.append(f"Battery: {battery.percent}% ({status})")
        else:
            lines.append("Battery: not detected (desktop or no battery info)")

        # Uptime
        uptime_seconds = int(psutil.boot_time())
        lines.append(f"Uptime: {uptime_seconds}s since boot")

        return "\n".join(lines)

    def list_processes() -> str:
        """List the top processes by CPU and memory usage."""
        procs = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort by CPU
        procs.sort(key=lambda p: p.get("cpu_percent", 0) or 0, reverse=True)
        top = procs[:15]

        lines = [f"{'PID':>6}  {'CPU%':>6}  {'MEM%':>6}  {'NAME'}"]
        lines.append("-" * 50)
        for p in top:
            cpu = p.get("cpu_percent", 0) or 0
            mem = p.get("memory_percent", 0) or 0
            name = p.get("name", "?")[:30]
            lines.append(f"{p['pid']:>6}  {cpu:>5.1f}%  {mem:>5.1f}%  {name}")

        return "\n".join(lines)

    def shutdown_system() -> str:
        """Shut down the computer. REQUIRES CONFIRMATION."""
        return "SHUTDOWN_REQUESTED"

    def restart_system() -> str:
        """Restart the computer. REQUIRES CONFIRMATION."""
        return "RESTART_REQUESTED"

    registry.register(ToolDef(
        name="get_system_info",
        description=(
            "Get current system status: operating system, CPU usage, RAM, "
            "disk space, battery level, and uptime. Read-only, always safe."
        ),
        parameters={"type": "object", "properties": {}},
        handler=get_system_info,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="list_processes",
        description=(
            "List the top running processes sorted by CPU usage. "
            "Shows PID, CPU percent, memory percent, and process name."
        ),
        parameters={"type": "object", "properties": {}},
        handler=list_processes,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="shutdown_system",
        description=(
            "Shut down the computer. This is a consequential action "
            "that requires explicit user confirmation."
        ),
        parameters={"type": "object", "properties": {}},
        handler=shutdown_system,
        safety_level="consequential",
    ))

    registry.register(ToolDef(
        name="restart_system",
        description=(
            "Restart the computer. This is a consequential action "
            "that requires explicit user confirmation."
        ),
        parameters={"type": "object", "properties": {}},
        handler=restart_system,
        safety_level="consequential",
    ))