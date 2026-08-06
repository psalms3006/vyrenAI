"""
runtime/terminal.py -- Terminal text interaction loop.

Text is VYREN's SECONDARY interface. Voice is primary.
This provides a REPL for when you're at a keyboard and prefer to type.
Voice, text, and web UI all share ONE BRAIN.

FIX (2026-07-16): Unified conversation architecture.
Previously, typed text went through provider.run_turn() — a completely
separate text-only LLM call with its own history, independent of the
Gemini Live voice session. This caused:
  - Two parallel conversations running simultaneously (confusing output)
  - Typed input never produced spoken replies (user expected voice response)
  - Voice and text had disjoint context/history

NOW: When voice is active (voice_runtime.is_active), typed text is
routed into the live voice session via voice_runtime.send_text(), which
sends it to Gemini Live's send_realtime_input(text=...). Gemini responds
with AUDIO (spoken reply), giving the user one unified conversation
whether they speak or type.

When voice is NOT active (no GEMINI_API_KEY or engine failed), typed
text falls back to the original provider.run_turn() text-only path with
full tool-calling support.
"""

import logging
import os
import sys
import threading

logger = logging.getLogger("vyren.terminal")


def start_terminal_loop(ctx: dict, shutdown_event: threading.Event, interaction_controller=None):
    """
    Start the terminal text loop in a background thread.

    interaction_controller: optional interaction controller used for
    mode-aware input handling.
    """
    t = threading.Thread(target=_terminal_loop, args=(ctx, shutdown_event, interaction_controller),
                         name="vyren-terminal", daemon=True)
    t.start()
    return t


