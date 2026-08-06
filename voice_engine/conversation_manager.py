"""
voice_engine/conversation_manager.py -- Conversation lifecycle manager.

States:
    IDLE
    LISTENING
    THINKING
    SPEAKING
    INTERRUPTED
    RECONNECTING

Every transition is logged. This is the single source of truth for
conversation phase; the engine's lower-level FSM handles transport/worker
state, but the human-facing conversation phase lives here.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger("vyren.voice.conversation_manager")


class ConversationPhase:
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    RECONNECTING = "reconnecting"


_VALID_TRANSITIONS: dict[str, set[str]] = {
    ConversationPhase.IDLE: {ConversationPhase.LISTENING, ConversationPhase.RECONNECTING},
    ConversationPhase.LISTENING: {
        ConversationPhase.THINKING,
        ConversationPhase.SPEAKING,
        ConversationPhase.INTERRUPTED,
        ConversationPhase.RECONNECTING,
        ConversationPhase.IDLE,
    },
    ConversationPhase.THINKING: {
        ConversationPhase.SPEAKING,
        ConversationPhase.LISTENING,
        ConversationPhase.INTERRUPTED,
        ConversationPhase.RECONNECTING,
        ConversationPhase.IDLE,
    },
    ConversationPhase.SPEAKING: {
        ConversationPhase.LISTENING,
        ConversationPhase.INTERRUPTED,
        ConversationPhase.RECONNECTING,
        ConversationPhase.IDLE,
    },
    ConversationPhase.INTERRUPTED: {
        ConversationPhase.LISTENING,
        ConversationPhase.THINKING,
        ConversationPhase.RECONNECTING,
        ConversationPhase.IDLE,
    },
    ConversationPhase.RECONNECTING: {
        ConversationPhase.LISTENING,
        ConversationPhase.IDLE,
    },
}


@dataclass
class ConversationManager:
    """
    Owns the human-facing conversation lifecycle.

    It does not touch audio directly. It tracks phase, timing, and
    transition history so supervisors and UI can reason about what the
    user/assistant is doing right now.
    """

    clock: Callable[[], float] = time.monotonic
    _state: str = field(default=ConversationPhase.IDLE, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _transition_count: int = field(default=0, init=False)
    _rejected_count: int = field(default=0, init=False)
    _history: list[tuple[str, str, float]] = field(default_factory=list, init=False)
    _on_change: Optional[Callable[[str], None]] = field(default=None, init=False, repr=False)
    _listening_since: Optional[float] = field(default=None, init=False, repr=False)
    _speaking_since: Optional[float] = field(default=None, init=False, repr=False)
    _last_user_speech_ts: Optional[float] = field(default=None, init=False, repr=False)
    _last_model_speech_ts: Optional[float] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._history = []

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def transition_count(self) -> int:
        with self._lock:
            return self._transition_count

    @property
    def rejected_count(self) -> int:
        with self._lock:
            return self._rejected_count

    @property
    def history(self) -> list[tuple[str, str, float]]:
        with self._lock:
            return list(self._history[-200:])

    @property
    def is_listening(self) -> bool:
        return self.state == ConversationPhase.LISTENING

    @property
    def is_speaking(self) -> bool:
        return self.state == ConversationPhase.SPEAKING

    @property
    def is_idle(self) -> bool:
        return self.state == ConversationPhase.IDLE

    @property
    def is_interrupted(self) -> bool:
        return self.state == ConversationPhase.INTERRUPTED

    @property
    def is_reconnecting(self) -> bool:
        return self.state == ConversationPhase.RECONNECTING

    def set_on_change(self, callback: Optional[Callable[[str], None]]) -> None:
        self._on_change = callback

    def note_user_speech(self) -> None:
        with self._lock:
            self._last_user_speech_ts = self.clock()

    def note_model_speech(self) -> None:
        with self._lock:
            self._last_model_speech_ts = self.clock()

    def time_since_user_speech(self) -> Optional[float]:
        with self._lock:
            if self._last_user_speech_ts is None:
                return None
            return self.clock() - self._last_user_speech_ts

    def time_since_model_speech(self) -> Optional[float]:
        with self._lock:
            if self._last_model_speech_ts is None:
                return None
            return self.clock() - self._last_model_speech_ts

    def transition(self, new_state: str, reason: str = "") -> bool:
        """
        Attempt a phase transition.

        Returns True on success. Illegal transitions are rejected and logged.
        """
        if new_state not in _VALID_TRANSITIONS:
            logger.error("[CONV] Unknown target state: %r", new_state)
            return False

        with self._lock:
            old_state = self._state
            if old_state == new_state:
                return True

            allowed = _VALID_TRANSITIONS.get(old_state, set())
            if new_state not in allowed:
                self._rejected_count += 1
                logger.warning(
                    "[CONV] Rejected transition %s -> %s: %s",
                    old_state,
                    new_state,
                    reason or "not allowed",
                )
                return False

            self._history.append((old_state, new_state, self.clock()))
            if len(self._history) > 500:
                self._history = self._history[-500:]
            self._state = new_state
            self._transition_count += 1

            now = self.clock()
            if new_state == ConversationPhase.LISTENING:
                self._listening_since = now
            elif new_state == ConversationPhase.SPEAKING:
                self._speaking_since = now

        logger.info("[CONV] %s -> %s%s", old_state, new_state, f" ({reason})" if reason else "")
        try:
            if self._on_change:
                self._on_change(new_state)
        except Exception:
            pass
        return True

    def reset(self) -> None:
        with self._lock:
            self._state = ConversationPhase.IDLE
            self._transition_count = 0
            self._rejected_count = 0
            self._history = []
            self._listening_since = None
            self._speaking_since = None
            self._last_user_speech_ts = None
            self._last_model_speech_ts = None

    def status(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "transition_count": self._transition_count,
                "rejected_count": self._rejected_count,
                "listening_since": self._listening_since,
                "speaking_since": self._speaking_since,
                "last_user_speech_ts": self._last_user_speech_ts,
                "last_model_speech_ts": self._last_model_speech_ts,
            }
