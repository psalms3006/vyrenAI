"""One-time migration helper to replace hardcoded ~/.vyren paths."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

migrations = []


def add(path, old, new):
    migrations.append((REPO / path, old, new))


def apply(path, old, new):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8")
    return True


# Runtime
add(
    "runtime/manager.py",
    'VYREN_DIR = Path(os.path.expanduser("~/.vyren"))\n',
    "from platform_abstraction import get_env\nVYREN_DIR = get_env().data_dir\n",
)

# Monitoring / web_server
add(
    "monitoring/__init__.py",
    '    disk_root = "C:\\\\" if platform.system() == "Windows" else "/"',
    "    disk_root = get_disk_root()",
)
add(
    "runtime/web_server.py",
    '            disk_root = "C:\\\\" if platform.system() == "Windows" else "/"',
    "            disk_root = get_disk_root()",
)

# Auto start
add(
    "runtime/auto_start.py",
    '"""\nruntime/auto_start.py -- Windows Auto-Start Registration.\n',
    '"""\nruntime/auto_start.py -- Platform-aware auto-start registration.\n',
)
add(
    "runtime/auto_start.py",
    "Registers VYREN to start automatically when Windows boots.\nUses the Windows Startup folder (configurable).\n",
    "Registers VYREN to start automatically on supported platforms.\n",
)
add(
    "runtime/auto_start.py",
    '    def _get_startup_folder(self) -> Path:\n        """Get the Windows Startup folder path."""\n        if sys.platform == "win32":\n            import winreg\n            try:\n                key = winreg.OpenKey(\n                    winreg.HKEY_CURRENT_USER,\n                    r"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Shell Folders",\n                )\n                startup, _ = winreg.QueryValueEx(key, "Startup")\n                winreg.CloseKey(key)\n                return Path(startup)\n            except Exception:\n                # Fallback\n                appdata = os.environ.get("APPDATA", "")\n                return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"\n\n        # Non-Windows: use a config directory\n        return Path(os.path.expanduser("~/.config/vyren/"))\n',
    "    def _get_startup_folder(self) -> Path:\n        \"\"\"Get the platform startup location.\"\"\"\n        if not get_env().supports_autostart:\n            return get_env().data_dir / "autostart"\n        return self._startup_folder\n",
)
add(
    "runtime/auto_start.py",
    '    def _create_shortcut(self):\n        """Create a Windows shortcut (.lnk) file."""\n        if sys.platform == "win32":\n            self._create_windows_shortcut()\n        else:\n            # On non-Windows, create a simple shell script\n            self._create_shell_script()\n',
    '    def _create_shortcut(self):\n        """Create a platform-specific autostart entry."""\n        if is_windows():\n            self._create_windows_shortcut()\n        else:\n            self._create_shell_script()\n',
)