def _terminal_loop(ctx: dict, shutdown_event: threading.Event, interaction_controller=None):
    """The terminal REPL loop."""
    import safety
    from provider import run_turn

    history: list = []
    registry = ctx.get("registry")
    audit = ctx.get("audit")
    voice_runtime = ctx.get("voice_runtime")

    while not shutdown_event.is_set():
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if shutdown_event.is_set():
            break

        cmd = user_input.lower()

        # ---- Slash Commands ----
        if cmd in ("/quit", "/exit", "/q"):
            shutdown_event.set()
            print("\n  Shutting down VYREN...\n")
            break

        if cmd == "/help":
            print()
            print("  VYREN Text Interface (secondary — voice is primary)")
            print("  Commands:")
            print("    /quit         - Shut down VYREN")
            print("    /kill         - Activate kill switch")
            print("    /unkill       - Deactivate kill switch")
            print("    /tools        - List tools")
            print("    /memory       - Show memory")
            print("    /status       - System health")
            print("    /voice        - Voice status")
            print("    /clear        - Clear conversation")
            print("    /notices      - Show pending notices")
            print("    /agents       - Show agent status")
            print("    /connectivity - Network status")
            print("    /help         - This message")
            print()
            continue

        if cmd == "/kill":
            safety.activate_kill_switch()
            print("\n  Kill switch ON.\n")
            if audit:
                audit.security("Kill switch activated (terminal)")
            continue

        if cmd == "/unkill":
            safety.deactivate_kill_switch()
            print("\n  Kill switch OFF.\n")
            if audit:
                audit.security("Kill switch deactivated (terminal)")
            continue

        if cmd == "/tools" and registry:
            print(f"\n  Tools ({len(registry.tool_names())}):\n")
            for name in registry.tool_names():
                tool = registry.get(name)
                level = "CONSEQUENTIAL" if tool.safety_level == "consequential" else "safe"
                print(f"    {name}  [{level}]  {tool.description[:60]}")
            print()
            continue

        if cmd == "/memory":
            memory = ctx.get("memory")
            if memory:
                facts = memory.list_all()
                if not facts:
                    print("\n  Memory is empty.\n")
                else:
                    print(f"\n  Memory ({len(facts)} entries):\n")
                    for f in facts[:20]:
                        print(f"    {f['key']}: {f['value'][:80]}")
                    if len(facts) > 20:
                        print(f"    ... and {len(facts) - 20} more")
                    print()
            continue

        if cmd == "/status":
            health = ctx.get("health")
            if health:
                status = health.get_status()
                print(f"\n  Health Status:")
                for k, v in status.items():
                    icon = "[OK]" if v == "healthy" else "[!!]"
                    print(f"    {icon} {k}: {v}")
                print()
            connectivity = ctx.get("connectivity")
            if connectivity:
                print(f"  Connectivity: {connectivity.mode.value}")
                print(f"    Internet: {connectivity.status.internet_available}")
                print(f"    Gemini: {connectivity.status.gemini_available}")
                print(f"    Ollama: {connectivity.status.ollama_available}")
                print()
            print()
            continue

        if cmd == "/voice":
            if voice_runtime and voice_runtime.is_active:
                caps = voice_runtime.get_status().get("capabilities", {})
                print(f"\n  Voice: {voice_runtime.mode}")
                print(f"  State: {voice_runtime.get_status().get('state', 'unknown')}")
                print(f"  Wake word: 'Hey Vyren'")
                print(f"  Online STT (Deepgram): {'yes' if caps.get('stt') else 'no'}")
                print(f"  Online TTS (ElevenLabs): {'yes' if caps.get('tts') else 'no'}")
                print(f"  Gemini Live: {'yes' if caps.get('gemini_live') else 'no'}")
                print(f"  Local TTS (pyttsx3): {'yes' if caps.get('local_tts') else 'no'}")
                print(f"  Local STT (Whisper): {'yes' if caps.get('local_stt') else 'no'}")
                print()
            else:
                print("\n  Voice not active. Check that sounddevice is installed.\n")
            continue

        if cmd == "/clear":
            history.clear()
            print("\n  Conversation cleared.\n")
            continue

        if cmd == "/notices":
            ns = ctx.get("notice_store")
            if ns:
                pending = ns.get_pending()
                if not pending:
                    print("\n  No pending notices.\n")
                else:
                    print(f"\n  {len(pending)} notice(s):\n")
                    for n in pending:
                        print(f"    [{n['urgency']}] {n['message']}")
                    print()
            continue

        if cmd == "/agents":
            coord = ctx.get("coordinator")
            if coord:
                status = coord.get_status()
                print(f"\n  Agents ({status.get('registered_agents', 0)}):\n")
                for agent in status.get("agents", []):
                    caps = ", ".join(agent.get("capabilities", []))
                    print(f"    {agent['name']}: {caps}")
                print()
            continue

        if cmd == "/connectivity":
            connectivity = ctx.get("connectivity")
            if connectivity:
                s = connectivity.status
                print(f"\n  Mode: {s.mode.value}")
                print(f"  Internet: {s.internet_available}")
                print(f"  Gemini: {s.gemini_available}")
                print(f"  Ollama: {s.ollama_available}")
                print(f"  Latency: {s.latency_ms}ms")
                print(f"  Transitions: {s.transition_count}\n")
            else:
                print("\n  Connectivity manager not available.\n")
            continue

        if not user_input:
            continue

        try:
            if interaction_controller is not None:
                interaction_controller.on_user_input()
                if not interaction_controller.may_speak():
                    # If voice is unavailable/in fallback, typed input must
                    # still work. Force conversation mode so the user is
                    # never silently blocked from the text fallback.
                    if voice_runtime and getattr(voice_runtime, "mode", None) == "fallback":
                        try:
                            interaction_controller.set_user_mode("conversation")
                        except Exception:
                            pass
                    if not interaction_controller.may_speak():
                        print("  [VYREN is quiet — enable conversation mode or use wake word]")
                        continue
        except Exception:
            pass

        # ---- Conversation Turn ----
        # UNIFIED CONVERSATION (2026-07-16 fix):
        # When voice is active, route typed text into the live voice session
        # for spoken replies. This gives ONE conversation whether user
        # speaks or types — no more two parallel brains.
        #
        # Voice session uses tools=None (voice-first design — see
        # voice/runtime.py _build_live_config() rationale). If the user
        # needs tool-calling from typed input, use /text mode or when
        # voice is unavailable.
        
        use_voice = (
            voice_runtime
            and voice_runtime.is_active
            and voice_runtime.mode != "fallback"
        )
        if use_voice:
            try:
                if interaction_controller is not None:
                    interaction_controller.on_user_input()
                    # In fallback mode there is no voice path, so typed input
                    # must always reach the text fallback. Only enforce quiet
                    # mode when a real voice session could otherwise handle it.
                    if (
                        voice_runtime is not None
                        and getattr(voice_runtime, "mode", None) == "fallback"
                    ):
                        pass
                    elif not interaction_controller.may_speak():
                        print("  [VYREN is quiet — enable conversation mode or use wake word]")
                        continue
            except Exception:
                pass
        
        if use_voice:
            # --- Voice-active path: send to Gemini Live for SPOKEN reply ---
            logger.info("Terminal input -> Voice session (spoken reply): '%s'", 
                       user_input[:80])
            
            if audit:
                audit.model_turn("user", user_input)
                audit.info("Terminal text routed to voice session")
            
            voice_runtime._reply_event.clear()
            voice_runtime.send_text(user_input)
            history.append({"role": "user", "parts": [{"text": user_input}]})
            
            if voice_runtime._reply_event.wait(timeout=voice_runtime._pending_reply_timeout):
                reply = voice_runtime.get_last_assistant_reply()
                if reply:
                    print(f"  VYREN: {reply}\n")
            else:
                # Hard fallback: voice turn timed out, use text path so the
                # user always gets a response instead of hanging silently.
                print("  [Voice turn timed out — switching to text fallback...]\n")
                _handle_text_only_turn(ctx, history, user_input, registry, audit)
            
        elif not registry:
            print("  [System not ready]\n")
            continue
            
        else:
            # --- Fallback path: voice inactive, use text-only LLM with tools ---
            # This is the original provider.run_turn() path, used when:
            #   - No GEMINI_API_KEY set (fallback/offline mode)
            #   - Voice engine failed/stopped
            #   - User explicitly wants text-only mode (future: /text command)
            _handle_text_only_turn(ctx, history, user_input, registry, audit)


