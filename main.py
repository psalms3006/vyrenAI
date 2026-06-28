"""
main.py — VYREN's agent loop (Tiers 1+2+4+6 combined).

The full loop:
  1. Load config, memory, tools, audit log
  2. Read input from the user
  3. Send to model with tools available
  4. If model calls tools:
     a. For each tool call: check safety gate, execute, log result
     b. Feed tool results back to model (it may call more tools)
     c. Repeat until model produces a text reply
  5. Print reply, append to history, wait for next input

The text path, tool path, and safety gate all flow through
the same brain. Voice and heartbeat are integrated.

Run:  python main.py
Quit: Ctrl+C, or type /quit, /exit, /q
Voice: /voice (switch to push-to-talk mode, requires API keys)
Status: /status, /notices, /heartbeat, /voice-info
Special: /kill (activate kill switch), /unkill (deactivate),
          /tools (list available tools), /memory (show stored memory),
          /clear (clear conversation history, keep memory)
"""

import os
import sys

# Make sure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import audit as audit_mod
import safety
from memory import MemoryStore
from heartbeat import Heartbeat, NoticeStore
from provider import run_turn, TurnResult
from system_prompt import build_system_prompt
from tools import create_registry


def print_welcome(registry):
    tool_names = registry.tool_names()
    print()
    print("  VYREN")
    print(f"  {len(tool_names)} tools loaded: {', '.join(tool_names)}")
    print("  Type a message and press Enter.")
    print("  Commands: /quit  /kill  /tools  /memory  /clear")
    print()


