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
- Dedup: same check won't spam the same notice repeatedly
- Battery notices auto-clear when charging
- Stale notices from previous boot are cleared if condition is resolved
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

    def add(self, check_name: str, message: str, urgency: str = "low") -> dict:
        """Add a new notice. Deduplicates against existing notices for same check."""
        # --- Dedup: don't add if the same check has an identical pending notice ---
        for n in self._notices:
            if (not n["dismissed"]
                    and n["check"] == check_name
                    and n["message"] == message):
                return n  # Already exists, return existing

        notice = {
            "id": f"{check_name}_{int(time.time())}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "check": check_name,
            "message": message,
            "urgency": urgency,
            "dismissed": False,
        }
        self._notices.append(notice)
        self._save()
        return notice

    def dismiss(self, notice_id: str):
        for n in self._notices:
            if n["id"] == notice_id:
                n["dismissed"] = True
                self._save()
                return True
        return False

    def dismiss_all(self):
        for n in self._notices:
            n["dismissed"] = True
        self._save()

    def dismiss_by_check(self, check_name: str):
        """Dismiss ALL pending notices for a given check name.
        Used to clear stale battery notices when charging starts."""
        changed = False
        for n in self._notices:
            if not n["dismissed"] and n["check"] == check_name:
                n["dismissed"] = True
                changed = True
        if changed:
            self._save()
        return changed

    def clear_old(self, max_age_hours: int = 48):
        cutoff = time.time() - (max_age_hours * 3600)
        self._notices = [
            n for n in self._notices
            if not n["dismissed"] or n.get("timestamp", time.time()) > cutoff
        ]
        self._save()

    def clear_stale_on_boot(self):
        """Dismiss all pending notices whose conditions are no longer true.
        Called once at startup to prevent replaying old alerts."""
        changed = False

        # Check battery: if charging or no battery, dismiss old battery notices
        battery = psutil.sensors_battery()
        if battery is None:
            # Desktop — no battery. Clear all battery notices.
            changed |= self.dismiss_by_check("battery_monitor")
        elif battery.power_plugged:
            # Charging — dismiss old low-battery notices
            changed |= self.dismiss_by_check("battery_monitor")

        # Clear any notice older than 1 hour (stale from previous session)
        cutoff = time.time() - 3600
        for n in self._notices:
            if not n["dismissed"]:
                try:
                    ts = datetime.fromisoformat(n["timestamp"]).timestamp()
                    if ts < cutoff:
                        n["dismissed"] = True
                        changed = True
                except Exception:
                    pass

        if changed:
            self._save()

    def get_pending(self) -> list[dict]:
        return [n for n in self._notices if not n["dismissed"]]

    def count_pending(self) -> int:
        return len(self.get_pending())


# ---------------------------------------------------------------------------
# Built-in system checks
# ---------------------------------------------------------------------------

def _check_cpu(threshold: float = 90) -> dict | None:
    cpu = psutil.cpu_percent(interval=1)
    if cpu > threshold:
        return {"ok": False, "value": cpu,
                "message": f"CPU at {cpu}% (threshold {threshold}%)",
                "urgency": "high"}
    return {"ok": True, "value": cpu}


def _check_memory(threshold: float = 90) -> dict | None:
    mem = psutil.virtual_memory()
    if mem.percent > threshold:
        return {"ok": False, "value": mem.percent,
                "message": f"RAM at {mem.percent}% (threshold {threshold}%)",
                "urgency": "medium"}
    return {"ok": True, "value": mem.percent}


def _check_disk(threshold: float = 95) -> dict | None:
    disk = psutil.disk_usage("/")
    if disk.percent > threshold:
        free_gb = round(disk.free / (1024**3), 1)
        return {"ok": False, "value": disk.percent,
                "message": f"Disk at {disk.percent}%, only {free_gb}GB free",
                "urgency": "low"}
    return {"ok": True, "value": disk.percent}


def _check_battery(low_threshold: float = 20) -> dict | None:
    """Check battery with full state awareness.

    Returns None if:
      - No battery present (desktop)
      - Battery is charging (even if low — it's recovering)
      - Battery is full

    Returns warning only if:
      - Battery is DISCHARGING (not plugged in)
      - AND below the low_threshold
    """
    battery = psutil.sensors_battery()
    if battery is None:
        # No battery hardware (desktop). Nothing to report.
        return {"ok": True, "value": None, "no_battery": True}

    percent = battery.percent
    plugged = battery.power_plugged

    # If charging or fully charged — no warning, regardless of percentage
    if plugged:
        return {"ok": True, "value": percent, "charging": True}

    # Discharging — only warn if below threshold
    if percent < low_threshold:
        return {
            "ok": False,
            "value": percent,
            "message": f"Battery at {percent}% and discharging. Consider plugging in.",
            "urgency": "high",
        }

    return {"ok": True, "value": percent, "charging": False}


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
        self.on_notice = on_notice
        self._running = False
        self._thread: threading.Thread | None = None
        self._check_running = False
        # Track the last result per check to detect state changes
        self._last_results: dict[str, dict] = {}

    def start(self):
        if self._running:
            return

        # Clear stale notices from previous session BEFORE starting checks
        self.notices.clear_stale_on_boot()

        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._running

    def _loop(self):
        interval = self.config.get("interval_seconds", 300)
        quiet = self.config.get("quiet_hours", {})
        quiet_start = quiet.get("start", "23:00")
        quiet_end = quiet.get("end", "07:00")
        quiet_tz = quiet.get("timezone", "Africa/Lagos")

        last_run: dict[str, float] = {}

        while self._running:
            checks = self.config.get("checks", [])
            for check in checks:
                if not check.get("enabled", True):
                    continue

                name = check["name"]
                check_interval = check.get("interval_seconds", interval)

                if name in last_run and (time.time() - last_run[name]) < check_interval:
                    continue

                if self._check_running:
                    continue

                if _in_quiet_hours(quiet_start, quiet_end, quiet_tz):
                    if check.get("urgency", "low") != "high":
                        continue

                self._check_running = True
                try:
                    self._run_check(check)
                    last_run[name] = time.time()
                except Exception:
                    pass
                finally:
                    self._check_running = False

            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)

    def _run_check(self, check: dict):
        name = check["name"]
        check_fn = BUILTIN_CHECKS.get(name)
        if not check_fn:
            return

        threshold = check.get("threshold", 90)
        result = check_fn(threshold)

        if result is None:
            return

        prev = self._last_results.get(name)

        # --- State change detection ---

        # If check is now OK but was previously failing, clear old notices
        if result.get("ok", True):
            if prev and not prev.get("ok", True):
                # Condition resolved — dismiss old notices for this check
                self.notices.dismiss_by_check(name)
            self._last_results[name] = result
            return

        # Check is failing — but don't spam if the message is the same
        if prev and not prev.get("ok", True):
            prev_msg = prev.get("message", "")
            curr_msg = result.get("message", "")
            if prev_msg == curr_msg:
                # Same problem, same message — don't create a duplicate notice
                self._last_results[name] = result
                return

        # New problem or changed message — create notice
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

        self._last_results[name] = result

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "pending_notices": self.notices.count_pending(),
            "checks_configured": len(self.config.get("checks", [])),
        }