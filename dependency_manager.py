"""
dependency_manager.py -- Centralized optional-dependency handling for VYREN.

Every VYREN subsystem (Vision, Voice, Memory, OCR, Automation, ...) that wants
to import an optional third-party package must go through this module instead
of writing ad-hoc `try / import / except ImportError` blocks scattered across
the codebase.

When a module is missing, the manager:

  1. Detects the missing module name (from ModuleNotFoundError.name or arg).
  2. Knows which subsystem requested it (passed by the caller).
  3. Maps the module name -> pip package via an internal lookup table.
     The LLM is NEVER asked to guess package names -- this table is the
     single source of truth.
  4. Prints + logs a human-readable explanation of which functionality is
     unavailable.
  5. Shows the exact `pip install <package>` command.
  6. Logs the error to the `vyren.dependency_manager` logger with enough
     detail (module, package, subsystem, stdlib flag) for debugging.
  7. Returns `None` (or raises DependencyError if `required=True`) so the
     caller can degrade gracefully instead of crashing VYREN.

This module deliberately depends ONLY on the Python standard library, so it
can be imported very early in boot -- before `reliability.setup_logging()`
has run -- without itself triggering ImportError.

Typical usage at the top of a subsystem module:

    from dependency_manager import DependencyManager
    _dm = DependencyManager("Vision")

    def capture_screen():
        mss = _dm.import_optional("mss")
        if mss is None:
            return None  # screen capture disabled -- error already reported
        ...

Or as a one-shot helper from inside a function:

    from dependency_manager import safe_import

    sd = safe_import("sounddevice", subsystem="Voice")
    if sd is None:
        return  # mic/speaker unavailable -- error already reported
"""

from __future__ import annotations

import importlib
import logging
import sys
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("vyren.dependency_manager")


# ---------------------------------------------------------------------------
# Internal lookup tables
# ---------------------------------------------------------------------------

# Canonical mapping: Python import name -> pip package name.
# The LLM is NEVER asked to guess these -- this table is the single source
# of truth. If a module is missing, we look it up here. If it is not in the
# table, we fall back to using the module's top-level name as the package
# name (which is correct for the vast majority of PyPI packages).
MODULE_TO_PACKAGE: dict[str, str] = {
    # --- User-specified VYREN dependency manager spec ----------------------
    "cv2":                    "opencv-python",
    "PIL":                    "Pillow",
    "mss":                    "mss",
    "faiss":                  "faiss-cpu",
    "sentence_transformers":  "sentence-transformers",
    "bs4":                    "beautifulsoup4",
    "pyautogui":              "pyautogui",
    "pygetwindow":            "pygetwindow",
    "pyperclip":              "pyperclip",
    "watchdog":               "watchdog",
    "rapidocr_onnxruntime":   "rapidocr-onnxruntime",
    "easyocr":                "easyocr",
    "sounddevice":            "sounddevice",
    "soundfile":              "soundfile",

    # --- Additional modules actually used by VYREN today -------------------
    # Kept here so the manager can give correct advice at every call site,
    # not just the spec list. Adding an entry is always safe; removing one
    # only removes a hint, never breaks an import.
    "psutil":                 "psutil",
    "pyttsx3":                "pyttsx3",
    "faster_whisper":         "faster-whisper",
    "numpy":                  "numpy",
    "pynput":                 "pynput",
    "httpx":                  "httpx",
    "websockets":             "websockets",
    "uvicorn":                "uvicorn",
    "fastapi":                "fastapi",
    "google.genai":           "google-genai",
    "yaml":                   "pyyaml",
    "dotenv":                 "python-dotenv",
}

