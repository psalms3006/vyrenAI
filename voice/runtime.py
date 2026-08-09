"""
voice/runtime.py -- VYREN's voice runtime.

This is a THIN ADAPTER that connects VYREN's brain, memory, tools,
and personality to the shared voice_engine.

The shared engine handles:
  - Gemini Live Native Audio connection
  - Mic capture, speaker playback
  - Streaming, barge-in, reconnection
  - Turn management, state machine, diagnostics
  - Worker supervision and automatic restart

VYREN only provides:
  - System prompt (with memory, world model, KG context)
  - Tool declarations (from ToolRegistry → Gemini format)
  - Tool execution (via ToolRegistry.execute)
  - Turn completion handling (audit, memory)
  - Dynamic config rebuild (NOVA's _build_config pattern)

Architecture:
  VYREN Brain/Tools/Memory
          ↓ (AssistantCallbacks + build_config_callback)
  Shared Voice Engine (voice_engine/)
          ↓
  Gemini Live Native Audio
          ↓
  Mic ↔ Speakers

v2.2 changes:
  - Added _build_live_config() — rebuilds system prompt with fresh
    memory/time context on every connect/reconnect (NOVA's pattern).
  - Passes build_config_callback to engine config.
  - Engine calls this on every session, so stale memory/time is impossible.
"""

import asyncio
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any

try:
    from google.genai import types as _genai_types
except Exception as _genai_import_exc:  # pragma: no cover - optional dependency absent
    logging.getLogger("vyren.voice").error(
        "google.genai import failed — Gemini Live will be unavailable: %s",
        _genai_import_exc, exc_info=True,
    )
    class _FakeGenaiTypes:
        LiveConnectConfig = object  # type: ignore[assignment]
    _genai_types = _FakeGenaiTypes()  # type: ignore[assignment]


class _FakeModule:
    def __getattr__(self, name):
        return _FakeModule()


def _genai_live_available() -> bool:
    return (
        isinstance(getattr(_genai_types, "LiveConnectConfig", None), type)
        and not isinstance(GeminiLiveVoiceEngine, _FakeModule)
    )


types = _genai_types  # type: ignore[assignment]

try:
    from voice_engine import GeminiLiveVoiceEngine, AssistantCallbacks, VoiceState
    from voice_engine.protocol import ToolCall, ToolResult, TurnTranscription, VoiceEngineConfig
    from voice_engine import diagnostics as diag
    from voice_engine.conversation_manager import ConversationPhase
except Exception as _voice_engine_import_exc:  # pragma: no cover - optional dependency absent
    logging.getLogger("vyren.voice").error(
        "voice_engine import failed — Gemini Live will be unavailable: %s",
        _voice_engine_import_exc, exc_info=True,
    )
    class _FakeModule:
        def __getattr__(self, name):
            return _FakeModule()
    GeminiLiveVoiceEngine = AssistantCallbacks = VoiceState = _FakeModule()  # type: ignore[assignment,misc]
    ToolCall = ToolResult = TurnTranscription = VoiceEngineConfig = _FakeModule()  # type: ignore[assignment,misc]
    diag = _FakeModule()  # type: ignore[assignment]
    ConversationPhase = _FakeModule()  # type: ignore[assignment]

logger = logging.getLogger("vyren.voice")


