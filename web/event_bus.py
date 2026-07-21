"""
event_bus.py — Central event bus for VYREN's event-driven architecture.

Every subsystem publishes and subscribes to structured events. This is the
nervous system of VYREN — it decouples modules so they can react to changes
without knowing about each other.

Events are typed dicts with at minimum: type, source, timestamp, data.
Subscribers are async callables matched by event type (with wildcard support).

Thread-safe. Supports both sync and async handlers.
"""

import asyncio
import json
import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine
from pathlib import Path

logger = logging.getLogger("vyren.events")

# ---------------------------------------------------------------------------
# Event structure
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """A structured event in the VYREN system."""
    type: str                          # e.g. "file.created", "battery.low"
    source: str                        # module that published (e.g. "filesystem_watcher")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: dict = field(default_factory=dict)
    priority: int = 5                  # 1=highest, 10=lowest
    id: str = field(default_factory=lambda: f"evt_{int(time.time()*1000)}_{id(object())}")

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None and v != ""}


# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------

class EventBus:
    """
    Central publish/subscribe event bus.

    Usage:
        bus = EventBus()

        # Subscribe
        bus.subscribe("file.*", my_handler)
        bus.subscribe("battery.low", alert_handler)

        # Publish
        await bus.publish(Event(type="file.created", source="watcher", data={"path": "/tmp/x"}))

    Handlers can be sync or async. The bus dispatches in order of priority.
    """

    def __init__(self, max_history: int = 1000):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._history: list[Event] = []
        self._max_history = max_history
        self._lock = threading.Lock()
        self._async_handlers: set = set()  # Track which are async
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, pattern: str, handler: Callable) -> None:
        """Subscribe a handler to events matching a pattern.

        Patterns support simple glob: 'file.*' matches 'file.created', 'file.deleted', etc.
        Use '*' to match all events.
        """
        with self._lock:
            if handler not in self._subscribers[pattern]:
                self._subscribers[pattern].append(handler)
                if asyncio.iscoroutinefunction(handler):
                    self._async_handlers.add(handler)
                else:
                    self._async_handlers.discard(handler)
        logger.debug(f"Subscribed {handler.__name__} to '{pattern}'")

    def unsubscribe(self, pattern: str, handler: Callable) -> None:
        """Remove a handler from a pattern."""
        with self._lock:
            if pattern in self._subscribers:
                try:
                    self._subscribers[pattern].remove(handler)
                except ValueError:
                    pass

    def _matches(self, pattern: str, event_type: str) -> bool:
        """Check if an event type matches a subscription pattern."""
        if pattern == "*":
            return True
        if pattern == event_type:
            return True
        # Simple glob: 'file.*' matches 'file.anything'
        if pattern.endswith(".*"):
            prefix = pattern[:-1]  # 'file.'
            return event_type.startswith(prefix)
        return False

    def _get_handlers(self, event_type: str) -> list[Callable]:
        """Get all handlers matching an event type, sorted by pattern specificity."""
        handlers = []
        with self._lock:
            for pattern, handler_list in self._subscribers.items():
                if self._matches(pattern, event_type):
                    # More specific patterns first (exact > wildcard > glob)
                    specificity = 0
                    if pattern == event_type:
                        specificity = 3
                    elif ".*" in pattern:
                        specificity = 2
                    elif pattern == "*":
                        specificity = 1
                    for h in handler_list:
                        handlers.append((specificity, h))

        # Sort: higher specificity first, then insertion order
        handlers.sort(key=lambda x: -x[0])
        return [h for _, h in handlers]

    def publish_sync(self, event: Event) -> list:
        """Publish an event synchronously. Returns list of (handler, result) pairs."""
        handlers = self._get_handlers(event.type)
        results = []

        # Store in history
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    # Can't await in sync context — schedule on event loop
                    if self._loop and self._loop.is_running():
                        self._loop.create_task(self._safe_async_call(handler, event))
                    else:
                        logger.warning(f"Async handler {handler.__name__} skipped (no event loop)")
                    results.append((handler, None))
                else:
                    result = handler(event)
                    results.append((handler, result))
            except Exception as e:
                logger.error(f"Event handler {handler.__name__} failed: {e}")
                results.append((handler, None))

        return results

    async def publish(self, event: Event) -> list:
        """Publish an event asynchronously. Awaits async handlers."""
        handlers = self._get_handlers(event.type)
        results = []

        # Store in history
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(event)
                else:
                    result = handler(event)
                results.append((handler, result))
            except Exception as e:
                logger.error(f"Event handler {handler.__name__} failed: {e}")
                results.append((handler, None))

        return results

    async def _safe_async_call(self, handler, event):
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Async handler {handler.__name__} failed: {e}")

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """Set the event loop for dispatching async handlers from sync context."""
        self._loop = loop

    @property
    def history(self) -> list[Event]:
        return list(self._history)

    def get_history(self, event_type: str | None = None, limit: int = 50) -> list[dict]:
        """Get recent events, optionally filtered by type."""
        events = self._history
        if event_type:
            events = [e for e in events if e.type == event_type]
        return [e.to_dict() for e in events[-limit:]]

    def subscriber_count(self) -> dict[str, int]:
        """Return count of subscribers per pattern."""
        with self._lock:
            return {p: len(h) for p, h in self._subscribers.items() if h}

    def clear_subscribers(self):
        """Remove all subscribers. Used during shutdown."""
        with self._lock:
            self._subscribers.clear()
            self._async_handlers.clear()