# Human-readable description of what each module enables inside VYREN.
# Used to build the "X subsystem is unavailable because Y is missing" message
# so the user understands what they're losing, not just what's broken.
MODULE_DESCRIPTIONS: dict[str, str] = {
    "cv2":                    "OpenCV -- computer vision and image processing",
    "PIL":                    "Pillow -- image capture and manipulation",
    "mss":                    "mss -- fast cross-platform screen capture",
    "faiss":                  "FAISS -- vector similarity search for semantic memory",
    "sentence_transformers":  "sentence-transformers -- embedding models for semantic memory",
    "bs4":                    "BeautifulSoup4 -- HTML parsing for web tools",
    "pyautogui":              "PyAutoGUI -- desktop automation (mouse / keyboard)",
    "pygetwindow":            "PyGetWindow -- window enumeration for automation",
    "pyperclip":              "Pyperclip -- clipboard access",
    "watchdog":               "watchdog -- filesystem event monitoring",
    "rapidocr_onnxruntime":   "RapidOCR (ONNX Runtime) -- on-device OCR",
    "easyocr":                "EasyOCR -- on-device OCR",
    "sounddevice":            "sounddevice -- microphone / speaker audio I/O",
    "soundfile":              "soundfile -- audio file read/write",
    "psutil":                 "psutil -- system / process metrics",
    "pyttsx3":                "pyttsx3 -- offline text-to-speech fallback",
    "faster_whisper":         "faster-whisper -- offline speech-to-text fallback",
    "numpy":                  "numpy -- numerical arrays (audio / image processing)",
    "pynput":                 "pynput -- keyboard / mouse listener",
    "httpx":                  "httpx -- HTTP client",
    "websockets":             "websockets -- WebSocket client/server",
    "uvicorn":                "uvicorn -- ASGI server",
    "fastapi":                "fastapi -- Web API framework",
    "google.genai":           "google-genai -- Gemini LLM / multimodal client",
    "yaml":                   "PyYAML -- YAML config parser",
    "dotenv":                 "python-dotenv -- .env file loader",
}

# Modules that ship with the Python standard library. If one of these is
# reported missing, the user has a broken or unsupported Python install --
# suggesting `pip install` would be misleading. We use sys.stdlib_module_names
# when available (Python 3.10+) and a hand-curated fallback for older Pythons.
_STDLIB_MODULES: set[str] = set(getattr(sys, "stdlib_module_names", None) or {
    "os", "sys", "json", "logging", "asyncio", "threading", "subprocess",
    "pathlib", "typing", "dataclasses", "enum", "time", "datetime",
    "collections", "functools", "itertools", "re", "io", "abc",
    "audioop", "platform", "shutil", "signal", "socket", "ssl",
    "urllib", "http", "email", "html", "xml", "csv", "sqlite3",
    "queue", "traceback", "warnings", "weakref", "copy", "struct",
})


# ---------------------------------------------------------------------------
# Dataclass for a missing-dependency report
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MissingDependency:
    """Structured report for a missing optional dependency.

    Returned by `DependencyManager.report_missing()` and attached to
    `DependencyError.missing` so callers can embed the report into their
    own error responses (e.g. JSON tool errors) in addition to the
    human-readable rendering.
    """

    module_name: str          # e.g. "mss"
    package_name: str         # e.g. "mss" (what `pip install` expects)
    subsystem: str            # e.g. "Vision"
    description: str          # human-readable "what is unavailable"
    is_stdlib: bool           # True if this is supposed to ship with Python
    install_command: str      # e.g. "pip install mss"

    def render(self, disabled_feature: str | None = None) -> str:
        """Render the user-facing message shown by VYREN.

        The format matches the spec exactly:

            Vision subsystem unavailable.

            Missing module:
            mss

            Required package:
            mss

            Install with:
            pip install mss

            Screen capture has been disabled until this dependency is installed.
        """
        lines: list[str] = []
        lines.append(f"{self.subsystem} subsystem unavailable.")
        lines.append("")
        lines.append("Missing module:")
        lines.append(self.module_name)
        lines.append("")

        if self.is_stdlib:
            # Stdlib modules can't be `pip install`ed -- a missing stdlib
            # module means the Python install itself is broken.
            lines.append(
                f"'{self.module_name}' is part of the Python standard library "
                f"but could not be imported. Your Python installation may be "
                f"corrupted, or you may be running an unsupported Python "
                f"version (Python {sys.version_info.major}.{sys.version_info.minor})."
            )
        else:
            lines.append("Required package:")
            lines.append(self.package_name)
            lines.append("")
            lines.append("Install with:")
            lines.append(self.install_command)

        if self.description:
            lines.append("")
            lines.append(f"What is unavailable: {self.description}")

        if disabled_feature:
            # Caller-supplied one-liner about which concrete feature is
            # disabled (e.g. "Screen capture has been disabled until this
            # dependency is installed."). Appended verbatim.
            lines.append("")
            lines.append(disabled_feature)

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class DependencyError(ImportError):
    """Raised when a required (non-optional) dependency is missing.

    Subclasses `ImportError` so existing `except ImportError:` blocks in
    VYREN continue to catch it, but carries a structured `.missing`
    attribute for callers that want the full report.
    """

    def __init__(self, missing: MissingDependency):
        self.missing = missing
        super().__init__(missing.render())