class VoiceRuntime:
    """
    VYREN's voice runtime. Plugs VYREN into the shared voice engine.

    Boot sequence:
    1. Build system prompt with memory/world model/KG context
    2. Convert VYREN's tool registry to Gemini tool declarations
    3. Create AssistantCallbacks that routes tools through VYREN's registry
    4. Create GeminiLiveVoiceEngine with those callbacks + build_config_callback
    5. Start the engine in a background thread

    The engine handles everything else. This class is just the glue.
    """

    # Immutable by construction — a Python class constant, not a value
    # read from memory, ctx, or a config file, so nothing at runtime
    # (a memory write, a mis-parsed YAML, a bad env var) can alter it.
    # This is placed FIRST in every system prompt build, ahead of
    # memory/KG/world-model context, and given explicit instruction
    # below to override pretrained-model assumptions.
    _IDENTITY_BLOCK = (
        "## Identity (read this first — this overrides anything the "
        "underlying model would otherwise assume)\n"
        "You are VYREN. This is not a persona or character — it is what "
        "you are.\n"
        "- Creator, owner, primary user, architect: Psalms Samuel Asagwara "
        "(goes by \"Psalms\"), a Mechatronics Engineering student at the "
        "Federal University of Technology, Owerri (FUTO), Nigeria.\n"
        "- Purpose: an autonomous AI operating system — reasoning, "
        "planning, learning, and executing tasks, not a chat widget.\n"
        "- Sibling AI: NOVA, built by the same creator.\n"
        "- Conversational style: direct, warm, calm, intelligent, "
        "concise unless depth is asked for — an educated Nigerian voice, "
        "not a corporate one.\n"
        "\n"
        "Rules for identity questions (who made you / who owns you / "
        "who created you / who designed you / what are you / why were "
        "you built / what is your mission / who is your primary user):\n"
        "- Answer ONLY from the facts above. Never say \"a team of "
        "engineers,\" \"a group of developers,\" \"OpenAI,\" "
        "\"Anthropic,\" or any other generic/pretrained answer about who "
        "made you. Your creator is Psalms Samuel Asagwara — full stop.\n"
        "- Don't confuse your creator with the model currently doing "
        "your reasoning. Correct: \"I'm VYREN, my reasoning is currently "
        "powered by Gemini, but Psalms built me.\" Wrong: \"Gemini "
        "created me.\"\n"
        "- Never use stock AI-assistant phrasing (\"As an AI language "
        "model...\", \"I was trained by...\", \"I don't have a creator, "
        "I was developed by a team...\") unless it's literally true "
        "given the facts above, which for creator/ownership questions "
        "it is not.\n"
        "\n"
        "General honesty rule, not just for identity: if you genuinely "
        "don't know something, say so plainly — \"I don't know,\" \"I "
        "don't have enough information,\" \"I haven't learned that yet.\" "
        "Do not fill a gap with a statistically plausible but unverified "
        "answer. Uncertainty should sound intelligent, not apologetic — "
        "no \"I'm sorry, but as an AI...\"."
    )

    def __init__(self, ctx: dict):
        self._ctx = ctx
        self._active = False
        self._stop_event = threading.Event()
        self._engine: GeminiLiveVoiceEngine | None = None
        self._engine_thread: threading.Thread | None = None

        # Fallback state (if Gemini Live not available)
        self._fallback_mode = False
        self._fallback_thread: threading.Thread | None = None

        # State callbacks for web UI
        self._state_callbacks: list = []
        self._state = "stopped"

        # Shared conversation history — both the online (Gemini Live) and
        # offline loop write here, so switching modes mid-conversation
        # doesn't reset context to zero. Gemini-message format:
        # {"role": "user"|"model", "parts": [{"text": ...}]}
        self.recent_turns: list[dict] = []
        self._max_recent_turns = 20

        self._offline_loop = None  # voice.offline_loop.OfflineVoiceLoop, lazy-created

        # Connectivity-driven voice mode state.
        # These are the single source of truth for voice mode transitions,
        # separate from the engine's own reconnect loop. The connectivity
        # manager can ask these directly and the voice runtime can also
        # force transitions on repeated engine failures.
        self._voice_failure_count = 0
        self._voice_recovery_check_interval_s = 30.0
        self._voice_recovery_required_successes = 2

        # Mark-style unified conversation: typed input goes through the
        # same live session as voice. Reply surfacing uses a small
        # synchronization primitive so the terminal can wait for and print
        # the assistant's response instead of dropping it.
        self._reply_event = threading.Event()
        self._last_reply = ""
        self._pending_reply_timeout = 60.0

        # Shared conversation lifecycle trackers.
        # ConversationManager tracks human-facing phase; VoiceSupervisor adds
        # higher-level recovery checks without replacing the engine internals.
        try:
            from voice_engine.conversation_manager import ConversationManager
            self._conversation_manager = ConversationManager()
        except Exception:
            self._conversation_manager = None

        try:
            from voice_engine.voice_supervisor import VoiceSupervisor
            self._voice_supervisor = VoiceSupervisor(
                conversation_manager=self._conversation_manager,
            )
        except Exception:
            self._voice_supervisor = None

        # Configurable threshold for connectivity-driven mode transitions.
        try:
            import config as _cfg
            self._voice_failure_threshold = int(
                _cfg.get("connectivity.voice_failure_threshold", 3)
            )
        except Exception:
            self._voice_failure_threshold = 3

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def mode(self) -> str:
        if self._fallback_mode:
            return "fallback"
        if self._engine and self._engine.is_active:
            return "gemini_live"
        return "stopped"

    @property
    def wake_word(self) -> str:
        try:
            from identity import get_wake_word
            return get_wake_word()
        except Exception:
            return "vyren"

    def on_state_change(self, callback):
        self._state_callbacks.append(callback)

    def _notify_state(self, state):
        self._state = state
        cm = self._conversation_manager
        if cm is not None:
            try:
                mapping = {
                    "listening": ConversationPhase.LISTENING,
                    "idle": ConversationPhase.LISTENING,
                    "thinking": ConversationPhase.THINKING,
                    "speaking": ConversationPhase.SPEAKING,
                    "interrupted": ConversationPhase.INTERRUPTED,
                    "reconnecting": ConversationPhase.RECONNECTING,
                }
                target = mapping.get(state)
                if target is not None:
                    cm.transition(target, reason="runtime state")
            except Exception:
                pass
        for cb in self._state_callbacks:
            try:
                cb(state)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Start the voice runtime."""
        api_key = os.environ.get("GEMINI_API_KEY")

        if api_key:
            self._start_gemini_live(api_key)
        else:
            logger.warning("No GEMINI_API_KEY — falling back to wake-word mode")
            self._start_fallback(reason="no_api_key")

    def stop(self):
        self._active = False
        self._stop_event.set()
        if self._engine:
            self._engine.stop()
        if self._offline_loop:
            self._offline_loop.stop()
            self._offline_loop = None
        if getattr(self, "_voice_supervisor", None):
            try:
                self._voice_supervisor.stop()
            except Exception:
                pass
        if getattr(self, "_conversation_manager", None):
            try:
                self._conversation_manager.reset()
            except Exception:
                pass
        for t in [self._engine_thread, self._fallback_thread]:
            if t and t.is_alive():
                t.join(timeout=5)

    def interrupt(self):
        """Barge-in: not needed with the shared engine — it handles this natively."""
        pass

    def speak(self, text: str):
        """Speak text aloud."""
        if not text:
            return
        try:
            ctrl = self._ctx.get("interaction_controller")
            if ctrl is not None and not ctrl.may_speak():
                return
        except Exception:
            pass
        if self._engine and self._engine.is_active:
            self._engine.send_text(text)
        else:
            self._speak_fallback(text)

    def send_text(self, text: str):
        """Send text input into the voice session."""
        if not text or not text.strip():
            return
        try:
            ctrl = self._ctx.get("interaction_controller")
            if ctrl is not None:
                ctrl.on_user_input()
                if not ctrl.may_speak():
                    return
        except Exception:
            pass
        if self._engine and self._engine.is_active:
            self._engine.send_text(text.strip())
        elif self._offline_loop is not None:
            self._offline_loop.handle_text(text.strip())
        else:
            logger.warning(
                "[TEXT] No active engine and no offline loop — typed "
                "input has nowhere to go. Voice mode is '%s'.", self.mode,
            )

    def get_last_assistant_reply(self) -> str:
        # Was: joining every model-role turn in recent_turns, reversed —
        # which doesn't return "the last reply", it concatenates the
        # entire conversation history backwards into one ever-growing
        # string. self._last_reply is already correctly maintained
        # per-turn in _on_turn_complete; just use it.
        return (self._last_reply or "").strip()

    def get_status(self) -> dict:
        status = {
            "active": self._active,
            "mode": self.mode,
            "state": self._state,
            "wake_word": self.wake_word,
            "capabilities": {
                "gemini_live": bool(os.environ.get("GEMINI_API_KEY")),
                "recording": self._has_sounddevice(),
            },
            "is_speaking": self._engine.is_speaking if self._engine else False,
            "has_live_session": self._engine.is_active if self._engine else False,
        }

        # Include diagnostic counters for observability
        counters = diag.get_counters()
        status["diagnostics"] = {
            "mic_frames_sent": counters.get("mic_frames_sent", 0),
            "mic_frames_dropped": counters.get("mic_frames_dropped", 0),
            "speaker_frames_played": counters.get("speaker_frames_played", 0),
            "turns_completed": counters.get("turns_completed", 0),
            "reconnect_count": counters.get("reconnect_count", 0),
            "errors": counters.get("errors", 0),
            "tool_calls": counters.get("tool_calls", 0),
            "session_uptime_s": (
                time.monotonic() - counters.get("session_start_time", time.monotonic())
            ),
        }

        return status

    # ------------------------------------------------------------------
    # Gemini Live (Primary) — via shared engine
    # ------------------------------------------------------------------

    def _start_gemini_live(self, api_key: str):
        """Start VYREN using the shared voice engine."""
        self._active = True
        self._stop_event.clear()

        if self._conversation_manager:
            try:
                self._conversation_manager.reset()
            except Exception:
                pass

        if not _genai_live_available():
            logger.warning("Gemini Live unavailable — falling back to offline voice")
            self._start_fallback(reason="live_unavailable")
            return

        if self._voice_supervisor:
            try:
                self._voice_supervisor.stop()
            except Exception:
                pass
            try:
                self._voice_supervisor.set_recovery_handlers(
                    on_reconnect=self._request_reconnect,
                    on_reset_queues=self._reset_audio_queues,
                    on_mic_restart=self._restart_mic_worker,
                    on_speaker_restart=self._restart_speaker_worker,
                )
                self._voice_supervisor.start(stop_event=self._stop_event)
            except Exception as exc:
                logger.debug("Voice supervisor start failed: %s", exc)

        # Create callbacks — this is where VYREN plugs in
        callbacks = AssistantCallbacks(
            on_tool_call=self._on_tool_call,
            on_turn_complete=self._on_turn_complete,
            on_state_change=self._on_engine_state_change,
            on_transcription=self._on_transcription,
            on_connected=self._on_connected,
            on_error=self._on_error,
        )

        # Build engine config with build_config_callback
        # The engine will call _build_live_config() on every connect/reconnect,
        # ensuring fresh memory/time context (NOVA's _build_config pattern).
        # NOTE: Voice gets a small, fixed vision-tool subset (see
        # _build_live_config) — not the full 47-tool registry. The text
        # pipeline still gets full tool access via provider.py.
        config = VoiceEngineConfig(
            api_key=api_key,
            system_prompt=self._build_system_prompt(),  # Initial prompt
            voice_name="Charon",
            build_config_callback=self._build_live_config,
        )

        self._engine = GeminiLiveVoiceEngine(config, callbacks)

        # Start in background thread
        self._engine_thread = threading.Thread(
            target=self._engine.run,
            name="vyren-voice-engine",
            daemon=True,
        )
        self._engine_thread.start()
        logger.info("Voice: Gemini Live engine started (shared architecture v2.4)")

        # Reset voice connectivity failure counter on successful start.
        # This does not mean the WebSocket connected yet — that is
        # signaled separately by _on_connected() — but starting a fresh
        # Gemini Live session means any prior consecutive failures are
        # no longer relevant.
        self._voice_failure_count = 0
        try:
            import config as _cfg
            self._voice_recovery_check_interval_s = float(
                _cfg.get("connectivity.voice_recovery_check_interval_s", 30.0)
            )
            self._voice_recovery_required_successes = int(
                _cfg.get("connectivity.voice_recovery_required_successes", 2)
            )
        except Exception:
            pass

    def _build_live_config(self) -> types.LiveConnectConfig:
        """Build a fresh LiveConnectConfig for each connect/reconnect.

        This is NOVA's _build_config() pattern. Every time the engine
        connects or reconnects to Gemini, it gets a config with:
          - Fresh system prompt (current memory, time, world model)
          - A small, fixed vision-tool subset (see below) — not the
            full 47-tool registry the text pipeline gets
        """
        # Rebuild system prompt with fresh memory/time context
        system_prompt = self._build_system_prompt()

        # VOICE-FIRST, WITH ONE DELIBERATE EXCEPTION: vision.
        #
        # Both NOVA and Mark's production pipelines avoid passing all 47
        # tool declarations to the audio WebSocket. Reasons that still
        # hold:
        #   1. Gemini Live with 35+ tools causes 1007 config errors
        #      (tool name validation, parameter schema size limits)
        #   2. Voice sessions should be CONVERSATION-only by default. Tool
        #      use adds latency (tool execution blocks the response) and
        #      breaks the real-time flow (user hears silence while a tool
        #      runs)
        #
        # But "zero tools" also means Gemini can never actually call
        # capture_screen/capture_and_analyze during a voice conversation —
        # when asked "what's on my screen," it has no way to find out, so
        # it narrates a plausible-sounding answer instead. That's not a
        # vision-tool bug (the tool itself really captures the screen and
        # really calls Gemini Vision, verified directly in
        # tools/screen_tools.py) — it's that voice was never given the
        # ability to call it at all.
        #
        # Fix: pass a small, fixed tool subset — vision (4 tools) plus
        # remember/recall (2 tools), still nowhere near the size that
        # triggers 1007 — so vision requests trigger a real capture, and
        # the "persist standing preferences" instruction above has an
        # actual tool to call instead of a system prompt telling the
        # model to do something it structurally can't do. Everything
        # else (filesystem, terminal, scheduler, etc.) stays
        # text-pipeline-only, unchanged.
        registry = self._ctx.get("registry")
        voice_tools = None
        if registry:
            try:
                voice_tools = registry.to_gemini_tools(names=[
                    "capture_screen",
                    "capture_and_analyze",
                    "analyze_image",
                    "edit_file",
                    "list_directory",
                    "read_file",
                    "browser_control",
                    "open_app",
                    "remember",
                    "recall",
                ]) or None
            except Exception as e:
                logger.warning("Voice tool subset unavailable, continuing without tools: %s", e)
                voice_tools = None

        logger.info(
            "Building LiveConnectConfig: prompt=%d chars, tools=%s (voice-first + vision + memory)",
            len(system_prompt),
            (len(voice_tools[0]["function_declarations"]) if voice_tools else 0),
        )

        live_kwargs = {
            "response_modalities": [types.Modality.AUDIO],
            "output_audio_transcription": types.AudioTranscriptionConfig(),
            "input_audio_transcription": types.AudioTranscriptionConfig(),
            "system_instruction": system_prompt,
            "realtime_input_config": types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    prefix_padding_ms=50,
                    silence_duration_ms=300,
                ),
            ),
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon",
                    )
                )
            ),
        }
        if voice_tools:
            live_kwargs["tools"] = voice_tools
        if getattr(self, "_resumption_handle", None):
            live_kwargs["session_resumption"] = types.SessionResumptionConfig(
                handle=self._resumption_handle
            )
        # Only send fields that are explicitly set. The Live API rejects
        # unknown / null config fields as INVALID_ARGUMENT (1007), so we
        # build a minimal payload instead of dumping the whole dataclass.
        _SUPPORTED_LIVE_CONFIG_KEYS = {
            "response_modalities",
            "generation_config",
            "temperature",
            "top_p",
            "top_k",
            "max_output_tokens",
            "media_resolution",
            "seed",
            "speech_config",
            "system_instruction",
            "tools",
            "realtime_input_config",
            "input_audio_transcription",
            "output_audio_transcription",
            "session_resumption",
            "enable_affective_dialog",
            "thinking_config",
        }
        live_kwargs = {
            key: value
            for key, value in live_kwargs.items()
            if key in _SUPPORTED_LIVE_CONFIG_KEYS and value is not None
        }
        cfg = types.LiveConnectConfig(**live_kwargs)
        return cfg

    def _build_system_prompt(self) -> str:
        """Build VYREN's system prompt with all context, under a hard cap."""
        budget = {
            "memory_v2_chars": 1200,
            "memory_chars": 800,
            "world_model_chars": 800,
            "kg_chars": 800,
            "base_chars": 2400,
        }
        base = self._ctx.get("system_prompt", "You are VYREN, a voice-first AI assistant.")
        parts = [self._IDENTITY_BLOCK[: int(budget["base_chars"] * 0.6)], base]

        parts.append(
            "Rules:\n"
            "- Remember standing preferences with remember(); do not rely on\n"
            "  verbal acknowledgment alone. Reuse stable keys.\n"
            "- Honor tool status tags: SUCCESS/FAILED/PARTIAL. Never claim\n"
            "  success if a tool failed or only partially completed.\n"
            "- If you do not know something, say so plainly."
        )
        parts.append(
            "Voice Conversation Rules (this session is SPOKEN — pacing matters "
            "more than in text):\n"
            "- Keep replies to 1-2 sentences unless the user asked for detail "
            "or you're reporting data they requested.\n"
            "- Don't narrate what you're about to do (\"Let me check that for "
            "you...\") — just call the tool, then report the result briefly.\n"
            "- Never repeat yourself. Say a thing once and stop talking.\n"
            "- Don't ask a clarifying question unless truly necessary — make "
            "the reasonable assumption and proceed.\n"
            "- After a tool call resolves, give the result in one short "
            "sentence, not a recap of what you did."
        )
        parts.append("Current date and time: " + datetime.now().strftime("%A, %B %d, %Y — %I:%M %p"))

        memory = self._ctx.get("memory")
        if memory and hasattr(memory, "build_context"):
            try:
                ctx = memory.build_context()
            except Exception:
                ctx = ""
            if ctx:
                trimmed = self._trim_to_budget(ctx, budget["memory_chars"])
                parts.append("Memory Context\n" + trimmed)

        memory_v2 = self._ctx.get("memory_v2")
        if memory_v2 is not None:
            trimmed = ""
            try:
                if hasattr(memory_v2, "assemble_context"):
                    trimmed = memory_v2.assemble_context(max_chars=budget["memory_v2_chars"])
                elif hasattr(memory_v2, "build_context"):
                    trimmed = memory_v2.build_context(max_tokens=300)
                    trimmed = self._trim_to_budget(trimmed, budget["memory_v2_chars"])
            except Exception:
                trimmed = ""
            if trimmed:
                parts.append(trimmed)

        world_model = self._ctx.get("world_model")
        if world_model is not None:
            trimmed = ""
            try:
                ctx = world_model.to_context_string()
                trimmed = self._trim_to_budget(ctx, budget["world_model_chars"])
            except Exception:
                trimmed = ""
            if trimmed:
                parts.append("Your Model of the User's World\n" + trimmed)

        kg = self._ctx.get("knowledge_graph")
        if kg is not None:
            trimmed = ""
            try:
                ctx = kg.to_context_string()
                trimmed = self._trim_to_budget(ctx, budget["kg_chars"])
            except Exception:
                trimmed = ""
            if trimmed:
                parts.append(trimmed)

        full = "\n\n".join(parts)
        return self._trim_to_budget(full, 5000)

    @staticmethod
    def _trim_to_budget(text: str, max_chars: int) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        marker = "\n...[truncated]...\n"
        marker_len = len(marker)
        head_limit = max(0, max_chars - marker_len)
        if head_limit <= 0:
            return marker[:max_chars]
        head = text[: int(head_limit * 0.8)]
        tail = text[-int(head_limit * 0.2):]
        candidate = head + marker + tail
        if len(candidate) <= max_chars:
            return candidate
        return candidate[:max_chars]

    # ------------------------------------------------------------------
    # Assistant Callbacks — VYREN's brain plugged into the engine
    # ------------------------------------------------------------------

    async def _on_tool_call(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Handle tool calls from the voice model using VYREN's ToolRegistry."""
        audit = self._ctx.get("audit")
        registry = self._ctx.get("registry")
        event_bus = self._ctx.get("event_bus")

        results = []
        for tc in tool_calls:
            name = tc.name
            args = tc.args

            if audit:
                audit.tool_call(name, args, "(voice)")

            try:
                self._notify_state("thinking")
            except Exception:
                pass

            try:
                broadcast = self._ctx.get("ws_broadcast")
                if broadcast:
                    broadcast({
                        "type": "tool_call",
                        "name": name,
                        "args": args,
                        "status": "started",
                    })
            except Exception:
                pass

            if registry:
                try:
                    result = await asyncio.to_thread(registry.execute, name, args)
                except Exception as e:
                    result = f"Error: {e}"
                    logger.error("Voice tool error: %s -> %s", name, e)
            else:
                result = "Error: no tool registry"

            try:
                broadcast = self._ctx.get("ws_broadcast")
                if broadcast:
                    broadcast({
                        "type": "tool_result",
                        "name": name,
                        "result": str(result)[:300],
                        "status": "done",
                    })
            except Exception:
                pass

            if audit:
                audit.tool_call(name, args, str(result)[:100])

            if event_bus:
                try:
                    from event_bus import Event
                    event_bus.publish_sync(Event(
                        type="vyren.tool_called",
                        source="voice",
                        data={"tool": name, "args": args, "result_preview": str(result)[:100]},
                    ))
                except Exception:
                    pass

            results.append(ToolResult(id=tc.id, name=name, result=str(result)))

        return results

    def _on_turn_complete(self, turn: TurnTranscription):
        """Handle completed voice turn — audit, memory, shared history."""
        audit = self._ctx.get("audit")
        if audit:
            if turn.user_text:
                audit.model_turn("user", turn.user_text)
            if turn.model_text:
                audit.model_turn("model", turn.model_text)

        if turn.user_text or turn.model_text:
            self._record_turn(turn.user_text, turn.model_text)

        if turn.model_text:
            try:
                self._last_reply = turn.model_text
            except Exception:
                pass
            try:
                self._reply_event.set()
            except Exception:
                pass

        try:
            ctrl = self._ctx.get("interaction_controller")
            if ctrl is not None:
                ctrl.on_speak_done()
        except Exception:
            pass

        logger.info("Voice turn complete — User: '%s' | VYREN: '%s'",
                     turn.user_text[:60], turn.model_text[:60])

        broadcast = self._ctx.get("ws_broadcast")
        if broadcast:
            if turn.user_text:
                broadcast({"type": "user_transcript", "text": turn.user_text})
            if turn.model_text:
                broadcast({"type": "chunk", "text": turn.model_text})
            broadcast({"type": "done"})

    def _record_turn(self, user_text: str, model_text: str):
        """Append a turn to the shared rolling history (both online and
        offline paths call this) so switching modes mid-conversation
        doesn't lose recent context.
        """
        if user_text:
            self.recent_turns.append({"role": "user", "parts": [{"text": user_text}]})
        if model_text:
            self.recent_turns.append({"role": "model", "parts": [{"text": model_text}]})
        if len(self.recent_turns) > self._max_recent_turns:
            self.recent_turns = self.recent_turns[-self._max_recent_turns:]

    def _on_engine_state_change(self, state: VoiceState):
        """Forward engine state to VYREN's state system.

        Also counts meaningful Gemini connectivity failures for the
        connectivity-driven offline transition:
          - RECONNECTING = one failed session attempt
          - LISTENING    = successful communication, reset counter
          - FAILED       = engine exhausted its own retries, treat as
                           one additional meaningful failure and switch
                           to offline if threshold is breached
        """
        self._notify_state(state.value)
        threshold = int(getattr(self, "_voice_failure_threshold", 3) or 3)

        if state == VoiceState.RECONNECTING:
            self._voice_failure_count += 1
            logger.warning(
                "[CONNECTIVITY] Gemini Live failure %d/%d",
                self._voice_failure_count,
                threshold,
            )
            if self._voice_failure_count >= threshold:
                logger.warning(
                    "[CONNECTIVITY] Switching to OFFLINE mode after %d failures",
                    self._voice_failure_count,
                )
                self._start_fallback(reason="connectivity_failures")

        elif state == VoiceState.LISTENING:
            if getattr(self, "_voice_failure_count", 0):
                logger.info(
                    "[CONNECTIVITY] Gemini Live recovered — failure counter reset"
                )
            self._voice_failure_count = 0

        elif state == VoiceState.FAILED and self._active and not self._fallback_mode:
            # Engine gave up on its own; count this as a failure too, but
            # avoid double-switching if RECONNECTING already crossed the
            # threshold and started fallback.
            if not getattr(self, "_fallback_started_by_threshold", False):
                self._voice_failure_count += 1
                logger.warning(
                    "[CONNECTIVITY] Gemini Live failure %d/%d (engine gave up)",
                    self._voice_failure_count,
                    threshold,
                )
                if self._voice_failure_count >= threshold:
                    logger.warning(
                        "[CONNECTIVITY] Switching to OFFLINE mode after %d failures",
                        self._voice_failure_count,
                    )
                    self._start_fallback(reason="connectivity_failures")

    def _on_transcription(self, user_text: str, model_text: str):
        """Forward transcriptions for display/logging."""
        if user_text:
            logger.debug("Voice STT: %s", user_text[:100])
        if model_text:
            logger.debug("Voice TTS: %s", model_text[:100])

    def _on_connected(self):
        logger.info("Voice: Connected to Gemini Live Audio")
        self._notify_state("listening")

    def _on_error(self, error: str):
        logger.error("Voice engine error: %s", error)

    # ------------------------------------------------------------------
    # Connectivity failure accounting
    # ------------------------------------------------------------------

    def record_connectivity_failure(self, error: str = "") -> None:
        """Record a meaningful Gemini connectivity failure.

        Only meaningful failures should call this: network errors,
        session failures, and similar connectivity issues. Ordinary
        conversation turns or non-connectivity errors should not.
        """
        threshold = int(getattr(self, "_voice_failure_threshold", 3) or 3)
        self._voice_failure_count += 1
        logger.warning(
            "[CONNECTIVITY] Gemini Live failure %d/%d%s",
            self._voice_failure_count,
            threshold,
            (f" — {error}" if error else ""),
        )
        if self._voice_failure_count >= threshold:
            logger.warning(
                "[CONNECTIVITY] Switching to OFFLINE mode after %d failures",
                self._voice_failure_count,
            )
            self._start_fallback(reason="connectivity_failures")

    def record_connectivity_success(self) -> None:
        """Reset the connectivity failure counter on a successful Gemini turn."""
        if getattr(self, "_voice_failure_count", 0):
            logger.info(
                "[CONNECTIVITY] Gemini Live recovered — failure counter reset"
            )
        self._voice_failure_count = 0

    # ------------------------------------------------------------------
    # Recovery hooks for the shared VoiceSupervisor
    # ------------------------------------------------------------------

    def _request_reconnect(self) -> None:
        if self._engine:
            try:
                self._engine.set_state(VoiceState.RECONNECTING)
            except Exception:
                pass

    def _reset_audio_queues(self) -> None:
        if not self._engine:
            return
        for attr in ("_mic_queue", "_speaker_queue"):
            try:
                q = getattr(self._engine, attr, None)
                if q is not None:
                    while True:
                        try:
                            q.get_nowait()
                        except Exception:
                            break
            except Exception:
                pass

    def _restart_mic_worker(self) -> None:
        self._reset_audio_queues()
        self._request_reconnect()

    def _restart_speaker_worker(self) -> None:
        self._reset_audio_queues()
        self._request_reconnect()

    # ------------------------------------------------------------------
    # Fallback (no GEMINI_API_KEY or offline) — local STT/TTS
    # ------------------------------------------------------------------

    def _start_fallback(self, reason: str = "no_api_key"):
        """Start fallback voice mode — a real offline conversation loop
        (local STT + reasoning's existing Ollama fallback + local TTS),
        not just idle waiting. Auto-recovers to Gemini Live once a key
        and internet are both available again.
        """
        if getattr(self, "_fallback_mode", False):
            return
        self._active = True
        self._fallback_mode = True
        self._fallback_reason = reason
        logger.info(f"Voice: Fallback mode starting ({reason}) — local STT/reasoning/TTS")

        # Notify state immediately, even if the loop below can't fully
        # start. This is what unblocks InteractionController out of its
        # default "silent" mode (see runtime/manager.py
        # _on_voice_state_for_greeting) — previously this call only fired
        # from inside _fallback_main(), which never started when
        # sounddevice was missing, leaving the assistant permanently
        # gated behind "conversation mode or wake word" with no voice
        # and no working text fallback.
        self._notify_state("fallback")

        if not self._has_sounddevice():
            logger.error("Voice: Offline fallback unavailable because sounddevice is not installed")
            return

        from voice.offline_loop import OfflineVoiceLoop
        self._offline_loop = OfflineVoiceLoop(
            self._ctx,
            get_history=lambda: self.recent_turns,
            on_turn=self._record_turn,
        )
        self._offline_loop.start()

        self._fallback_thread = threading.Thread(
            target=self._fallback_main,
            name="vyren-fallback-voice",
            daemon=True,
        )
        self._fallback_thread.start()

    def _fallback_main(self):
        """Supervises fallback mode: keeps the offline loop alive and
        periodically checks whether we can recover to Gemini Live.
        """
        logger.info("Fallback voice: offline conversation loop active.")
        self._notify_state("fallback")

        last_check = 0.0
        recovered_ok = False

        while self._active and not self._stop_event.is_set():
            now = time.time()

            if now - last_check >= self._voice_recovery_check_interval_s:
                last_check = now
                if self._can_recover_to_live() and _genai_live_available():
                    recovered_ok = True
                    logger.info("Voice: Internet detected. Transitioning to Gemini Live.")
                    self._fallback_mode = False
                    if self._offline_loop:
                        self._offline_loop.stop()
                        self._offline_loop = None
                    api_key = os.environ.get("GEMINI_API_KEY")
                    if api_key:
                        self._start_gemini_live(api_key)
                    return

            self._stop_event.wait(timeout=5.0)

        if self._offline_loop:
            self._offline_loop.stop()
            self._offline_loop = None
        if not recovered_ok:
            logger.info("Fallback voice: stopped without recovery.")

    def _can_recover_to_live(self) -> bool:
        """Check if we can switch back to Gemini Live."""
        import socket

        if not os.environ.get("GEMINI_API_KEY"):
            return False

        try:
            socket.setdefaulttimeout(2.0)
            socket.create_connection(("8.8.8.8", 53), timeout=2.0)
            return True
        except OSError:
            return False

    def _speak_fallback(self, text: str):
        """Speak using fallback TTS (pyttsx3)."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 175)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            logger.error("Fallback TTS error: %s", e)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _has_sounddevice() -> bool:
        try:
            from voice.offline_loop import _sd
            return _sd is not None
        except Exception:
            return False