"""
memory_extractor.py -- Smart post-turn memory extraction for VYREN.

Inspired by Mark-XXXIX-OR's two-stage memory pipeline:
  1. should_extract()  — cheap YES/NO check (avoids wasting tokens on
                         boring turns like "what time is it?")
  2. extract_memories() — structured JSON extraction when stage 1 says YES

Unlike Mark's implementation which uses a separate OpenRouter client,
VYREN uses its own provider.py (Gemini → Ollama fallback) so this works
offline too.

The extraction runs in a daemon thread after each turn_complete to
avoid blocking the voice pipeline.
"""

import json
import logging
import re
import threading
import time
from typing import Any

logger = logging.getLogger("vyren.memory_extractor")

# Cooldown between extraction attempts (seconds) to avoid hammering the API
_EXTRACTION_COOLDOWN = 30
_last_extraction_time = 0.0
_extraction_lock = threading.Lock()


def _call_model_short(prompt: str, system: str = "Reply only YES or NO.") -> str:
    """Call the lightweight model with a short prompt, return text."""
    from provider import run_turn_lightweight
    result = run_turn_lightweight(
        messages=[{"role": "user", "parts": [{"text": prompt}]}],
        system_prompt=system,
    )
    return (result.text or "").strip()


def should_extract(user_text: str, vyren_text: str) -> bool:
    """Stage 1: Should we try to extract memories from this turn?

    A cheap YES/NO check. Only returns True if the conversation
    contains personal facts, preferences, relationships, project info,
    or other long-term-worthy information.
    """
    if not user_text or len(user_text.strip()) < 5:
        return False

    combined = f"User: {user_text[:300]}\nVYREN: {vyren_text[:800]}"

    prompt = (
        "Does this conversation contain ANY of the following?\n"
        "- Personal facts (name, age, city, job, birthday, nationality)\n"
        "- Preferences or favorites (food, color, music, sport, game, film, book, etc.)\n"
        "- Active projects or goals the user is working on\n"
        "- People in the user's life (friends, family, partner, colleagues)\n"
        "- Things the user wants to do or buy in the future\n"
        "- Any other fact worth remembering long-term\n\n"
        f"Reply only YES or NO.\n\nConversation:\n{combined}"
    )

    try:
        result = _call_model_short(
            prompt,
            system="You are a memory relevance checker. Reply only YES or NO. Nothing else.",
        )
        return "YES" in result.upper()
    except Exception as e:
        logger.debug("Memory extraction stage 1 failed: %s", e)
        return False


