"""runtime/ -- VYREN Runtime Manager package.

Manages the full lifecycle of the VYREN AI operating system:
always-on operation, process supervision, service discovery,
graceful shutdown, and auto-restart.
"""

from runtime.manager import RuntimeManager

__all__ = ["RuntimeManager"]