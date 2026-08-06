"""
identity.py -- Centralized VYREN identity configuration.

This is the single source of truth for:
- product identity
- conversational assistant name
- wake word
- company
- user-relationship rules

Every subsystem should import from here instead of hardcoding
assistant names, wake words, or creator text.
"""

from __future__ import annotations

import logging
from typing import Optional

import config

logger = logging.getLogger("vyren.identity")

# Permanent product identity
PRODUCT_NAME = "Vyren"
COMPANY = "Omniel"

# Default conversational identity before any user rename.
_DEFAULT_ASSISTANT_NAME = "Vyren"

# Config keys
_CFG_ASSISTANT_NAME = "identity.assistant_name"
_CFG_COMPANY = "identity.company"
_CFG_ALIASES = "identity.aliases"


def get_assistant_name() -> str:
    """Return the user-facing conversational name for VYREN.

    This is the name VYREN should use in speech, greetings, and
    conversational replies. It defaults to ``Vyren`` and can be
    changed via ``config.yaml`` or the rename flow.
    """
    return config.get(_CFG_ASSISTANT_NAME, _DEFAULT_ASSISTANT_NAME) or _DEFAULT_ASSISTANT_NAME


def get_product_name() -> str:
    """Return the permanent product name. Always ``Vyren``."""
    return PRODUCT_NAME


def get_company() -> str:
    """Return the owning company. Defaults to ``Omniel``."""
    return config.get(_CFG_COMPANY, COMPANY) or COMPANY


def get_wake_word() -> str:
    """Return the current wake word derived from the assistant name.

    The configured assistant name automatically becomes the wake word.
    """
    name = get_assistant_name()
    wake = name.strip().split()[0] if name.strip() else _DEFAULT_ASSISTANT_NAME
    return wake.lower()


def get_aliases() -> list[str]:
    """Return alternate accepted names for the configured assistant."""
    raw = config.get(_CFG_ALIASES, [])
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def is_identity_query(text: str) -> bool:
    """Best-effort detection for identity-related user questions."""
    t = (text or "").lower()
    triggers = [
        "your name",
        "who are you",
        "what are you",
        "real name",
        "product name",
        "company",
        "who made you",
        "who created you",
        "who owns you",
        "your real name",
        "wake word",
    ]
    return any(t in t for t in triggers)


def build_identity_response(user_question: str, *, assistant_name: Optional[str] = None) -> str:
    """Return a concise identity answer consistent with VYREN's rules.

    Rules:
    - "What is your name?" -> configured assistant name
    - "What is your real name?" -> product name + configured name
    - Creator/owner questions -> Omniel
    """
    q = (user_question or "").lower()
    name = assistant_name if assistant_name is not None else get_assistant_name()
    product = get_product_name()
    company = get_company()

    if "real name" in q or "product name" in q:
        if name.lower() == product.lower():
            return f"My name is {product}."
        return f"My product name is {product}, but you've chosen to call me {name}."

    if any(k in q for k in ["who are you", "what are you", "your name"]):
        return f"I'm {name}."

    if any(k in q for k in ["company", "who made you", "who created you", "who owns you"]):
        return f"I was developed by {company}."

    return f"I'm {name}, {company}'s specialist AI."


def set_assistant_name(name: str, save: bool = True) -> str:
    """Persist a new conversational identity.

    Returns the final effective assistant name after normalization.
    """
    cleaned = (name or "").strip() or _DEFAULT_ASSISTANT_NAME
    try:
        cfg_path = config._find_config()
        import yaml
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        cfg.setdefault("identity", {})
        cfg["identity"]["assistant_name"] = cleaned
        if save:
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, sort_keys=False)
        config._config = None
    except Exception as e:
        logger.debug("Could not persist assistant name: %s", e)
    return cleaned