def run():
    # ------------------------------------------------------------------
    # Startup: load everything
    # ------------------------------------------------------------------
    config.load()

    memory_path = config.get("memory.path")
    audit_path = config.get("audit.path")
    mem = MemoryStore(memory_path)
    audit = audit_mod.AuditLog(audit_path)
    registry = create_registry(memory_store=mem)

    # Build system prompt with memory context
    memory_context = mem.build_context()
    system_prompt = build_system_prompt(memory_context)

    # Get Gemini tool declarations
    gemini_tools = registry.to_gemini_tools()

    # In-memory conversation history
    history: list = []

    # Heartbeat
    notice_store = NoticeStore(
        config.get("audit.path", "~/.vyren/notices.json").replace(
            "audit.log", "notices.json"
        )
    )
    heartbeat = Heartbeat(
        notice_store=notice_store,
        config=config.get("heartbeat", {"enabled": False, "interval_seconds": 300, "checks": []}),
        on_notice=lambda n: print(f"\n  [Notice] {n['message']}\n"),
    )
    if config.get("heartbeat.enabled", False):
        heartbeat.start()
        pending = notice_store.count_pending()
        if pending:
            print(f"  {pending} pending notice(s) from heartbeat.")

    print_welcome(registry)
    audit.info("VYREN started")

    # ------------------------------------------------------------------
    # Main conversation loop
    # ------------------------------------------------------------------
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nGoodbye.\n")
            audit.info("VYREN stopped (Ctrl+C)")
            break

        # Handle commands
        cmd = user_input.lower()
        if cmd in ("/quit", "/exit", "/q"):
            print("\nGoodbye.\n")
            audit.info("VYREN stopped (quit command)")
            break

        if cmd == "/kill":
            safety.activate_kill_switch()
            print("\n  Kill switch ON. All proactive behavior paused.\n")
            audit.security("Kill switch activated")
            continue

        if cmd == "/unkill":
            safety.deactivate_kill_switch()
            print("\n  Kill switch OFF. Normal behavior resumed.\n")
            audit.security("Kill switch deactivated")
            continue

        if cmd == "/tools":
            print(f"\n  Available tools ({len(registry.tool_names())}):\n")
            for name in registry.tool_names():
                tool = registry.get(name)
                level = "CONSEQUENTIAL" if tool.safety_level == "consequential" else "safe"
                print(f"    {name}  [{level}]")
                print(f"      {tool.description[:80]}\n")
            continue

        if cmd == "/memory":
            facts = mem.list_all()
            if not facts:
                print("\n  Memory is empty.\n")
            else:
                print(f"\n  Memory ({len(facts)} entries):\n")
                for f in facts:
                    print(f"    {f['key']}: {f['value']}")
                print()
            continue

        if cmd == "/clear":
            history.clear()
            print("\n  Conversation history cleared. Memory preserved.\n")
            audit.info("Conversation history cleared")
            continue

        if cmd == "/status":
            from provider import _ollama_available
            hb_status = heartbeat.get_status()
            print(f"\n  VYREN Status:")
            print(f"    Tools: {len(registry.tool_names())}")
            print(f"    Memory: {mem.count()} entries")
            print(f"    Kill switch: {'ACTIVE' if safety.is_killed() else 'off'}")
            print(f"    Ollama (offline): {'available' if _ollama_available() else 'not running'}")
            print(f"    Heartbeat: {'running' if hb_status['running'] else 'stopped'}")
            print(f"    Pending notices: {hb_status['pending_notices']}")
            print(f"    Model: {config.get('model.name', 'gemini-2.5-flash')}")
            print()
            continue

        if cmd == "/notices":
            pending = notice_store.get_pending()
            if not pending:
                print("\n  No pending notices.\n")
            else:
                print(f"\n  {len(pending)} pending notice(s):\n")
                for n in pending:
                    print(f"    [{n['urgency']}] {n['message']}")
                    print(f"      ({n['timestamp']})")
                    notice_store.dismiss(n["id"])
                print("  All dismissed.\n")
            continue

        if cmd == "/heartbeat":
            if heartbeat.is_running:
                heartbeat.stop()
                print("\n  Heartbeat stopped.\n")
            else:
                hb_config = config.get("heartbeat", {})
                hb_config["enabled"] = True
                heartbeat.start()
                print("\n  Heartbeat started.\n")
            continue

        if cmd == "/voice-info":
            from voice import voice_available
            v = voice_available()
            print(f"\n  Voice Status:")
            print(f"    STT (Deepgram): {'available' if v['stt'] else 'no key'}")
            print(f"    TTS (ElevenLabs): {'available' if v['tts'] else 'no key'}")
            print(f"    Recording: {'available' if v['recording'] else 'sounddevice not installed'}")
            print(f"    Ready: {'YES' if v['ready'] else 'NO'}")
            if v["reason"]:
                print(f"    Missing: {v['reason']}")
            print(f"    Browser voice: always available in the web dashboard\n")
            continue

        if cmd == "/voice":
            from voice import voice_available, push_to_talk_loop
            v = voice_available()
            if not v["ready"]:
                print(f"\n  Voice not ready: {v['reason']}")
                print("  Use browser voice (dashboard) or install dependencies.\n")
                continue

            def process_voice_text(text):
                """Process a voice message through the agent loop."""
                nonlocal history
                history.append(_user_message(text))
                audit.model_turn("user", text)
                chunks = []
                result = run_turn(history, system_prompt, gemini_tools, on_chunk=lambda t: print(t, end="", flush=True))
                if result.text:
                    if not result.text.endswith("\n"):
                        print()
                    print()
                    history.append(_model_message(result.text))
                    audit.model_turn("model", result.text)

            push_to_talk_loop(process_voice_text)
            continue

        if not user_input:
            continue

        # --------------------------------------------------------------
        # Agent turn: send to model, handle tool calls, get reply
        # --------------------------------------------------------------
        # Append user message
        history.append(_user_message(user_input))
        audit.model_turn("user", user_input)

        # Stream text chunks to terminal
        def on_chunk(text: str):
            print(text, end="", flush=True)

        # Run the model
        result = run_turn(
            messages=history,
            system_prompt=system_prompt,
            tools=gemini_tools,
            on_chunk=on_chunk,
        )

        # --------------------------------------------------------------
        # Tool calling loop
        # --------------------------------------------------------------
        max_tool_rounds = 10  # Safety limit to prevent infinite loops
        tool_round = 0

        while result.function_calls and tool_round < max_tool_rounds:
            tool_round += 1

            # Build the model's response part (text + function calls)
            model_parts = []
            if result.text:
                model_parts.append({"text": result.text})
            for fc in result.function_calls:
                model_parts.append({
                    "function_call": {"name": fc.name, "args": fc.args}
                })
            history.append({"role": "model", "parts": model_parts})

            # Execute each tool call
            tool_results = []
            for fc in result.function_calls:
                # Safety gate: consequential tools require confirmation
                if registry.is_consequential(fc.name):
                    approved = safety.ask_confirmation(fc.name, fc.args)
                    audit.confirmation(fc.name, fc.args, approved)

                    if not approved:
                        tool_results.append({
                            "function_response": {
                                "name": fc.name,
                                "response": {
                                    "result": (
                                        "User declined this action. "
                                        "Do not retry without asking again."
                                    )
                                },
                            }
                        })
                        audit.info(f"Tool {fc.name} declined by user")
                        continue

                # Execute the tool
                audit.info(f"Executing tool: {fc.name}")
                tool_output = registry.execute(fc.name, fc.args)
                audit.tool_call(fc.name, fc.args, tool_output[:100])

                # Check for special "REQUESTED" sentinel values
                # (used by tools that need post-confirmation execution)
                if tool_output.endswith("_REQUESTED"):
                    tool_output = _execute_post_confirmation(fc.name, fc.args, tool_output)

                tool_results.append({
                    "function_response": {
                        "name": fc.name,
                        "response": {"result": tool_output},
                    }
                })

            # Add tool results to history (as "user" role per Gemini spec)
            history.append({"role": "user", "parts": tool_results})

            # Send back to model for next round
            result = run_turn(
                messages=history,
                system_prompt=system_prompt,
                tools=gemini_tools,
                on_chunk=on_chunk,
            )

        # --------------------------------------------------------------
        # Finalize the turn
        # --------------------------------------------------------------
        if result.text:
            if not result.text.endswith("\n"):
                print()
            print()  # Blank line for readability
            audit.model_turn("model", result.text)
            history.append(_model_message(result.text))

        elif not result.function_calls:
            # Model produced no text and no tools — print a newline
            print("\n")


