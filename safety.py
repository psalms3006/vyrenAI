"""safety.py -- Confirmation gate for consequential actions.

Before any tool on the consequential list runs, this module pauses
and asks the user for explicit approval. The user sees exactly what
the tool intends to do and must type 'yes' to proceed.

Read-only tools flow freely. Only irreversible or impactful actions
stop here.
"""

from config import is_consequential


# Global kill switch. When True, all proactive behavior stops.
# The user can still talk to VYREN, but nothing happens automatically.
kill_switch_active: bool = False


def activate_kill_switch():
    """Pause all proactive/background behavior immediately."""
    global kill_switch_active
    kill_switch_active = True


def deactivate_kill_switch():
    """Resume normal behavior."""
    global kill_switch_active
    kill_switch_active = False


def is_killed() -> bool:
    return kill_switch_active


def needs_confirmation(tool_name: str) -> bool:
    """Check if a tool requires user confirmation before running."""
    return is_consequential(tool_name)


def ask_confirmation(tool_name: str, args: dict) -> bool:
    """Present the pending action to the user and wait for yes/no.

    Returns True if the user approved, False if declined.
    """
    # Build a clear description of what's about to happen
    args_str = ", ".join(f"{k}={v}" for k, v in args.items())
    print()
    print(f"  ⚠  VYREN wants to: {tool_name}({args_str})")
    print(f"  This action requires your confirmation.")
    print()

    while True:
        try:
            answer = input("  Allow this? (yes/no): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return False

        if answer in ("yes", "y", "yeah", "go ahead", "do it", "proceed"):
            return True
        elif answer in ("no", "n", "nope", "don't", "stop", "cancel"):
            return False
        else:
            print('  Please type "yes" or "no".')
