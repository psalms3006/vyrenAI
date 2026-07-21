"""boot/ -- VYREN Boot Manager package.

Responsible for the ordered, dependency-aware initialization of every
subsystem in the VYREN AI operating system.  main.py invokes the
BootManager; it handles the rest.
"""

from boot.manager import BootManager

__all__ = ["BootManager"]