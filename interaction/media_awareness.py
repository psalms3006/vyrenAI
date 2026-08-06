"""
interaction/media_awareness.py -- VYREN's media and context awareness layer.

Detects when the user is engaged with media or productivity contexts
where interruption should be suppressed or limited.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger("vyren.interaction.media")


@dataclass
class MediaAwareness:
    """
    Media awareness policy and signal providers.

    Media states:
      - full_screen_app: fullscreen game/video/app
      - audio_active: system audio above threshold
      - meeting_active: virtual meeting indicator
      - screen_sharing: user is sharing screen
      - recording: user is recording audio/video
    """

    detector: Optional[Callable[[], dict[str, bool]]] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _signals: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._signals = {
            "full_screen_app": False,
            "audio_active": False,
            "meeting_active": False,
            "screen_sharing": False,
            "recording": False,
        }

    def set_detector(self, detector: Callable[[], dict[str, bool]]) -> None:
        self.detector = detector

    def refresh(self) -> dict[str, bool]:
        if self.detector is None:
            return dict(self._signals)
        try:
            updates = self.detector()
        except Exception:
            updates = {}
        with self._lock:
            for key in self._signals:
                if key in updates:
                    self._signals[key] = bool(updates[key])
        return dict(self._signals)

    def signals(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._signals)

    def is_user_busy(self) -> bool:
        s = self.signals()
        return (
            s.get("full_screen_app", False)
            or s.get("meeting_active", False)
            or s.get("screen_sharing", False)
            or s.get("recording", False)
            or bool(s.get("audio_active", False))
        )

    def set_signal(self, key: str, value: bool) -> None:
        with self._lock:
            if key in self._signals:
                self._signals[key] = bool(value)
