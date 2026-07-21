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

# File that stores the last greeting hash to avoid repeats
_GREETING_HISTORY_PATH = Path(os.path.expanduser("~/.vyren/greeting_history.json"))
_MAX_HISTORY = 10


def _load_history() -> list[str]:
    try:
        if _GREETING_HISTORY_PATH.exists():
            with open(_GREETING_HISTORY_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_history(history: list[str]):
    _GREETING_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_GREETING_HISTORY_PATH, "w") as f:
            json.dump(history[-_MAX_HISTORY:], f)
    except Exception:
        pass


def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Signal gathering
# ---------------------------------------------------------------------------

def _gather_signals(services: dict) -> dict:
    """Gather all available real data for greeting context."""
    signals = {
        "time_of_day": _get_time_of_day(),
        "hour": datetime.now().hour,
        "minute": datetime.now().minute,
        "day_of_week": datetime.now().strftime("%A"),
        "date_str": datetime.now().strftime("%B %d"),
        "tool_count": 0,
        "memory_entries": 0,
        "ollama_available": False,
        "connectivity": "online",
        "pending_notices": 0,
        "pending_urgent": 0,
        "voice_active": False,
        "battery_percent": None,
        "battery_charging": None,
        "has_battery": True,
        "last_boot": None,
    }

    # Tools
    registry = services.get("registry")
    if registry:
        try:
            signals["tool_count"] = len(registry.tool_names())
        except Exception:
            pass

    # Memory
    memory = services.get("memory")
    if memory:
        try:
            signals["memory_entries"] = memory.count()
        except Exception:
            pass

    # Ollama
    try:
        from provider import _ollama_available
        signals["ollama_available"] = _ollama_available()
    except Exception:
        pass

    # Connectivity
    connectivity = services.get("connectivity")
    if connectivity:
        signals["connectivity"] = connectivity.mode.value

    # Notices
    notice_store = services.get("notice_store")
    if notice_store:
        try:
            pending = notice_store.get_pending()
            signals["pending_notices"] = len(pending)
            signals["pending_urgent"] = sum(
                1 for n in pending if n.get("urgency") == "high"
            )
        except Exception:
            pass

    # Voice
    voice = services.get("voice_runtime")
    if voice:
        signals["voice_active"] = voice.is_active

    # Battery
    try:
        import psutil
        battery = psutil.sensors_battery()
        if battery is None:
            signals["has_battery"] = False
        else:
            signals["battery_percent"] = battery.percent
            signals["battery_charging"] = battery.power_plugged
    except Exception:
        pass

    # Last boot time (to detect offline gaps)
    service_state = services.get("service_state")
    if service_state:
        try:
            signals["last_boot"] = service_state.get("last_startup")
        except Exception:
            pass

    return signals


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _get_time_of_day() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


def _friendly_time() -> str:
    """Return a human-friendly time string like 'almost 11' or 'half past 3'."""
    h = datetime.now().hour
    m = datetime.now().minute
    h12 = h % 12 or 12

    if m == 0:
        return str(h12) + " o'clock"
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
# Greeting generation (compositional, not template-based)
# ---------------------------------------------------------------------------

def generate_greeting(services: dict) -> str:
    """Generate a unique, contextual greeting for this boot."""
    signals = _gather_signals(services)
    history = _load_history()

    # Try up to 20 times to generate a unique greeting
    for _ in range(20):
        greeting = _compose_greeting(signals)
        h = _hash(greeting)

        # Don't repeat the last 3 greetings
        if h not in history[-3:]:
            history.append(h)
            _save_history(history)
            return greeting

    # Fallback (should almost never happen)
    return _compose_greeting(signals)


def _compose_greeting(s: dict) -> str:
    """Compose a greeting from signal-aware fragments."""
    parts = []
    tod = s["time_of_day"]

    # --- Part 1: Opening (time-aware, varied) ---
    opening = _pick_opening(tod, s["hour"], s["minute"])
    parts.append(opening)

    # --- Part 2: Contextual addition (0-1 items, not always present) ---
    context = _pick_context(s)
    if context:
        parts.append(context)

    # --- Part 3: Closing (varied) ---
    closing = _pick_closing(s)
    if closing:
        parts.append(closing)

    return " ".join(parts)


def _pick_opening(tod: str, hour: int, minute: int) -> str:
    """Pick the opening line. Always unique-ish due to time variation."""
    openers = {
        "morning": [
            "Good morning, Psalms.",
            "Morning, Psalms.",
            "Good morning.",
            "Rise and shine.",
            "Early start today.",
            "Morning.",
        ],
        "afternoon": [
            "Good afternoon, Psalms.",
            "Afternoon.",
            "Hey, good afternoon.",
            "Welcome back.",
            "Hey there.",
        ],
        "evening": [
            "Good evening, Psalms.",
            "Evening.",
            "Hey, Psalms.",
            "Good evening.",
            "Welcome back.",
        ],
        "night": [
            "Still up, Psalms?",
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
    elif random.random() < 0.3:
        candidates.append("All systems healthy.")
    elif random.random() < 0.2:
        candidates.append("System health looks good.")

    # Offline mode
    if s.get("connectivity") == "offline":
        candidates.append("Running offline.")
    elif s.get("connectivity") == "degraded":
        candidates.append("Connectivity's a bit shaky but I'm managing.")

    # Day of week
    if s["day_of_week"] in ("Monday",):
        candidates.append("Fresh week ahead.")
    elif s["day_of_week"] in ("Friday",):
        candidates.append("Almost the weekend.")

    if not candidates:
        return None

    # Return at most one
    return random.choice(candidates)


def _pick_closing(s: dict) -> str | None:
    """Pick a closing line. Sometimes returns None for brevity."""
    # 60% chance to have a closing
    if random.random() > 0.6:
        return None

    closings = [
        "Ready when you are.",
        "What's on the agenda?",
        "What are we working on today?",
        "What can I do for you?",
        "Let me know what you need.",
        "How can I help?",
        "I'm here if you need anything.",
        "What's first?",
        "What's the plan?",
    ]

    # If there are urgent notices, hint at them
    if s.get("pending_urgent", 0) > 0:
        urgent_closings = [
            "By the way, I have something that needs your attention.",
            "There's something you should know — ask me about it.",
            "I've got a heads-up for you when you're ready.",
        ]
        return random.choice(urgent_closings)

    # If there are pending (non-urgent) notices
    if s.get("pending_notices", 0) > 0:
        notice_closings = [
            "You've got a couple of things waiting.",
            "A few items need your attention when you get a chance.",
        ]
        return random.choice(notice_closings) if random.random() < 0.5 else random.choice(closings)

    return random.choice(closings)