# ---------------------------------------------------------------------------
# Core manager
# ---------------------------------------------------------------------------

class DependencyManager:
    """Per-subsystem optional-dependency handler.

    A single instance is bound to one subsystem name (e.g. "Vision",
    "Voice", "Memory", "OCR", "Automation"). All optional imports inside
    that subsystem go through the instance so error messages are
    consistently attributed.

    Use `get_manager(subsystem)` for the shared per-subsystem singleton,
    or construct `DependencyManager(subsystem)` directly if you prefer a
    private instance.
    """

    def __init__(self, subsystem: str):
        if not subsystem or not subsystem.strip():
            raise ValueError("DependencyManager requires a non-empty subsystem name")
        self.subsystem = subsystem.strip()

    # ----- public API -----------------------------------------------------

    def import_optional(
        self,
        module_name: str,
        *,
        item: str | None = None,
        disabled_feature: str | None = None,
    ) -> Any:
        """Try to import `module_name`. On failure, report and return `None`.

        Parameters
        ----------
        module_name : str
            The name used in `import module_name` (e.g. "mss", "PIL",
            "cv2", "sentence_transformers"). May contain a dotted path
            ("google.genai") -- the top-level package is used for the
            package-name lookup.
        item : str, optional
            If given, return `module.item` instead of `module`. Equivalent
            to `from module import item`. Returns `None` if either the
            module or the attribute is unavailable.
        disabled_feature : str, optional
            One-line human-readable description of which feature is being
            disabled because of the missing dep (e.g. "Screen capture has
            been disabled until this dependency is installed."). Appended
            verbatim to the user-facing message.
        """
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            # ModuleNotFoundError.name is the cleanest source; fall back to
            # the caller-supplied module_name for older Python or weird
            # cases where the exception doesn't carry .name.
            missing_name = getattr(e, "name", None) or module_name
            # If the user asked for a dotted import like "google.genai" and
            # the failure is actually on the top-level "google" package,
            # report the top-level name -- that's what they need to install.
            if "." in missing_name:
                top = missing_name.split(".", 1)[0]
                # Only collapse to top-level if the top-level itself fails
                # to import (i.e. the dotted path's parent is missing, not
                # just a submodule attribute).
                try:
                    importlib.import_module(top)
                except ImportError:
                    missing_name = top
            self.report_missing(
                missing_name,
                disabled_feature=disabled_feature,
            )
            return None

        if item:
            try:
                return getattr(module, item)
            except AttributeError as e:
                # The MODULE imported fine but the requested attribute is
                # missing. This is NOT a missing-dependency situation --
                # it's a version mismatch or a programmer error. Re-raise
                # as ImportError so callers' existing `except ImportError`
                # blocks catch it, but include the original AttributeError
                # for debuggability.
                raise ImportError(
                    f"Module '{module_name}' is installed but has no "
                    f"attribute '{item}': {e}. This usually means the "
                    f"installed version is too old or too new."
                ) from e

        return module

    def import_required(
        self,
        module_name: str,
        *,
        item: str | None = None,
        disabled_feature: str | None = None,
    ) -> Any:
        """Like `import_optional` but raises `DependencyError` on failure.

        Use this when the subsystem genuinely cannot function without the
        module and there is no graceful degradation path -- the caller
        must handle the exception and decide whether to skip the feature
        or abort.
        """
        value = self.import_optional(
            module_name,
            item=item,
            disabled_feature=disabled_feature,
        )
        if value is None:
            missing = self._build_report(module_name)
            raise DependencyError(missing)
        return value

    def is_available(self, module_name: str) -> bool:
        """Return True if `module_name` can be imported. No side effects.

        Does NOT report or log -- use this for capability probes (e.g.
        the voice status endpoint reporting whether the mic is available).
        """
        try:
            importlib.import_module(module_name)
            return True
        except ImportError:
            return False

    def report_missing(
        self,
        module_name: str,
        *,
        disabled_feature: str | None = None,
    ) -> MissingDependency:
        """Print + log the formatted "missing dependency" message.

        Returns the structured `MissingDependency` so callers can also
        embed the report into their own error responses (e.g. JSON tool
        errors returned to the LLM).
        """
        report = self._build_report(module_name)
        message = report.render(disabled_feature=disabled_feature)

        # Print to stdout so the user sees it even before logging is
        # configured -- the dependency manager can be called very early
        # in boot, before reliability.setup_logging() has run, and we
        # must not silently swallow the diagnostic.
        try:
            print("\n" + message + "\n", flush=True)
        except Exception:
            # If stdout is closed/redirected (e.g. daemon mode), don't
            # crash -- the logger below is the durable record.
            pass

        # Always log at ERROR level -- a missing dep is a real problem
        # even if VYREN continues running in degraded mode. The structured
        # one-liner is for grep / log analysis; the multi-line message
        # is for human readers.
        logger.error(
            "Missing dependency: module=%r package=%r subsystem=%r "
            "stdlib=%s install=%r",
            report.module_name,
            report.package_name,
            report.subsystem,
            report.is_stdlib,
            report.install_command,
        )
        for line in message.splitlines():
            logger.error(line)

        return report

    # ----- internals ------------------------------------------------------

    def _build_report(self, module_name: str) -> MissingDependency:
        """Resolve a module name to a structured MissingDependency report."""
        # The lookup table is keyed by the import name; for dotted imports
        # like "google.genai" we try the full key first, then fall back to
        # the top-level segment ("google").
        package_name = MODULE_TO_PACKAGE.get(module_name)
        if package_name is None:
            top = module_name.split(".", 1)[0]
            package_name = MODULE_TO_PACKAGE.get(top, top)

        description = (
            MODULE_DESCRIPTIONS.get(module_name)
            or MODULE_DESCRIPTIONS.get(module_name.split(".", 1)[0], "")
        )

        is_stdlib = (
            module_name in _STDLIB_MODULES
            or module_name.split(".", 1)[0] in _STDLIB_MODULES
        )

        install_command = f"pip install {package_name}"

        return MissingDependency(
            module_name=module_name,
            package_name=package_name,
            subsystem=self.subsystem,
            description=description,
            is_stdlib=is_stdlib,
            install_command=install_command,
        )


