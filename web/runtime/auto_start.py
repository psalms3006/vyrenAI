"""
runtime/auto_start.py -- Windows Auto-Start Registration.

Registers VYREN to start automatically when Windows boots.
Uses the Windows Startup folder (configurable).

Usage (from Python):
    from runtime.auto_start import AutoStartManager
    mgr = AutoStartManager()
    mgr.enable()   # Register auto-start
    mgr.disable()  # Remove auto-start
    mgr.is_enabled()  # Check if registered
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("vyren.auto_start")


class AutoStartManager:
    """
    Manages VYREN's auto-start registration.

    On Windows, creates a shortcut in the Startup folder.
    On Linux (future), would use systemd user service.
    On Android (future), would use a foreground service.
    """

    def __init__(self):
        self._startup_folder = self._get_startup_folder()
        self._shortcut_name = "VYREN.lnk"
        self._shortcut_path = self._startup_folder / self._shortcut_name

        # The script to run
        self._target_script = Path(sys.executable).parent / "python.exe"
        self._working_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self._main_script = self._working_dir / "main.py"

    def is_enabled(self) -> bool:
        """Check if auto-start is registered."""
        return self._shortcut_path.exists()

    def enable(self) -> bool:
        """Register VYREN for auto-start on system boot."""
        if self.is_enabled():
            logger.info("Auto-start already enabled")
            return True

        try:
            self._create_shortcut()
            logger.info(f"Auto-start enabled: {self._shortcut_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to enable auto-start: {e}")
            return False

    def disable(self) -> bool:
        """Remove VYREN from auto-start."""
        if not self.is_enabled():
            logger.info("Auto-start not currently enabled")
            return True

        try:
            self._shortcut_path.unlink()
            logger.info("Auto-start disabled")
            return True
        except Exception as e:
            logger.error(f"Failed to disable auto-start: {e}")
            return False

    def _get_startup_folder(self) -> Path:
        """Get the Windows Startup folder path."""
        if sys.platform == "win32":
            import winreg
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
                )
                startup, _ = winreg.QueryValueEx(key, "Startup")
                winreg.CloseKey(key)
                return Path(startup)
            except Exception:
                # Fallback
                appdata = os.environ.get("APPDATA", "")
                return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"

        # Non-Windows: use a config directory
        return Path(os.path.expanduser("~/.config/vyren/"))

    def _create_shortcut(self):
        """Create a Windows shortcut (.lnk) file."""
        if sys.platform == "win32":
            self._create_windows_shortcut()
        else:
            # On non-Windows, create a simple shell script
            self._create_shell_script()

    def _create_windows_shortcut(self):
        """Create a Windows .lnk shortcut using COM."""
        try:
            import pythoncom
            from win32com.shell import shell, shellcon

            shortcut = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink,
                None,
                pythoncom.CLSCTX_INPROC_SERVER,
                shell.IID_IShellLink,
            )

            # Set shortcut properties
            shortcut.SetPath(str(self._target_script))
            shortcut.SetArguments(f'"{self._main_script}"')
            shortcut.SetWorkingDirectory(str(self._working_dir))
            shortcut.SetDescription("VYREN AI Operating System")

            # Save the shortcut
            persist_file = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
            persist_file.Save(str(self._shortcut_path), 0)

        except ImportError:
            # Fallback: create a .bat file instead
            bat_path = self._startup_folder / "VYREN.bat"
            bat_content = (
                f'@echo off\n'
                f'cd /d "{self._working_dir}"\n'
                f'"{sys.executable}" main.py\n'
            )
            bat_path.write_text(bat_content)
            logger.info(f"Created batch file instead: {bat_path}")

    def _create_shell_script(self):
        """Create a shell script for non-Windows platforms."""
        self._startup_folder.mkdir(parents=True, exist_ok=True)
        sh_path = self._startup_folder / "vyren.sh"
        sh_content = (
            f"#!/bin/bash\n"
            f'cd "{self._working_dir}"\n'
            f'"{sys.executable}" main.py\n'
        )
        sh_path.write_text(sh_content)
        sh_path.chmod(0o755)