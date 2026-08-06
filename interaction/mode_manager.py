"""
interaction/mode_manager.py -- VYREN's mode management.

Provides a focused interface for setting and querying the current user mode.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

from interaction.interaction_controller import USER_MODES, UserMode

logger = logging.getLogger("vyren.interaction.modes")


@dataclass
class ModeManager:
    controller: object = None  # InteractionController

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _current: Optional[UserMode] = None

    def __post_init__(self) -> None:
        self._current = USER_MODES["silent"]

    def set_mode(self, mode_id: str) -> Optional[UserMode]:
        mode = USER_MODES.get(mode_id)
        if mode is None:
            logger.warning("Unknown mode: %s", mode_id)
            return None
        with self._lock:
            self._current = mode
        try:
            if self.controller is not None:
                self.controller.set_user_mode(mode_id)
        except Exception:
            pass
        logger.info("Mode changed -> %s", mode_id)
        return mode

    def get_mode(self) -> Optional[UserMode]:
        with self._lock:
            return self._current

    def current_mode_id(self) -> str:
        with self._lock:
            return self._current.mode_id if self._current else "silent"