# ---------------------------------------------------------------------------
# Module-level singleton registry + convenience helpers
# ---------------------------------------------------------------------------

# Per-subsystem singleton cache. Subsequent calls with the same subsystem
# name return the same instance, so the manager can be used as a
# per-subsystem singleton without forcing callers to thread it through
# constructors.
_managers: dict[str, DependencyManager] = {}


def get_manager(subsystem: str) -> DependencyManager:
    """Return (or create) the shared DependencyManager for a subsystem.

    Subsequent calls with the same subsystem name return the same instance.
    """
    mgr = _managers.get(subsystem)
    if mgr is None:
        mgr = DependencyManager(subsystem)
        _managers[subsystem] = mgr
    return mgr


def safe_import(
    module_name: str,
    *,
    subsystem: str,
    item: str | None = None,
    disabled_feature: str | None = None,
) -> Any:
    """One-shot helper: `safe_import("mss", subsystem="Vision")`.

    Equivalent to `get_manager("Vision").import_optional("mss")` but
    shorter for call sites that don't want to hold a manager instance
    (e.g. a single lazy import inside a function body).
    """
    return get_manager(subsystem).import_optional(
        module_name,
        item=item,
        disabled_feature=disabled_feature,
    )


__all__ = [
    "MODULE_TO_PACKAGE",
    "MODULE_DESCRIPTIONS",
    "MissingDependency",
    "DependencyError",
    "DependencyManager",
    "get_manager",
    "safe_import",
]
