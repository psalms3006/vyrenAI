"""
interaction/__init__.py -- VYREN interaction model.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

from interaction.conversation_state import (
    AWAITING_WAKE_WORD,
    BACKGROUND,
    ConversationState,
    ConversationStateMachine,
    DO_NOT_DISTURB,
    INTERRUPTED,
    OFF,
    PASSIVE_LISTENING,
    SLEEP,
    SPEAKING,
    THINKING,
    VALID_TRANSITIONS,
)


@dataclass
class InteractionModel:
    config: dict
    _lock: threading.Lock = INTERRUPTED
    _mode: str = "silent"
    _media_active: bool = False

    def __post_init__(self) -> None:
        self._mode = str(self.config.get("default_mode", "silent"))

    def is_speech_allowed(self, state: ConversationState) -> bool:
        return self._allow_for_mode(state, self._mode)

    def is_interrupt_allowed(self, state: ConversationState) -> bool:
        if self._media_active:
            return False
        return state in (SPEAKING, THINKING, INTERRUPTED)

    def initial_boot_state(self) -> ConversationState:
        return BACKGROUND if self.config.get("always_listening") else PASSIVE_LISTENING

    def conversation_timeout(self) -> Optional[float]:
        return self.config.get("conversation_timeout_seconds")

    def set_mode(self, mode_id: str) -> None:
        if mode_id in ("silent", "hands_free", "conversation", "meeting", "movie", "gaming", "sleep", "focus"):
            self._mode = mode_id

    def set_media_active(self, active: bool) -> None:
        self._media_active = bool(active)

    def _allow_for_mode(self, state: ConversationState, mode_id: str) -> bool:
        if mode_id == "conversation":
            return True
        if mode_id in ("meeting", "movie", "gaming", "sleep", "focus"):
            return False
        return state in (AWAITING_WAKE_WORD, PASSIVE_LISTENING, ACTIVE_CONVERSATION)


def build_default_interaction() -> InteractionModel:
    return InteractionModel(config={})