# Computer control
add(
    "computer/__init__.py",
    '"""\ncomputer/ -- Computer control: keyboard, mouse, clipboard, terminal.\n\nUses pyautogui for input control and subprocess for terminal.\nAll computer control tools are consequential and require confirmation.\n"""\n\nimport logging\nimport os\nimport subprocess\nimport tempfile\nfrom typing import Callable\n\nlogger = logging.getLogger("vyren.computer")\n',
    '"""\ncomputer/ -- Computer control: keyboard, mouse, clipboard, terminal.\n\nUses pyautogui for input control and subprocess for terminal.\nAll computer control tools are consequential and require confirmation.\n"""\n\nfrom __future__ import annotations\n\nimport logging\nimport os\nimport platform\nimport shutil\nimport subprocess\nimport tempfile\nfrom typing import Callable, Optional\n\nlogger = logging.getLogger("vyren.computer")\n\nfrom platform_abstraction import get_default_shell, is_windows\n',
)
add(
    "computer/__init__.py",
    '    # Windows fallback\n    import ctypes\n    CF_UNICODETEXT = 13\n    user32 = ctypes.windll.user32\n    kernel32 = ctypes.windll.kernel32\n    if not user32.OpenClipboard(0):\n        return ""\n    try:\n        handle = user32.GetClipboardData(CF_UNICODETEXT)\n        if not handle:\n            return ""\n        kernel32.GlobalLock.restype = ctypes.c_wchar_p\n        return kernel32.GlobalLock(handle) or ""\n    finally:\n        user32.CloseClipboard()\n',
    '    if is_windows():\n        import ctypes\n\n        CF_UNICODETEXT = 13\n        user32 = ctypes.windll.user32\n        kernel32 = ctypes.windll.kernel32\n        if not user32.OpenClipboard(0):\n            return ""\n        try:\n            handle = user32.GetClipboardData(CF_UNICODETEXT)\n            if not handle:\n                return ""\n            kernel32.GlobalLock.restype = ctypes.c_wchar_p\n            return kernel32.GlobalLock(handle) or ""\n        finally:\n            user32.CloseClipboard()\n    return f"Clipboard access failed: unsupported platform: {get_env().platform}"\n',
)
add(
    "computer/__init__.py",
    'def run_command(command: str, timeout: int = 30, shell: bool = True) -> str:\n    """Run a shell command and return output. Windows: uses cmd.exe."""\n',
    "def run_command(command: str, timeout: int = 30, shell: bool = True) -> str:\n    \"\"\"Run a shell command and return output in a platform-safe way.\"\"\"\n",
)
add(
    "computer/__init__.py",
    'def open_application(app_name: str) -> str:\n    """Open an application by name. Windows-specific."""\n    import shutil\n    app_lower = app_name.lower()\n\n    # Common application mappings\n    app_commands = {\n        "vscode": "code",\n        "code": "code",\n        "notepad": "notepad",\n        "calculator": "calc",\n        "explorer": "explorer",\n        "browser": "start msedge",\n        "chrome": "start chrome",\n        "firefox": "start firefox",\n        "terminal": "start cmd",\n        "cmd": "start cmd",\n        "powershell": "start powershell",\n        "file explorer": "explorer",\n    }\n\n    cmd = app_commands.get(app_lower, f"start {app_name}")\n',
    'def open_application(app_name: str) -> str:\n    """Open an application by name across platforms."""\n    import shutil\n    app_lower = app_name.lower()\n\n    app_commands = {\n        "vscode": "code",\n        "code": "code",\n        "notepad": "notepad",\n        "calculator": "calc" if is_windows() else "gnome-calculator",\n        "explorer": "explorer" if is_windows() else "xdg-open .",\n        "browser": "start msedge" if is_windows() else "xdg-open https://",\n        "chrome": "start chrome" if is_windows() else "google-chrome",\n        "firefox": "start firefox" if is_windows() else "firefox",\n        "terminal": "start cmd" if is_windows() else "x-terminal-emulator",\n        "cmd": "start cmd" if is_windows() else "x-terminal-emulator",\n        "powershell": "start powershell" if is_windows() else "x-terminal-emulator",\n        "file explorer": "explorer" if is_windows() else "xdg-open .",\n    }\n\n    cmd = app_commands.get(app_lower, app_name)\n',
)

# System tools
add(
    "tools/system_tools.py",
    "import platform\n",
    "from platform_abstraction import get_env, get_disk_root, is_windows\n",
)
add(
    "tools/system_tools.py",
    '        lines.append(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")\n        lines.append(f"Hostname: {platform.node()}")\n',
    '        env = get_env()\n        lines.append(f"OS: {env.platform} ({platform.system()} {platform.release()})")\n        lines.append(f"Hostname: {platform.node()}")\n',
)

