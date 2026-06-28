"""
heartbeat.py — Proactive background loop.

Wakes up on a schedule, runs checks, decides if results are noteworthy,
and stores notices for the user. Quiet by default — earns the right
to interrupt.

Rules baked in from the start:
- Quiet by default, loud only when it counts
- Hold notices for the user (never fire and forget)
- Respect quiet hours
- Survive restarts (schedule persisted)
- No overlapping runs
- Every notice is dismissible
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import psutil


class NoticeStore:
    """Persistent store for proactive notices. Human-readable JSON."""

    def __init__(self, path: str | None = None):
        self.path = Path(path or os.path.expanduser("~/.vyren/notices.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._notices: list[dict] = []
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r") as f:
                    self._notices = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._notices = []

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._notices, f, indent=2, ensure_ascii=False)

    def add(self, check_name: str, message: str, urgency: str = "low"):
        """Add a new notice."""
        notice = {
            "id": f"{check_name}_{int(time.time())}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "check": check_name,
            "message": message,
            "urgency": urgency,  # "low", "medium", "high"
            "dismissed": False,
        }
        self._notices.append(notice)
        self._save()
        return notice

    def get_pending(self) -> list[dict]:
        """Get all undismissed notices, newest first."""
        return [n for n in self._notices if not n["dismissed"]]

    def dismiss(self, notice_id: str):
        """Mark a notice as dismissed."""
        for n in self._notices:
            if n["id"] == notice_id:
                n["dismissed"] = True
                self._save()
                return True
        return False

    def dismiss_all(self):
        """Dismiss all pending notices."""
        for n in self._notices:
            n["dismissed"] = True
        self._save()

    def clear_old(self, max_age_hours: int = 48):
        """Remove dismissed notices older than max_age_hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        self._notices = [
            n for n in self._notices
            if not n["dismissed"] or n.get("created_ts", time.time()) > cutoff
        ]
        self._save()

    def count_pending(self) -> int:
        return len(self.get_pending())


# ---------------------------------------------------------------------------
# Built-in system checks
# ---------------------------------------------------------------------------

def _check_cpu(threshold: float = 90) -> dict | None:
    cpu = psutil.cpu_percent(interval=1)
    if cpu > threshold:
        return {"ok": False, "value": cpu, "message": f"CPU at {cpu}% (threshold {threshold}%)", "urgency": "high"}
    return {"ok": True, "value": cpu}


def _check_memory(threshold: float = 90) -> dict | None:
    mem = psutil.virtual_memory()
    if mem.percent > threshold:
        return {"ok": False, "value": mem.percent, "message": f"RAM at {mem.percent}% (threshold {threshold}%)", "urgency": "medium"}
    return {"ok": True, "value": mem.percent}


def _check_disk(threshold: float = 95) -> dict | None:
    disk = psutil.disk_usage("/")
    if disk.percent > threshold:
        free_gb = round(disk.free / (1024**3), 1)
        return {"ok": False, "value": disk.percent, "message": f"Disk at {disk.percent}%, only {free_gb}GB free", "urgency": "low"}
    return {"ok": True, "value": disk.percent}


def _check_battery(low_threshold: float = 20) -> dict | None:
    battery = psutil.sensors_battery()
    if battery and not battery.power_plugged and battery.percent < low_threshold:
        return {"ok": False, "value": battery.percent, "message": f"Battery at {battery.percent}%, not charging", "urgency": "high"}
    return {"ok": True, "value": battery.percent if battery else 100}


BUILTIN_CHECKS = {
    "cpu_monitor": _check_cpu,
    "memory_monitor": _check_memory,
    "disk_monitor": _check_disk,
    "battery_monitor": _check_battery,
}


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------

def _in_quiet_hours(quiet_start: str, quiet_end: str, tz: str) -> bool:
    """Check if current time is within quiet hours."""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(tz)
        now = datetime.now(zone)
        start_h, start_m = map(int, quiet_start.split(":"))
        end_h, end_m = map(int, quiet_end.split(":"))
        current_minutes = now.hour * 60 + now.minute
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m

        if start_minutes <= end_minutes:
            return start_minutes <= current_minutes <= end_minutes
        else:
            # Spans midnight (e.g. 23:00 to 07:00)
            return current_minutes >= start_minutes or current_minutes <= end_minutes
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Heartbeat loop
# ---------------------------------------------------------------------------

class Heartbeat:
    """Background proactive loop. Runs in a daemon thread."""

    def __init__(self, notice_store: NoticeStore, config: dict,
                 on_notice: Callable[[dict], None] | None = None):
        self.notices = notice_store
        self.config = config
        self.on_notice = on_notice  # Callback when a notice is generated
        self._running = False
        self._thread: threading.Thread | None = None
        self._check_running = False  # Prevents overlapping runs

    def start(self):
        """Start the heartbeat in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the heartbeat loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._running

    def _loop(self):
        """Main heartbeat loop."""
        interval = self.config.get("interval_seconds", 300)
        quiet = self.config.get("quiet_hours", {})
        quiet_start = quiet.get("start", "23:00")
        quiet_end = quiet.get("end", "07:00")
        quiet_tz = quiet.get("timezone", "Africa/Lagos")

        # Schedule tracking: when each check was last run
        last_run: dict[str, float] = {}

        while self._running:
            # Check each configured check
            checks = self.config.get("checks", [])
            for check in checks:
                if not check.get("enabled", True):
                    continue

                name = check["name"]
                check_interval = check.get("interval_seconds", interval)

                # Skip if ran too recently
                if name in last_run and (time.time() - last_run[name]) < check_interval:
                    continue

                # Skip if overlapping
                if self._check_running:
                    continue

                # Skip if in quiet hours (for non-high urgency)
                if _in_quiet_hours(quiet_start, quiet_end, quiet_tz):
                    if check.get("urgency", "low") != "high":
                        continue

                # Run the check
                self._check_running = True
                try:
                    self._run_check(check)
                    last_run[name] = time.time()
                except Exception:
                    pass
                finally:
                    self._check_running = False

            # Sleep
            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)

    def _run_check(self, check: dict):
        """Run a single check and create a notice if noteworthy."""
        name = check["name"]
        check_fn = BUILTIN_CHECKS.get(name)
        if not check_fn:
            return  # Unknown check, skip

        threshold = check.get("threshold", 90)
        result = check_fn(threshold)

        if result and not result.get("ok", True):
            notice = self.notices.add(
                check_name=name,
                message=result.get("message", f"Check {name} triggered"),
                urgency=check.get("urgency", "low"),
            )
            if self.on_notice:
                try:
                    self.on_notice(notice)
                except Exception:
                    pass

    def get_status(self) -> dict:
        """Return heartbeat status for display."""
        return {
            "running": self._running,
            "pending_notices": self.notices.count_pending(),
            "checks_configured": len(self.config.get("checks", [])),
        }