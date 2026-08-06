"""
brain/greeting_engine.py -- Startup Greeting Engine.

VYREN used to sit silently after boot until spoken to. This module is
what makes it speak first: a fresh, spoken-aloud greeting every launch,
so the first thing you hear is VYREN already being alive and aware —
not a robot waiting for a wake word.

Architecture
------------
GreetingManager.generate_async() composes a greeting from pluggable
GreetingProvider objects, in priority order:

  SystemContextProvider  -- always available. Wraps brain.greetings'
                             existing signal-composition (time of day,
                             battery, connectivity, day of week, pending
                             notices) — reused, not duplicated.
  ProjectStatusProvider   -- git status of the VYREN repo + scheduler's
                             pending jobs, framed as "while you were
                             away" context.
  LiveContentProvider     -- one paraphrased headline from a rotating
                             topic pool (AI, robotics, cybersecurity,
                             space, football, F1, NBA, Nigerian/world
                             news, technology...), fetched via the
                             existing web_search tool and, if a
                             reasoning engine is available, rewritten
                             into a single casual sentence in VYREN's
                             own voice. Bounded by a timeout; skipped
                             outright if offline.
  LocalContentProvider    -- offline-safe bank: jokes, trivia,
                             "did you know", programming/cybersecurity
                             tips, philosophy, motivation. Always
                             available — this is what fires when the
                             live path can't.

Adding a new content source means writing one GreetingProvider subclass
and adding it to GreetingManager.DEFAULT_PROVIDERS. Nothing else needs
to change.

Rotation / anti-repetition
---------------------------
`data_dir/greeting_history.json` stores the last _MAX_HISTORY entries as
{hash, category, ts}. Category selection is weighted away from
recently-used categories (not just exact-text dedup), so the topic
mix feels fresh over weeks/months, not just turn to turn. The file is
backward-compatible with brain.greetings' older plain-hash-list format.
"""

import asyncio
import json
import logging
import os
import random
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("vyren.brain.greeting_engine")

from platform_paths import get_greeting_history_path, get_vyren_dir

_HISTORY_PATH = get_greeting_history_path()
_MAX_HISTORY = 40
_DATA_DIR = Path(__file__).parent / "data"
_BANK_PATH = _DATA_DIR / "greeting_bank.json"

# Categories that need a network call.
LIVE_CATEGORY_QUERIES = {
    "ai_news": "latest AI news today",
    "robotics_news": "robotics news today",
    "cybersecurity_news": "cybersecurity news today",
    "space_news": "space exploration news today",
    "science_news": "science discovery news today",
    "world_news": "world news headlines today",
    "nigerian_news": "Nigeria news today",
    "football": "football transfer news today",
    "formula1": "Formula 1 news today",
    "nba": "NBA news today",
    "technology": "technology news today",
}

# Categories served entirely from the local bank — see greeting_bank.json.
LOCAL_CATEGORIES = (
    "joke", "dry_humor", "sarcasm", "trivia", "did_you_know",
    "programming_tip", "cybersecurity_tip", "philosophy",
    "motivation", "productivity", "history_today",
)


# ---------------------------------------------------------------------------
# History / rotation
# ---------------------------------------------------------------------------

def _load_history() -> list[dict]:
    try:
        if not _HISTORY_PATH.exists():
            return []
        with open(_HISTORY_PATH, "r") as f:
            raw = json.load(f)
    except Exception:
        return []

    # Backward compat: brain.greetings originally stored a flat list of
    # hash strings. Upgrade those in place to the richer schema.
    return [
        entry if isinstance(entry, dict) else {"hash": entry, "category": None, "ts": 0}
        for entry in raw
    ]


def _save_history(history: list[dict]):
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_HISTORY_PATH, "w") as f:
            json.dump(history[-_MAX_HISTORY:], f)
    except Exception as e:
        logger.debug(f"Could not persist greeting history: {e}")