def extract_memories(user_text: str, vyren_text: str) -> dict:
    """Stage 2: Extract structured memories from the conversation.

    Returns a dict with VYREN memory layer keys, e.g.:
    {
        "semantic": {"user_name": "Chidi"},
        "preference": {"favorite_music": "Afrobeats"},
        "episodic": {"discussed_vyren_v2": "User wants VYREN v2 merged with tier 3"},
    }

    Each value is {key: value} — the memory_extractor pipeline will
    convert these into proper MemoryEntry objects via memory_v2.
    """
    combined = f"User: {user_text[:600]}\nVYREN: {vyren_text[:300]}"

    prompt = (
        "Extract ALL memorable personal facts from this conversation. Any language.\n"
        "Return ONLY valid JSON. Use {} if truly nothing is worth saving.\n\n"
        "Category guide (map to VYREN memory layers):\n"
        '  "semantic"    -> name, age, birthday, city, country, job, school, '
        "nationality, language, facts about the user\n"
        '  "preference"  -> ANY favorite or preferred thing: favorite_food, '
        "favorite_color, favorite_music, favorite_film, favorite_game, "
        "favorite_sport, hobbies, interests, dislikes, etc.\n"
        '  "project"     -> projects being built, ongoing work, goals, ideas in progress\n'
        '  "episodic"    -> important events, decisions made, experiences, conversations '
        "worth remembering\n"
        "  \"procedural\" -> workflows, how-to knowledge, processes the user follows\n\n"
        "IMPORTANT:\n"
        "- Be LIBERAL: if something MIGHT be worth remembering, include it.\n"
        "- Extract from BOTH user and VYREN turns.\n"
        "- Skip: weather results, one-time commands, search results, greetings.\n"
        "- Use concise English values regardless of conversation language.\n"
        "- Key names should be short and descriptive (snake_case).\n\n"
        "Format:\n"
        '{\n'
        '  "semantic": {"user_name": "Chidi", "city": "Lagos"},\n'
        '  "preference": {"favorite_music": "Afrobeats", "ide_editor": "VS Code"},\n'
        '  "project": {"vyren_v2": "Building AI OS with voice-first design"},\n'
        '  "episodic": {"decided_merge_architecture": "User chose to merge v2 into tier 3"}\n'
        "}\n\n"
        f"Conversation:\n{combined}\n\nJSON:"
    )

    try:
        raw = _call_model_short(
            prompt,
            system=(
                "Return ONLY valid JSON. No markdown fences, no explanation, "
                "no extra text. Use {} if nothing to save."
            ),
        )

        # Clean markdown fences if present
        clean = raw.strip()
        if clean.startswith("```"):
            parts = clean.split("```")
            clean = parts[1] if len(parts) > 1 else clean
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip().rstrip("`").strip()

        if not clean or clean == "{}":
            return {}

        data = json.loads(clean)
        if not isinstance(data, dict):
            return {}

        # Validate: only allow known layer names as top-level keys
        valid_layers = {
            "semantic", "preference", "episodic", "project",
            "procedural", "working",
        }
        filtered = {}
        for key, value in data.items():
            if key in valid_layers and isinstance(value, dict):
                filtered[key] = value

        return filtered

    except json.JSONDecodeError:
        logger.debug("Memory extraction: JSON parse failed")
        return {}
    except Exception as e:
        logger.debug("Memory extraction failed: %s", e)
        return {}


def extract_and_store(user_text: str, vyren_text: str, memory_manager) -> int:
    """Full pipeline: check → extract → store. Returns count of memories stored."""
    global _last_extraction_time

    with _extraction_lock:
        now = time.time()
        if now - _last_extraction_time < _EXTRACTION_COOLDOWN:
            return 0
        _last_extraction_time = now

    # Stage 1
    if not should_extract(user_text, vyren_text):
        return 0

    # Stage 2
    extracted = extract_memories(user_text, vyren_text)
    if not extracted:
        return 0

    # Stage 3: Store into memory_v2
    from memory_v2 import MemoryLayer
    layer_map = {
        "semantic": MemoryLayer.SEMANTIC,
        "preference": MemoryLayer.PREFERENCE,
        "episodic": MemoryLayer.EPISODIC,
        "project": MemoryLayer.PROJECT,
        "procedural": MemoryLayer.PROCEDURAL,
        "working": MemoryLayer.WORKING,
    }

    count = 0
    for category, entries in extracted.items():
        layer = layer_map.get(category, MemoryLayer.SEMANTIC)
        for key, value in entries.items():
            if not value or not isinstance(value, str):
                continue
            try:
                memory_manager.remember(
                    key=key,
                    value=str(value),
                    layer=layer,
                    importance=0.6 if category in ("semantic", "preference") else 0.4,
                    source="auto_extract",
                    tags=["auto_extracted", category],
                )
                count += 1
            except Exception as e:
                logger.debug("Failed to store extracted memory %s: %s", key, e)

    if count > 0:
        logger.info(
            "Auto-extracted %d memory(ies) from conversation turn", count
        )

    return count


def extract_and_store_async(user_text: str, vyren_text: str, memory_manager):
    """Run extraction in a daemon thread (non-blocking)."""
    def _run():
        try:
            extract_and_store(user_text, vyren_text, memory_manager)
        except Exception as e:
            logger.debug("Async memory extraction failed: %s", e)

    t = threading.Thread(target=_run, name="vyren-mem-extract", daemon=True)
    t.start()