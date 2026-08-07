import subprocess
"""tools/computer_tools.py -- Computer control tools.

Keyboard, mouse, clipboard, terminal, application control.
Most are consequential and require confirmation."""

from tools import ToolDef, ToolRegistry


def register(registry: ToolRegistry):
    from computer import get_clipboard, set_clipboard, run_command, list_running_apps, open_application, type_text, press_key

    def clipboard_read() -> str:
        """Read the current clipboard content."""
        return get_clipboard() or "(clipboard is empty)"

    def clipboard_write(text: str) -> str:
        """Write text to the clipboard."""
        return set_clipboard(text)

    def run_terminal_command(command: str, timeout: int = 30) -> str:
        """Run a terminal/shell command and return the output. REQUIRES CONFIRMATION."""
        return f"TERMINAL_REQUESTED: {command}"

    def list_apps() -> str:
        """List running applications and processes."""
        return list_running_apps()

    def open_app(app_name: str) -> str:
        """Open an application by name. REQUIRES CONFIRMATION."""
        return f"OPEN_APP_REQUESTED: {app_name}"

    def set_brightness(level: int = 50) -> str:
        """Set screen brightness on Windows. REQUIRES CONFIRMATION."""
        try:
            ps = (
                "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,"
                f" {max(0, min(100, int(level)))})"
            )
            out = subprocess.run(
                ["powershell", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if out.returncode == 0:
                return f"Brightness set to {level}%"
            return f"Brightness tool error: {out.stderr.strip() or out.stdout.strip()}"
        except Exception as e:
            return f"Brightness tool failed: {type(e).__name__} -- {e}"

    def press_key_tool(key: str) -> str:
        """Press a keyboard key. REQUIRES CONFIRMATION."""
        return f"KEY_REQUESTED: {key}"

    registry.register(ToolDef(
        name="clipboard_read",
        description="Read the current clipboard content.",
        parameters={"type": "object", "properties": {}},
        handler=clipboard_read,
        safety_level="safe",
    ))
    registry.register(ToolDef(
        name="clipboard_write",
        description="Write text to the clipboard.",
        parameters={"type": "object", "properties": {"text": {"type": "string", "description": "Text to copy to clipboard"}}, "required": ["text"]},
        handler=clipboard_write,
        safety_level="safe",
    ))
    registry.register(ToolDef(
        name="run_terminal_command",
        description="Run a terminal/shell command (cmd, PowerShell) and return output. Destructive commands require confirmation.",
        parameters={"type": "object", "properties": {"command": {"type": "string", "description": "Shell command to execute"}, "timeout": {"type": "integer", "description": "Max seconds (default 30)"}}, "required": ["command"]},
        handler=run_terminal_command,
        safety_level="consequential",
    ))
    registry.register(ToolDef(
        name="list_apps",
        description="List running applications and processes with PID, name, and memory usage.",
        parameters={"type": "object", "properties": {}},
        handler=list_apps,
        safety_level="safe",
    ))
    registry.register(ToolDef(
        name="open_app",
        description="Open an application by name (e.g. 'vscode', 'chrome', 'notepad').",
        parameters={"type": "object", "properties": {"app_name": {"type": "string", "description": "Application name to open"}}, "required": ["app_name"]},
        handler=open_app,
        safety_level="consequential",
    ))
    registry.register(ToolDef(
        name="set_brightness",
        description="Set Windows screen brightness to a percentage (0-100).",
        parameters={"type": "object", "properties": {"level": {"type": "integer", "description": "Brightness percent 0-100"}}},
        handler=set_brightness,
        safety_level="consequential",
    ))
    registry.register(ToolDef(
        name="press_key",
        description="Press a keyboard key (e.g. 'enter', 'ctrl+c', 'alt+tab').",
        parameters={"type": "object", "properties": {"key": {"type": "string", "description": "Key or key combo to press"}}, "required": ["key"]},
        handler=press_key_tool,
        safety_level="consequential",
    ))