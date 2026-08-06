"""
computer/ -- Computer control: keyboard, mouse, clipboard, terminal.

Uses pyautogui for input control and subprocess for terminal.
All computer control tools are consequential and require confirmation.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import tempfile
from typing import Callable, Optional

logger = logging.getLogger("vyren.computer")

from platform_abstraction import get_default_shell, is_windows


def get_clipboard() -> str:
    """Get the current clipboard content."""
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except ImportError:
        try:
            from environment import get_capabilities
            caps = get_capabilities()
            if caps.has_clipboard and caps.is_windows:
                import ctypes
                CF_UNICODETEXT = 13
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                if not user32.OpenClipboard(0):
                    return ""
                try:
                    handle = user32.GetClipboardData(CF_UNICODETEXT)
                    if not handle:
                        return ""
                    kernel32.GlobalLock.restype = ctypes.c_wchar_p
                    return kernel32.GlobalLock(handle) or ""
                finally:
                    user32.CloseClipboard()
            return f"Clipboard access unavailable on this environment: {caps.platform}"
        except Exception as e:
            return f"Clipboard access failed: {e}"
        return f"Clipboard access failed: unsupported platform: {get_env().platform}"


def set_clipboard(text: str) -> str:
    """Set the clipboard content."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return f"Clipboard set ({len(text)} chars)"
    except ImportError:
        return "pyperclip not installed (pip install pyperclip)"


def run_command(command: str, timeout: int = 30, shell: bool = True) -> str:
    """Run a shell command and return output in a platform-safe way."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return output if output.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        return f"Command failed: {type(e).__name__} -- {e}"


def list_running_apps() -> str:
    """List running applications/processes."""
    try:
        import psutil
        lines = []
        for proc in psutil.process_iter(["pid", "name", "memory_percent"]):
            try:
                info = proc.info
                lines.append(
                    f"  PID {info['pid']:>6}  {info['name'][:30]:30}  MEM {info.get('memory_percent', 0) or 0:5.1f}%"
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        lines.sort()
        return f"Running processes ({len(lines)}):\n" + "\n".join(lines[:30])
    except Exception as e:
        return f"Failed to list processes: {e}"


def open_application(app_name: str) -> str:
    """Open an application by name across platforms."""
    import shutil
    app_lower = app_name.lower()

    app_commands = {
        "vscode": "code",
        "code": "code",
        "notepad": "notepad",
        "calculator": "calc" if is_windows() else "gnome-calculator",
        "explorer": "explorer" if is_windows() else "xdg-open .",
        "browser": "start msedge" if is_windows() else "xdg-open https://",
        "chrome": "start chrome" if is_windows() else "google-chrome",
        "firefox": "start firefox" if is_windows() else "firefox",
        "terminal": "start cmd" if is_windows() else "x-terminal-emulator",
        "cmd": "start cmd" if is_windows() else "x-terminal-emulator",
        "powershell": "start powershell" if is_windows() else "x-terminal-emulator",
        "file explorer": "explorer" if is_windows() else "xdg-open .",
    }

    cmd = app_commands.get(app_lower, app_name)
    try:
        from environment import get_capabilities
        caps = get_capabilities()
        if not caps.can_open_apps:
            return f"Opening apps is not supported on this environment: {caps.platform}"
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=10)
        return f"Opened: {app_name}"
    except Exception as e:
        return f"Failed to open {app_name}: {e}"


def type_text(text: str) -> str:
    """Type text using keyboard. Requires pyautogui."""
    try:
        import pyautogui
        import time
        time.sleep(0.5)
        pyautogui.typewrite(text)
        return f"Typed {len(text)} characters"
    except ImportError:
        return "pyautogui not installed (pip install pyautogui)"
    except Exception as e:
        return f"Type failed: {e}"


def press_key(key: str) -> str:
    """Press a keyboard key. Requires pyautogui."""
    try:
        import pyautogui
        pyautogui.press(key)
        return f"Pressed: {key}"
    except ImportError:
        return "pyautogui not installed (pip install pyautogui)"
    except Exception as e:
        return f"Key press failed: {e}"
