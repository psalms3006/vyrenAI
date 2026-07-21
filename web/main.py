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
    from runtime.manager import RuntimeManager

    runtime = RuntimeManager()

    try:
        runtime.start()
    except KeyboardInterrupt:
        runtime.shutdown()


if __name__ == "__main__":
    main()