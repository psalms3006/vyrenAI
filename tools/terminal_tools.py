"""tools/terminal_tools.py -- Robust command execution for VYREN."""

import json
import logging
import os
import subprocess
import threading
from typing import Optional
from tools import ToolDef, ToolRegistry
from platform_abstraction import get_default_shell

logger = logging.getLogger("vyren.tools.terminal")

def register(registry: ToolRegistry):
    
    def run_command(command: str, cwd: Optional[str] = None, timeout: int = 60) -> str:
        """Execute a terminal command and return the result.
        command: The shell command to run.
        cwd: Working directory (optional).
        timeout: Execution timeout in seconds.
        """
        result_data = {"status": "success", "command": command}
        
        try:
            shell = get_default_shell() or "cmd.exe" if os.name == "nt" else "/bin/bash"
            
            # Use subprocess.run for simple synchronous execution
            process = subprocess.run(
                command,
                shell=True,
                executable=shell,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=os.environ.copy()
            )
            
            result_data["exit_code"] = process.returncode
            result_data["stdout"] = process.stdout
            result_data["stderr"] = process.stderr
            
            if process.returncode != 0:
                result_data["status"] = "error"
                result_data["error"] = f"Command failed with exit code {process.returncode}"
                
        except subprocess.TimeoutExpired:
            result_data["status"] = "error"
            result_data["error"] = f"Command timed out after {timeout} seconds"
        except Exception as e:
            result_data["status"] = "error"
            result_data["error"] = str(e)
            
        return json.dumps(result_data)

    registry.register(ToolDef(
        name="run_terminal_command",
        description="Execute a shell command on the host system. Returns JSON with stdout, stderr, and exit_code.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to execute."},
                "cwd": {"type": "string", "description": "Current working directory."},
                "timeout": {"type": "integer", "default": 60}
            },
            "required": ["command"]
        },
        handler=run_command,
        safety_level="consequential"
    ))
