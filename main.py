"""
main.py -- VYREN AI Operating System.

    python main.py

That's it. VYREN boots, starts listening, and speaks to you.
Like JARVIS. Voice is the primary interface.

What happens when you run this:
  1. All subsystems boot in dependency order
  2. The voice engine activates (Gemini Live, or continuous listening)
  3. VYREN speaks a greeting
  4. VYREN is always-on, always listening
  5. Say "Hey Vyren" to talk
  6. Text input is available as a secondary interface
  7. Web dashboard is available at http://localhost:8420
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env BEFORE any subsystem reads environment variables.
# This is the single root cause of "No GEMINI_API_KEY" —
# without this, os.environ.get("GEMINI_API_KEY") returns None
# because the .env file was never parsed into the environment.
from dotenv import load_dotenv
load_dotenv()


def main():
    import argparse
    import threading
    import time as _time
    import webbrowser

    parser = argparse.ArgumentParser(description="VYREN")
    parser.add_argument("--app", action="store_true", help="Launch desktop app window instead of browser")
    args = parser.parse_args()

    from runtime.manager import RuntimeManager

    runtime = RuntimeManager()

    if args.app:
        try:
            from apps.desktop.vyren_app import launch_dashboard
            launch_dashboard()
            return
        except Exception as exc:
            print(f"  [Desktop app launch failed: {exc}]")

    def _open_interface_when_ready():
        try:
            for _ in range(240):
                port = runtime._services.get("server_port") if runtime._services else None
                if port:
                    break
                _time.sleep(0.25)
            else:
                return
            url = f"http://localhost:{port}"
            webbrowser.open_new_tab(url)
            print(f"  Interface: {url}\n")
        except Exception as exc:
            print(f"  [Interface launch skipped: {exc}]")

    threading.Thread(target=_open_interface_when_ready, name="vyren-interface", daemon=True).start()

    try:
        runtime.start()
    except KeyboardInterrupt:
        runtime.shutdown()


if __name__ == "__main__":
    main()