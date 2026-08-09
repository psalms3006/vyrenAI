"""
VYREN Desktop App Launcher

Launches the VYREN web dashboard in a dedicated desktop window.
Uses the existing FastAPI backend at http://localhost:8420.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger("vyren.desktop")


def _wait_for_server(url: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def launch_dashboard():
    project_root = Path(__file__).resolve().parent.parent
    url = "http://localhost:8420"

    # Verify backend is reachable; if not, try to start it.
    server_proc = None
    if not _wait_for_server(url, timeout=4):
        logger.info("Starting VYREN backend...")
        try:
            if sys.platform == "win32":
                server_proc = subprocess.Popen(
                    [sys.executable, "main.py"],
                    cwd=str(project_root),
                    creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
                )
            else:
                server_proc = subprocess.Popen(
                    [sys.executable, "main.py"],
                    cwd=str(project_root),
                    start_new_session=True,
                )
        except Exception as exc:
            logger.warning("Backend launch failed: %s", exc)

        if not _wait_for_server(url, timeout=120):
            logger.warning("Backend did not become ready in time; opening UI anyway.")

    try:
        import webview
    except ImportError:
        logger.info("pywebview not installed; installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pywebview", "--quiet"])
        import webview  # type: ignore[import-untyped]

    window = webview.create_window(
        "VYREN",
        url=url,
        width=1280,
        height=800,
        min_size=(800, 600),
        fullscreen=False,
        frameless=False,
        easy_drag=True,
        text_select=False,
    )

    try:
        webview.start(debug=False, private_mode=False)
    finally:
        if server_proc and server_proc.poll() is None:
            try:
                server_proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    launch_dashboard()