# Known explicit path files
add(
    "audit.py",
    '        self.path = Path(path or os.path.expanduser("~/.vyren/audit.log"))',
    "        self.path = Path(path or str(get_env().path_for('audit')))",
)
add(
    "heartbeat.py",
    '        self.path = Path(path or os.path.expanduser("~/.vyren/notices.json"))',
    "        self.path = Path(path or str(get_env().path_for('notices')))",
)
add(
    "memory.py",
    '        self.path = Path(path or os.path.expanduser("~/.vyren/memory.json"))',
    "        self.path = Path(path or str(get_env().path_for('memory')))",
)
add(
    "scheduler.py",
    'JOBS_FILE = Path(os.path.expanduser("~/.vyren/jobs.json"))',
    "from platform_abstraction import get_env\nJOBS_FILE = get_env().path_for('jobs')",
)
add(
    "service.py",
    'VYREN_DIR = Path(os.path.expanduser("~/.vyren"))',
    "from platform_abstraction import get_env\nVYREN_DIR = get_env().data_dir",
)
add(
    "world_model.py",
    'VYREN_DIR = Path(os.path.expanduser("~/.vyren"))',
    "from platform_abstraction import get_env\nVYREN_DIR = get_env().data_dir",
)
add(
    "knowledge_graph.py",
    'VYREN_DIR = Path(os.path.expanduser("~/.vyren"))',
    "from platform_abstraction import get_env\nVYREN_DIR = get_env().data_dir",
)
add(
    "execution/__init__.py",
    'CHECKPOINT_DIR = Path(os.path.expanduser("~/.vyren/checkpoints"))',
    "from platform_abstraction import get_env\nCHECKPOINT_DIR = get_env().path_for('checkpoints')",
)
add(
    "security/__init__.py",
    'SEC_DIR = Path(os.path.expanduser("~/.vyren/security"))',
    "from platform_abstraction import get_env\nSEC_DIR = get_env().path_for('security')",
)
add(
    "brain/greetings.py",
    '_GREETING_HISTORY_PATH = Path(os.path.expanduser("~/.vyren/greeting_history.json"))',
    "from platform_abstraction import get_env\n_GREETING_HISTORY_PATH = get_env().path_for('greeting_history')",
)
add(
    "brain/greeting_engine.py",
    '~/.vyren/greeting_history.json stores the last _MAX_HISTORY entries as\n',
    "`data_dir/greeting_history.json` stores the last _MAX_HISTORY entries as\n",
)
add(
    "brain/greeting_engine.py",
    '_HISTORY_PATH = Path(os.path.expanduser("~/.vyren/greeting_history.json"))',
    "from platform_abstraction import get_env\n_HISTORY_PATH = get_env().path_for('greeting_history')",
)
add(
    "runtime/connectivity.py",
    '            queue_path = Path(os.path.expanduser("~/.vyren"))',
    "            queue_path = get_env().data_dir",
)
add(
    "runtime/connectivity.py",
    '        queue_file = Path(os.path.expanduser("~/.vyren")) / "offline_task_queue.json"\n',
    "        queue_file = get_env().path_for('offline_queue')\n",
)
add(
    "runtime/connectivity.py",
    '        queue_file = Path(os.path.expanduser("~/.vyren")) / "offline_task_queue.json"\n',
    "        queue_file = get_env().path_for('offline_queue')\n",
)
add(
    "tools/screen_tools.py",
    '        save_path = os.path.expanduser(f"~/.vyren/screenshots/screen_{timestamp}.png")',
    "        save_path = str(get_env().path_for('screenshots') / f'screen_{timestamp}.png')",
)
add(
    "tools/vision_tools.py",
    '                        save_path = os.path.expanduser(f"~/.vyren/generated_{timestamp}.png")\n                    else:\n                        save_path = os.path.expanduser(save_path)\n',
    "                        save_path = str(get_env().path_for('generated') / f'generated_{timestamp}.png')\n                    else:\n                        save_path = str(get_env().path_for('generated') / save_path)\n",
)
add(
    "tools/vision_tools.py",
    '            "auto-saves to ~/.vyren/ with a timestamp."\n',
    '            "auto-saves to the platform cache dir with a timestamp."\n',
)

# Agents developer path
add(
    "agents/developer.py",
    '                "directory": os.path.expanduser("~") + "\\\\my-project",\n',
    '                "directory": str(get_env().data_dir / "workspace" / "my-project"),\n',
)

changed = 0
for path, old, new in migrations:
    try:
        ok = apply(path, old, new)
        if ok:
            changed += 1
            print(f"patched: {path}")
        else:
            print(f"skip: {path}")
    except Exception as e:
        print(f"err: {path}: {e}")

print(f"\npatched {changed}/{len(migrations)} files")
