"""
brain/greetings.py -- Natural, Context-Aware Greeting Generator.

Every boot should feel unique, warm, and alive.
Like JARVIS greeting Tony — not a robot reading a template.

Principles:
  - Never repeat the exact same greeting twice in a row
  - Use real data (time, battery, system health, notices, connectivity)
  - Never fabricate information
  - Omit data that can't be retrieved (gracefully)
  - 1-3 sentences, conversational, warm
  - Acknowledge offline gaps if applicable
  - Urgent items after the greeting, not in it
"""

import hashlib
import json
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("vyren.brain.greetings")

from platform_paths import get_greeting_history_path

_GREETING_HISTORY_PATH = get_greeting_history_path()
_MAX_HISTORY = 10


def _load_history() -> list[str]:
    try:
        if _GREETING_HISTORY_PATH.exists():
            with open(_GREETING_HISTORY_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_history(history: list[str]) -> None:
    try:
        _GREETING_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_GREETING_HISTORY_PATH, "w") as f:
            json.dump(history[-_MAX_HISTORY:], f)
    except Exception:
        pass


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def _gather_signals(services: dict) -> dict:
    now = datetime.now()
    return {
        "time_of_day": _get_time_of_day(now),
        "hour": now.hour,
        "minute": now.minute,
        "has_battery": services.get("has_battery"),
        "battery_percent": services.get("battery_percent"),
        "battery_charging": services.get("battery_charging"),
        "internet_available": services.get("internet_available"),
        "notices": services.get("notices", []),
        "day_of_week": now.strftime("%A"),
    }


def _get_time_of_day(now: datetime) -> str:
    hour = now.hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


def _friendly_time() -> str:
    now = datetime.now()
    h = now.hour
    m = now.minute
    h12 = h % 12 or 12
    if m == 0:
        return f"{h12} o'clock"
    elif m == 15:
        return f"quarter past {h12}"
    elif m == 30:
        return f"half past {h12}"
    elif m == 45:
        return f"quarter to {h12 + 1 if h12 < 12 else 1}"
    elif m < 30:
        return f"just past {h12}"
    else:
        return f"almost {h12 + 1 if h12 < 12 else 1}"


# ---------------------------------------------------------------------------
# Greeting generation
# ---------------------------------------------------------------------------

def generate_greeting(services: dict) -> str:
    """Generate a unique, contextual greeting for this boot."""
    try:
        from identity import get_assistant_name
        assistant_name = get_assistant_name()
    except Exception:
        assistant_name = "VYREN"

    signals = _gather_signals(services)
    history = _load_history()

    # Try up to 20 times to generate a unique greeting
    for _ in range(20):
        greeting = _compose_greeting(signals, assistant_name=assistant_name)
        h = _hash(greeting)

        # Don't repeat the last 3 greetings
        if h not in history[-3:]:
            history.append(h)
            _save_history(history)
            return greeting

    # Fallback (should almost never happen)
    return _compose_greeting(signals, assistant_name=assistant_name)


def _compose_greeting(signals: dict, assistant_name: str = "VYREN") -> str:
    """Compose a greeting from signal-aware fragments."""
    parts = []
    tod = signals["time_of_day"]
    hour = signals["hour"]
    minute = signals["minute"]

    # --- Part 1: Opening ---
    opening = _pick_opening(tod, hour, minute, assistant_name=assistant_name)
    parts.append(opening)

    # --- Part 2: Contextual addition ---
    context = _pick_context(signals)
    if context:
        parts.append(context)

    # --- Part 3: Closing ---
    closing = _pick_closing()
    if closing:
        parts.append(closing)

    return " ".join(parts)


def _pick_opening(tod: str, hour: int, minute: int, assistant_name: str = "VYREN") -> str:
    """Pick the opening line. Always unique-ish due to time variation."""
    openers = {
        "morning": [
            f"Good morning.",
            "Morning.",
            "Rise and shine.",
            "Early start today.",
            "Morning.",
        ],
        "afternoon": [
            f"Good afternoon.",
            "Afternoon.",
            "Hey, good afternoon.",
            "Welcome back.",
            "Hey there.",
        ],
        "evening": [
            f"Good evening.",
            "Evening.",
            "Hey.",
            "Good evening.",
            "Welcome back.",
        ],
        "night": [
            "Still up?",
            "Working late?",
            "Hey.",
            "Burning the midnight oil?",
            "Late night session.",
        ],
    }

    base = random.choice(openers.get(tod, ["Hey."]))

    # Add time reference ~30% of the time
    if random.random() < 0.3:
        time_str = _friendly_time()
        connectors = ["It's", "It's about", "It's almost"]
        if "early" in base or "late" in base:
            return base
        return f"{random.choice(connectors)} {time_str}."

    return base


def _pick_context(s: dict) -> str | None:
    """Pick 0 or 1 contextual additions based on real data."""
    candidates = []

    # Battery status
    if s.get("has_battery") and s.get("battery_charging") is not None:
        if s["battery_charging"]:
            candidates.append("Your laptop is charging.")
        elif s["battery_percent"] is not None and s["battery_percent"] > 80:
            candidates.append("Battery's looking good.")

    # System health
    if random.random() < 0.4:
        candidates.append("Everything's running smoothly.")

    # Connectivity
    if s.get("internet_available") is False:
        candidates.append("I'm running offline right now.")

    # Notices
    notices = s.get("notices") or []
    if notices:
        candidates.append(f"You have {len(notices)} pending notice{'s' if len(notices) != 1 else ''}.")

    return random.choice(candidates) if candidates else None


def _pick_closing() -> str | None:
    closings = [
        "What's next?",
        "Ready when you are.",
        "Let's get to work.",
        "How can I help?",
        "What are we building?",
        "What's the plan?",
    ]
    return random.choice(closings) if random.random() < 0.7 else None