def _handle_text_only_turn(ctx: dict, history: list, user_input: str, 
                           registry, audit):
    """Handle a conversation turn using the text-only LLM (provider.run_turn).
    
    This is the FALLBACK path used when voice is not available.
    Supports full tool-calling via registry.
    """
    import safety
    from provider import run_turn
    
    system_prompt = ctx.get("system_prompt", "")
    gemini_tools = ctx.get("gemini_tools", [])

    history.append({"role": "user", "parts": [{"text": user_input}]})
    if audit:
        audit.model_turn("user", user_input)

    def on_chunk(text: str):
        print(text, end="", flush=True)

    result = run_turn(
        messages=history,
        system_prompt=system_prompt,
        tools=gemini_tools,
        on_chunk=on_chunk,
    )

    # Tool calling loop
    max_tool_rounds = 10
    tool_round = 0

    while result.function_calls and tool_round < max_tool_rounds:
        tool_round += 1

        model_parts = []
        if result.text:
            model_parts.append({"text": result.text})
        for fc in result.function_calls:
            model_parts.append({
                "function_call": {"name": fc.name, "args": fc.args}
            })
        history.append({"role": "model", "parts": model_parts})

        tool_results = []
        for fc in result.function_calls:
            if registry.is_consequential(fc.name):
                approved = safety.ask_confirmation(fc.name, fc.args)
                if audit:
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
                if audit:
                    audit.info(f"Tool {fc.name} declined by user")
                continue

            if audit:
                audit.info(f"Executing tool: {fc.name}")
            tool_output = registry.execute(fc.name, fc.args)
            if audit:
                audit.tool_call(fc.name, fc.args, tool_output[:100])

            if tool_output.endswith("_REQUESTED"):
                tool_output = _execute_post_confirmation(fc.name, fc.args, tool_output)

            tool_results.append({
                "function_response": {
                    "name": fc.name,
                    "response": {"result": tool_output},
                }
            })

        history.append({"role": "user", "parts": tool_results})

        result = run_turn(
            messages=history,
            system_prompt=system_prompt,
            tools=gemini_tools,
            on_chunk=on_chunk,
        )

    # Finalize
    if result.text:
        if not result.text.endswith("\n"):
            print()
        print()
        if audit:
            audit.model_turn("model", result.text)
        history.append({"role": "model", "parts": [{"text": result.text}]})
    elif not result.function_calls:
        print("\n")

    # Trim history to prevent memory growth
    if len(history) > 50:
        history = history[-30:]


def _execute_post_confirmation(name: str, args: dict, sentinel: str) -> str:
    """Execute actions approved through the confirmation gate."""
    from post_confirmation import execute_post_confirmation
    return execute_post_confirmation(name, args, sentinel)