def _pick_category(history: list[dict], pool: list[str]) -> str:
    """Weighted pick that favors categories NOT used recently.

    Recency weight decays linearly over the last _MAX_HISTORY entries —
    a category used last startup gets the lowest weight, one never seen
    (or seen 40 startups ago) gets full weight.
    """
    recent_categories = [e.get("category") for e in history[-_MAX_HISTORY:]]
    weights = []
    for cat in pool:
        try:
            idx_from_end = len(recent_categories) - 1 - recent_categories[::-1].index(cat)
            recency = len(recent_categories) - idx_from_end  # smaller = more recent
        except ValueError:
            recency = _MAX_HISTORY  # never used — max weight
        weights.append(max(1, recency))
    return random.choices(pool, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

@dataclass
class GreetingContent:
    """What a provider hands back to the manager."""
    category: str
    fragment: str  # one conversational sentence/clause, no trailing period logic needed


class GreetingProvider:
    """Base class for a greeting content source. Subclass and register."""

    name = "base"

    async def generate(self, services: dict, history: list[dict]) -> Optional[GreetingContent]:
        raise NotImplementedError


class SystemContextProvider(GreetingProvider):
    """Wraps brain.greetings' existing time/battery/connectivity/notice
    signal composition — this is the one guaranteed-available source and
    doubles as the opening line for every greeting.
    """

    name = "system_context"

    async def generate(self, services: dict, history: list[dict]) -> Optional[GreetingContent]:
        from brain import greetings as legacy

        signals = legacy._gather_signals(services)
        try:
            from identity import get_assistant_name
            assistant_name = get_assistant_name()
        except Exception:
            assistant_name = "VYREN"
        opening = legacy._pick_opening(signals["time_of_day"], signals["hour"], signals["minute"], assistant_name=assistant_name)
        context = legacy._pick_context(signals)
        fragment = opening if not context else f"{opening} {context}"
        return GreetingContent(category="system_context", fragment=fragment)


class ProjectStatusProvider(GreetingProvider):
    """'While you were away' — pending scheduler jobs + git status of the
    VYREN repo itself. Only returns something when there's actually
    something to say; silence here just means the manager skips it.
    """

    name = "project_status"

    async def generate(self, services: dict, history: list[dict]) -> Optional[GreetingContent]:
        return await asyncio.to_thread(self._check, services)

    def _check(self, services: dict) -> Optional[GreetingContent]:
        notes = []

        scheduler = services.get("scheduler")
        if scheduler:
            try:
                status = scheduler.get_status()
                pending = status.get("pending", 0) + status.get("recurring", 0)
                if pending == 1:
                    notes.append("you've got one pending reminder")
                elif pending > 1:
                    notes.append(f"you've got {pending} pending reminders")
            except Exception:
                pass

        try:
            repo_root = get_vyren_dir()
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_root, capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                changed = [l for l in result.stdout.splitlines() if l.strip()]
                if changed:
                    notes.append(f"{len(changed)} uncommitted change"
                                 f"{'s' if len(changed) != 1 else ''} sitting in the repo")
        except Exception:
            pass

        if not notes:
            return None
        fragment = "While you were away, " + " and ".join(notes) + "."
        return GreetingContent(category="project_status", fragment=fragment)


class LocalContentProvider(GreetingProvider):
    """Offline-safe bank — jokes, trivia, tips, philosophy. Always works."""

    name = "local_content"

    def __init__(self):
        self._bank: dict[str, list[str]] = {}
        try:
            with open(_BANK_PATH, "r") as f:
                self._bank = json.load(f)
        except Exception as e:
            logger.warning(f"Greeting content bank missing/unreadable: {e}")

    async def generate(self, services: dict, history: list[dict]) -> Optional[GreetingContent]:
        pool = [c for c in LOCAL_CATEGORIES if self._bank.get(c)]
        if not pool:
            return None
        category = _pick_category(history, pool)
        items = self._bank[category]
        # Avoid repeating the exact same item until the whole set has cycled
        used = {e.get("hash") for e in history[-_MAX_HISTORY:]}
        candidates = [i for i in items if str(hash(i)) not in used] or items
        return GreetingContent(category=category, fragment=random.choice(candidates))


class LiveContentProvider(GreetingProvider):
    """One paraphrased, conversational headline from a rotating news
    category. Skips itself entirely if offline; the manager falls back
    to LocalContentProvider on any failure or timeout.
    """

    name = "live_content"

    async def generate(self, services: dict, history: list[dict]) -> Optional[GreetingContent]:
        connectivity = services.get("connectivity")
        if connectivity is not None:
            try:
                if connectivity.is_offline:
                    return None
            except Exception:
                pass

        category = _pick_category(history, list(LIVE_CATEGORY_QUERIES.keys()))
        query = LIVE_CATEGORY_QUERIES[category]

        snippet = await asyncio.to_thread(self._search, query)
        if not snippet:
            return None

        fragment = await asyncio.to_thread(self._paraphrase, services, category, snippet)
        if not fragment:
            return None
        return GreetingContent(category=category, fragment=fragment)

    @staticmethod
    def _search(query: str) -> Optional[str]:
        try:
            from tools.web_tools import _ddg_search
            results = _ddg_search(query, max_results=3)
        except Exception:
            return None
        for r in results:
            snippet = (r.get("snippet") or "").strip()
            if len(snippet) > 20:
                return snippet[:280]
        return None

    @staticmethod
    def _paraphrase(services: dict, category: str, snippet: str) -> Optional[str]:
        """Turn a search-result snippet into one casual, in-VYREN's-voice
        sentence. Falls back to a light template wrap if no reasoning
        engine is wired in (still never quotes the snippet verbatim).
        """
        reasoning = services.get("reasoning")
        if reasoning is not None:
            try:
                prompt = (
                    "In exactly one short, casual spoken sentence, in your "
                    "own words (never quote directly), mention this current "
                    f"{category.replace('_', ' ')} item to the person you're "
                    f"greeting at startup. Raw source snippet: {snippet}\n"
                    "Reply with ONLY the sentence, nothing else."
                )
                result = reasoning.reason(
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=services.get("system_prompt", ""),
                )
                text = (result.text or "").strip().strip('"')
                if text and len(text) < 240:
                    return text
            except Exception as e:
                logger.debug(f"Greeting paraphrase failed: {e}")

        # No reasoning engine, or it failed — a plain, honest wrap that
        # still avoids reproducing the snippet as a "quote".
        topic = category.replace("_", " ")
        return f"Something on {topic} today — worth a look when you get a chance."


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class GreetingManager:
    """Orchestrates providers into one finished, spoken greeting.

    Usage:
        gm = GreetingManager(services)
        text = await gm.generate_async(timeout=4.0)
    """

    # Order matters: system_context always runs (it's the opening line).
    # project_status is a cheap local check. live_content is the one with
    # a network timeout; local_content is its always-available fallback.
    DEFAULT_PROVIDERS: list[GreetingProvider] = [
        SystemContextProvider(),
        ProjectStatusProvider(),
        LiveContentProvider(),
        LocalContentProvider(),
    ]

    def __init__(self, services: dict, providers: Optional[list[GreetingProvider]] = None):
        self._services = services
        self._providers = providers if providers is not None else self.DEFAULT_PROVIDERS

    async def generate_async(self, timeout: float = 4.0) -> str:
        """Build one greeting. Never raises — always returns *something*
        speakable, even with every provider down.
        """
        history = _load_history()
        by_name = {p.name: p for p in self._providers}

        opening = await self._safe_run(by_name.get("system_context"), history, timeout=1.5)
        status = await self._safe_run(by_name.get("project_status"), history, timeout=1.5)

        # Live content gets the real timeout budget; on any failure or
        # timeout, fall straight through to local content so startup
        # is never held hostage by a slow network.
        content = None
        live = by_name.get("live_content")
        if live is not None:
            content = await self._safe_run(live, history, timeout=timeout)
        if content is None:
            local = by_name.get("local_content")
            if local is not None:
                content = await self._safe_run(local, history, timeout=1.0)

        parts = []
        if opening:
            parts.append(opening.fragment)
        if status:
            parts.append(status.fragment)
        if content:
            parts.append(content.fragment)

        greeting = " ".join(p.strip() for p in parts if p and p.strip()) or \
            "VYREN is online and listening."

        # Record what actually got used, for future rotation.
        used_history = _load_history()
        now = time.time()
        for c in (opening, status, content):
            if c:
                used_history.append({
                    "hash": str(hash(c.fragment)),
                    "category": c.category,
                    "ts": now,
                })
        _save_history(used_history)

        return greeting

    async def _safe_run(self, provider: Optional[GreetingProvider], history: list[dict],
                         timeout: float) -> Optional[GreetingContent]:
        """Run one provider with a hard timeout. Any exception or timeout
        is swallowed — a missing greeting fragment is never worth risking
        the whole greeting (or worse, startup) over.
        """
        if provider is None:
            return None
        try:
            return await asyncio.wait_for(
                provider.generate(self._services, history),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.debug(f"Greeting provider '{provider.name}' timed out after {timeout}s")
            return None
        except Exception as e:
            logger.debug(f"Greeting provider '{provider.name}' failed: {e}")
            return None