# ---------------------------------------------------------------------------
# Standard Event Types
# ---------------------------------------------------------------------------

# File system events
FILE_CREATED = "file.created"
FILE_MODIFIED = "file.modified"
FILE_DELETED = "file.deleted"

# System events
SYSTEM_CPU_HIGH = "system.cpu_high"
SYSTEM_MEMORY_HIGH = "system.memory_high"
SYSTEM_DISK_LOW = "system.disk_low"
SYSTEM_BATTERY_LOW = "system.battery_low"
SYSTEM_BATTERY_CRITICAL = "system.battery_critical"
SYSTEM_NETWORK_CHANGE = "system.network_change"
SYSTEM_USB_INSERTED = "system.usb_inserted"
SYSTEM_USB_REMOVED = "system.usb_removed"

# User events
USER_ARRIVED = "user.arrived"
USER_LEFT = "user.left"
USER_IDLE = "user.idle"
USER_ACTIVE = "user.active"

# Application events
APP_LAUNCHED = "app.launched"
APP_CLOSED = "app.closed"
APP_FOCUSED = "app.focused"

# Browser events
BROWSER_DOWNLOAD_DONE = "browser.download_completed"
BROWSER_TAB_CHANGED = "browser.tab_changed"

# VYREN internal events
VYREN_TOOL_CALLED = "vyren.tool_called"
VYREN_TOOL_RESULT = "vyren.tool_result"
VYREN_MEMORY_UPDATED = "vyren.memory_updated"
VYREN_PLAN_CREATED = "vyren.plan_created"
VYREN_PLAN_PROGRESS = "vyren.plan_progress"
VYREN_SECURITY_ALERT = "vyren.security_alert"
VYREN_ERROR = "vyren.error"
VYREN_STARTED = "vyren.started"
VYREN_SHUTDOWN = "vyren.shutdown"

# Calendar / schedule
CALENDAR_REMINDER = "calendar.reminder"
SCHEDULED_JOB_DUE = "scheduler.job_due"
SCHEDULED_JOB_DONE = "scheduler.job_completed"
SCHEDULED_JOB_FAILED = "scheduler.job_failed"

# Security
SECURITY_ANOMALY = "security.anomaly"
SECURITY_PERMISSION_DENIED = "security.permission_denied"

# Dev events
GIT_COMMIT = "dev.git_commit"
GIT_BRANCH_CHANGE = "dev.git_branch_change"
BUILD_STARTED = "dev.build_started"
BUILD_COMPLETED = "dev.build_completed"
BUILD_FAILED = "dev.build_failed"