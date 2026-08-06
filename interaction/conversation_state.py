"""
interaction/conversation_state.py -- VYREN's conversation state machine.

States and transitions are explicit. Every speech/interruption decision
flows through this module; nothing speaks without permission.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class ConversationState(str, Enum):
    OFF = "off"
    BACKGROUND = "background"
    PASSIVE_LISTENING = "passive_listening"
    AWAITING_WAKE_WORD = "awaiting_wake_word"
    ACTIVE_CONVERSATION = "active_conversation"
    SPEAKING = "speaking"
    THINKING = "thinking"
    INTERRUPTED = "interrupted"
    DO_NOT_DISTURB = "do_not_disturb"
    SLEEP = "sleep"


# Explicit transition table.
# Format: source -> set of legal targets.
VALID_TRANSITIONS: dict[ConversationState, set[ConversationState]] = {
    ConversationState.OFF: {
        ConversationState.BACKGROUND,
    },
    ConversationState.BACKGROUND: {
        ConversationState.PASSIVE_LISTENING,
        ConversationState.SLEEP,
        ConversationState.OFF,
    },
    ConversationState.PASSIVE_LISTENING: {
        ConversationState.AWAITING_WAKE_WORD,
        ConversationState.BACKGROUND,
        ConversationState.SLEEP,
        ConversationState.OFF,
    },
    ConversationState.AWAITING_WAKE_WORD: {
        ConversationState.ACTIVE_CONVERSATION,
        ConversationState.PASSIVE_LISTENING,
        ConversationState.SLEEP,
        ConversationState.OFF,
    },
    ConversationState.ACTIVE_CONVERSATION: {
        ConversationState.SPEAKING,
        ConversationState.THINKING,
        ConversationState.PASSIVE_LISTENING,
        ConversationState.SLEEP,
        ConversationState.OFF,
    },
    ConversationState.SPEAKING: {
        ConversationState.THINKING,
        ConversationState.INTERRUPTED,
        ConversationState.SLEEP,
        ConversationState.OFF,
    },
    ConversationState.THINKING: {
        ConversationState.SPEAKING,
        ConversationState.INTERRUPTED,
        ConversationState.ACTIVE_CONVERSATION,
        ConversationState.PASSIVE_LISTENING,
        ConversationState.SLEEP,
        ConversationState.OFF,
    },
    ConversationState.INTERRUPTED: {
        ConversationState.THINKING,
        ConversationState.SPEAKING,
        ConversationState.ACTIVE_CONVERSATION,
        ConversationState.PASSIVE_LISTENING,
        ConversationState.SLEEP,
        ConversationState.OFF,
    },
    ConversationState.DO_NOT_DISTURB: {
        ConversationState.BACKGROUND,
        ConversationState.PASSIVE_LISTENING,
        ConversationState.SLEEP,
        ConversationState.OFF,
    },
    ConversationState.SLEEP: {
        ConversationState.BACKGROUND,
        ConversationState.OFF,
    },
}


@dataclass
class ConversationStateMachine:
    """
    Thread-safe conversation state machine with validation and hooks.

    All transitions are validated against VALID_TRANSITIONS.
    Invalid transitions are logged and rejected.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _state: ConversationState = ConversationState.OFF
    _last_transition_ts: float = field(default_factory=time.monotonic)
    _transition_count: int = 0
    _rejected_count: int = 0
    _history: list[tuple[ConversationState, ConversationState, float]] = field(
        default_factory=list
    )
    _on_enter: Optional[Callable[[ConversationState], None]] = None
    _on_exit: Optional[Callable[[ConversationState], None]] = None

    def __post_init__(self) -> None:
        self._history: list[tuple[ConversationState, ConversationState, float]] = []

    @property
    def state(self) -> ConversationState:
        with self._lock:
            return self._state

    @property
    def last_transition_ts(self) -> float:
        with self._lock:
            return self._last_transition_ts

    @property
    def transition_count(self) -> int:
        with self._lock:
            return self._transition_count

    @property
    def rejected_count(self) -> int:
        with self._lock:
            return self._rejected_count

    @property
    def history(self) -> list[tuple[ConversationState, ConversationState, float]]:
        with self._lock:
            return list(self._history[-100:])

    def set_callbacks(
        self,
        on_enter: Optional[Callable[[ConversationState], None]] = None,
        on_exit: Optional[Callable[[ConversationState], None]] = None,
    ) -> None:
        self._on_enter = on_enter
        self._on_exit = on_exit

    def transition(self, new_state: ConversationState, reason: str = "") -> bool:
        """
        Attempt to transition to `new_state`.

        Returns True on success, False if the transition is illegal.
        """
        with self._lock:
            old_state = self._state
            if old_state == new_state:
                return True  # idempotent no-op

            allowed = VALID_TRANSITIONS.get(old_state, set())
            if new_state not in allowed:
                self._rejected_count += 1
                return False

            self._history.append((old_state, new_state, time.monotonic()))
            if len(self._history) > 200:
                self._history = self._history[-200:]
            self._state = new_state
            self._last_transition_ts = time.monotonic()
            self._transition_count += 1

        # Callbacks outside the lock to avoid reentrancy surprises.
        try:
            if self._on_exit:
                self._on_exit(old_state)
        except Exception:
            pass
        try:
            if self._on_enter:
                self._on_enter(new_state)
        except Exception:
            pass

        return True

    def can_transition(self, target: ConversationState) -> bool:
        with self._lock:
            return target in VALID_TRANSITIONS.get(self._state, set())

    def is_speaking(self) -> bool:
        return self.state in (
            ConversationState.SPEAKING,
            ConversationState.THINKING,
            ConversationState.INTERRUPTED,
        )

    def is_active_conversation(self) -> bool:
        return self.state in (
            ConversationState.ACTIVE_CONVERSATION,
            ConversationState.SPEAKING,
            ConversationState.THINKING,
            ConversationState.INTERRUPTED,
        )

    def is_listening(self) -> bool:
        return self.state in (
            ConversationState.PASSIVE_LISTENING,
            ConversationState.AWAITING_WAKE_WORD,
            ConversationState.ACTIVE_CONVERSATION,
        )

    def is_quiet(self) -> bool:
        return self.state in (
            ConversationState.OFF,
            ConversationState.BACKGROUND,
            ConversationState.SLEEP,
            ConversationState.DO_NOT_DISTURB,
        )

    def reset(self) -> None:
        with self._lock:
            self._state = ConversationState.OFF
            self._last_transition_ts = time.monotonic()
            self._transition_count = 0
            self._rejected_count = 0
            self._history = []


# Convenience aliases
OFF = ConversationState.OFF
BACKGROUND = ConversationState.BACKGROUND
PASSIVE_LISTENING = ConversationState.PASSIVE_LISTENING
AWAITING_WAKE_WORD = ConversationState.AWAITING_WAKE_WORD
ACTIVE_CONVERSATION = ConversationState.ACTIVE_CONVERSATION
SPEAKING = ConversationState.SPEAKING
THINKING = ConversationState.THINKING
INTERRUPTED = ConversationState.INTERRUPTED
DO_NOT_DISTURB = ConversationState.DO_NOT_DISTURB
SLEEP = ConversationState.SLEEP
