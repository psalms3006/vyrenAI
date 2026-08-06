"""
camera/_optional.py -- Optional dependency handling for the camera package.

Provides:
- OptionalDependencyError
- optional_import(module_name)
"""

from __future__ import annotations


class OptionalDependencyError(ImportError):
    """Raised when an optional dependency is unavailable."""
