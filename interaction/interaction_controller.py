"""
interaction/interaction_controller.py -- VYREN's interaction and attention controller.

This is the central authority for whether VYREN may:
  - speak
  - interrupt
  - accept wake-word activation
  - transition conversation state

It is NOT a patch on top of existing behavior. It replaces implicit,
scattered decisions with one explicit policy.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from interaction.conversation_state import (
    ACTIVE_CONVERSATION,
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
)


@dataclass
class UserMode:
    """
    User-facing modes that shape interaction policy.

    Each mode is a constraint set, not a state.
    """

    mode_id: str
    priority: int = 0
    allow_wake_word: bool = True
    allow_interrupt_for_normal: bool = False
    allow_interrupt_for_media: bool = False
    auto_conversation_timeout_seconds: Optional[float] = None
    description: str = ""

    def allows(self, notification_priority: str, media_active: bool = False) -> bool:
        if notification_priority == "critical":
            return True
        if media_active:
            return False
        if notification_priority == "normal":
            return self.allow_interrupt_for_normal
        return False


# User modes.
USER_MODES: dict[str, UserMode] = {
    "silent": UserMode(
        mode_id="silent",
        priority=10,
        allow_wake_word=True,
        allow_interrupt_for_normal=False,
        allow_interrupt_for_media=False,
        auto_conversation_timeout_seconds=300,
        description="Never speak unless spoken to.",
    ),
    "hands_free": UserMode(
        mode_id="hands_free",
        priority=8,
        allow_wake_word=True,
        allow_interrupt_for_normal=False,
        allow_interrupt_for_media=False,
        auto_conversation_timeout_seconds=600,
        description="Wake word only.",
    ),
    "conversation": UserMode(
        mode_id="conversation",
        priority=5,
        allow_wake_word=True,
        allow_interrupt_for_normal=True,
        allow_interrupt_for_media=True,
        auto_conversation_timeout_seconds=None,
        description="Freely converse while active.",
    ),
    "meeting": UserMode(
        mode_id="meeting",
        priority=9,
        allow_wake_word=False,
        allow_interrupt_for_normal=False,
        allow_interrupt_for_media=False,
        auto_conversation_timeout_seconds=60,
        description="Never interrupt.",
    ),
    "movie": UserMode(
        mode_id="movie",
        priority=9,
        allow_wake_word=False,
        allow_interrupt_for_normal=False,
        allow_interrupt_for_media=False,
        auto_conversation_timeout_seconds=60,
        description="Never interrupt.",
    ),
    "gaming": UserMode(
        mode_id="gaming",
        priority=9,
        allow_wake_word=False,
        allow_interrupt_for_normal=False,
        allow_interrupt_for_media=False,
        auto_conversation_timeout_seconds=60,
        description="Never interrupt.",
    ),
    "sleep": UserMode(
        mode_id="sleep",
        priority=11,
        allow_wake_word=False,
        allow_interrupt_for_normal=False,
        allow_interrupt_for_media=False,
        auto_conversation_timeout_seconds=30,
        description="Remain silent.",
    ),
    "focus": UserMode(
        mode_id="focus",
        priority=9,
        allow_wake_word=True,
        allow_interrupt_for_normal=False,
        allow_interrupt_for_media=False,
        auto_conversation_timeout_seconds=120,
        description="Interrupt only for critical events.",
    ),
}


@dataclass
class InteractionController:
    """
    Central attention/interruption authority.

    Usage:
        controller = InteractionController(state_machine, config)
        if controller.may_speak():
            ...

    Policy is driven by:
      - conversation state
      - current user mode
      - media awareness signal
      - notification priority
    """

    state_machine: ConversationStateMachine
    config: dict[str, Any]
    media_detector: Optional[Callable[[], bool]] = None
    clock: Callable[[], float] = time.monotonic

    _active_mode: UserMode = field(default_factory=lambda: USER_MODES["silent"])
    _media_active: bool = False
    _pending_normal_notifications: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _conversation_start_ts: Optional[float] = None
    _last_user_activity_ts: Optional[float] = None
    _notify: Optional[Callable[[str], None]] = None

    def __post_init__(self) -> None:
        self._pending_normal_notifications = []
        self._conversation_start_ts = None
        self._last_user_activity_ts = None

    # ------------------------------------------------------------------
    # External hooks
    # ------------------------------------------------------------------

    def set_notify(self, notify: Callable[[str], None]) -> None:
        self._notify = notify

    def set_media_detector(self, detector: Callable[[], bool]) -> None:
        self._media_detector = detector

    def set_user_mode(self, mode_id: str) -> None:
        mode = USER_MODES.get(mode_id)
        if mode is None:
            return
        with self._lock:
            self._active_mode = mode

    def note_user_activity(self) -> None:
        with self._lock:
            self._last_user_activity_ts = self.clock()

    def start_conversation(self) -> None:
        with self._lock:
            self._conversation_start_ts = self.clock()
            self._last_user_activity_ts = self.clock()

    def end_conversation(self) -> None:
        with self._lock:
            self._conversation_start_ts = None
            self._last_user_activity_ts = None

    # ------------------------------------------------------------------
    # Media awareness
    # ------------------------------------------------------------------

    def is_media_active(self) -> bool:
        if self._media_active:
            return True
        if self.media_detector is None:
            return False
        try:
            return bool(self.media_detector())
        except Exception:
            return False

    def set_media_active(self, active: bool) -> None:
        self._media_active = bool(active)

    # ------------------------------------------------------------------
    # Speech/interruption policy
    # ------------------------------------------------------------------

    def may_speak(self, notification_priority: str = "normal") -> bool:
        """
        Return True only when VYREN has permission to produce speech.
        """
        with self._lock:
            state = self.state_machine.state
            mode = self._active_mode
            media = self.is_media_active()

        # Critical notifications override quiet states.
        if notification_priority == "critical":
            return not self.state_machine.is_quiet()

        if self.state_machine.is_quiet():
            return False

        if not self.state_machine.is_active_conversation() and self.state_machine.state not in (
            SPEAKING,
            THINKING,
            INTERRUPTED,
            AWAITING_WAKE_WORD,
            PASSIVE_LISTENING,
        ):
            return False

        if media:
            return False

        if mode.mode_id in ("meeting", "movie", "gaming", "sleep"):
            return False
        if mode.mode_id == "focus":
            return notification_priority == "critical"
        if mode.mode_id == "silent":
            return notification_priority == "critical"
        if mode.mode_id == "hands_free":
            return True
        return notification_priority == "normal"

    def may_interrupt(self, notification_priority: str = "normal") -> bool:
        """
        Return True only when VYREN may interrupt current speech.
        """
        with self._lock:
            state = self.state_machine.state
            mode = self._active_mode
            media = self.is_media_active()

        if notification_priority == "critical":
            return self.state_machine.is_speaking()

        if not self.state_machine.is_speaking():
            return False

        if media:
            return False

        if mode.mode_id == "conversation":
            return True
        if mode.mode_id == "focus":
            return False
        return False

    def may_activate(self) -> bool:
        """
        Wake word / push-to-talk / text activation policy.
        """
        with self._lock:
            state = self.state_machine.state
            mode = self._active_mode
            media = self.is_media_active()

        if state == DO_NOT_DISTURB:
            return False
        if state == SLEEP:
            return False
        if not mode.allow_wake_word:
            return False
        if media and mode.mode_id not in ("silent", "focus"):
            return False
        return self.state_machine.is_listening()

    def on_wake_word_detected(self) -> None:
        if not self.may_activate():
            return
        if self.state_machine.transition(ACTIVE_CONVERSATION, reason="wake_word"):
            self.start_conversation()

    def on_user_input(self) -> None:
        if self.state_machine.transition(ACTIVE_CONVERSATION, reason="user_input"):
            self.start_conversation()
        self.note_user_activity()

    def on_speak_done(self) -> None:
        """
        After speaking finishes, decide whether to stay active or timeout.
        """
        with self._lock:
            mode = self._active_mode
            timeout = mode.auto_conversation_timeout_seconds
            start = self._conversation_start_ts
            last = self._last_user_activity_ts

        if timeout is None or start is None or last is None:
            target = PASSIVE_LISTENING
        else:
            idle = self.clock() - last
            if idle > timeout:
                target = PASSIVE_LISTENING
            else:
                target = ACTIVE_CONVERSATION
                self.state_machine.transition(target, reason="post_speak_active")

        if target != ACTIVE_CONVERSATION:
            self.state_machine.transition(target, reason="conversation_timeout")
            self.end_conversation()

    def on_user_activity(self) -> None:
        self.note_user_activity()
        if not self.state_machine.is_active_conversation():
            self.state_machine.transition(ACTIVE_CONVERSATION, reason="user_activity")
            self.start_conversation()

    def on_notification(self, payload: dict[str, Any]) -> bool:
        """
        Route a notification.

        Critical notifications may interrupt immediately.
        Normal notifications are queued and delivered on next interaction.
        Returns True if notification was delivered now.
        """
        priority = str(payload.get("priority", "normal")).lower()
        with self._lock:
            if priority == "critical":
                if self.may_interrupt("critical"):
                    return True
                return False
            if priority == "normal":
                if self.may_speak("normal"):
                    return True
                self._pending_normal_notifications.append(payload)
                if len(self._pending_normal_notifications) > 200:
                    self._pending_normal_notifications = self._pending_normal_notifications[-200:]
                return False
            return False

    def drain_pending_notifications(self) -> list[dict[str, Any]]:
        with self._lock:
            pending = self._pending_normal_notifications
            self._pending_normal_notifications = []
            return list(pending)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self.state_machine.state.value,
                "mode": self._active_mode.mode_id,
                "media_active": self.is_media_active(),
                "pending_notifications": len(self._pending_normal_notifications),
                "conversation_active": self.state_machine.is_active_conversation(),
            }