def _user_message(text: str) -> dict:
    return {"role": "user", "parts": [{"text": text}]}


def _execute_post_confirmation(name: str, args: dict, sentinel: str) -> str:
    """Execute actions that were approved through the confirmation gate."""
    try:
        if name == "shutdown_system":
            import subprocess
            subprocess.run(["shutdown", "/s", "/t", "5"], check=False)
            return "Shutdown initiated."
        elif name == "restart_system":
            import subprocess
            subprocess.run(["shutdown", "/r", "/t", "5"], check=False)
            return "Restart initiated."
        elif name == "delete_file":
            path = args.get("file_path", "")
            os.remove(path)
            return f"Deleted: {path}"
        elif name == "edit_file":
            path = args.get("file_path", "")
            content = args.get("content", "")
            resolved = os.path.realpath(path)
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
            lines = content.count("\n") + 1
            return f"File written: {resolved} ({lines} lines)"
        elif name == "run_python":
            import subprocess
            code = args.get("code", "")
            timeout = args.get("timeout", 30)
            result = subprocess.run(
                ["python3", "-c", code],
                capture_output=True, text=True, timeout=timeout,
            )
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            return output if output.strip() else "(no output)"
        else:
            return sentinel
    except Exception as e:
        return f"Error executing {name}: {type(e).__name__} — {e}"


def _model_message(text: str) -> dict:
    return {"role": "model", "parts": [{"text": text}]}


if __name__ == "__main__":
    run()