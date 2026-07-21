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

from google.genai import types

from voice_engine import GeminiLiveVoiceEngine, AssistantCallbacks, VoiceState
from voice_engine.protocol import ToolCall, ToolResult, TurnTranscription, VoiceEngineConfig
from voice_engine import diagnostics as diag

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
        return "vyren"

    def on_state_change(self, callback):
        self._state_callbacks.append(callback)

    def _notify_state(self, state):
        self._state = state
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
            self._start_fallback()

    def stop(self):
        self._active = False
        self._stop_event.set()
        if self._engine:
            self._engine.stop()
        if self._offline_loop:
            self._offline_loop.stop()
            self._offline_loop = None
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
        if self._engine and self._engine.is_active:
            self._engine.send_text(text)
        else:
            self._speak_fallback(text)

    def send_text(self, text: str):
        """Send text into the voice session."""
        if not text or not text.strip():
            return
        if self._engine and self._engine.is_active:
            self._engine.send_text(text.strip())

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
        # NOTE: No tools passed — voice session is conversation-only (voice-first).
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

    def _build_live_config(self) -> types.LiveConnectConfig:
        """Build a fresh LiveConnectConfig for each connect/reconnect.

        This is NOVA's _build_config() pattern. Every time the engine
        connects or reconnects to Gemini, it gets a config with:
          - Fresh system prompt (current memory, time, world model)

        VOICE-FIRST: No tools are sent to the Gemini Live session.
        Both NOVA and Mark's production pipelines do not pass function
        declarations to the audio WebSocket. Reasons:
          1. Gemini Live with 35+ tools causes 1007 config errors
             (tool name validation, parameter schema size limits)
          2. Voice sessions should be CONVERSATION-only. Tool use adds
             latency (tool execution blocks the response) and breaks the
             real-time flow (user hears silence while tool runs)
          3. If the user needs a tool, the text pipeline (provider.py)
             handles it with full function calling support
          4. Gemini's native audio model prioritizes conversation quality
             when no tools are declared — faster responses, better VAD
        """
        # Rebuild system prompt with fresh memory/time context
        system_prompt = self._build_system_prompt()

        logger.info(
            "Building LiveConnectConfig: prompt=%d chars, tools=none (voice-first)",
            len(system_prompt),
        )

        # Match NOVA's exact config structure — NO tools for voice session
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=system_prompt,
            tools=None,
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    prefix_padding_ms=50,
                    silence_duration_ms=300,
                ),
            ),
            thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=100_000,
                sliding_window=types.SlidingWindow(target_tokens=4_000),
            ),
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon",
                    )
                )
            ),
        )

    def _build_system_prompt(self) -> str:
        """Build VYREN's system prompt with all context."""
        base = self._ctx.get("system_prompt", "You are VYREN, a voice-first AI assistant.")
        parts = [base]

        # Add current time (NOVA embeds time in system prompt)
        time_str = datetime.now().strftime("%A, %B %d, %Y — %I:%M %p")
        parts.append(f"\n\nCurrent date and time: {time_str}")

        memory = self._ctx.get("memory")
        if memory and hasattr(memory, "build_context"):
            ctx = memory.build_context()
            if ctx:
                parts.append("\n\n## Memory Context\n" + ctx)

        memory_v2 = self._ctx.get("memory_v2")
        if memory_v2 and hasattr(memory_v2, "build_context"):
            try:
                v2_ctx = memory_v2.build_context(max_tokens=300)
                if v2_ctx:
                    parts.append("\n\n" + v2_ctx)
            except Exception:
                pass

        world_model = self._ctx.get("world_model")
        if world_model and hasattr(world_model, "to_context_string"):
            ctx = world_model.to_context_string()
            if ctx:
                parts.append("\n\n## Your Model of the User's World\n" + ctx)

        kg = self._ctx.get("knowledge_graph")
        if kg and hasattr(kg, "to_context_string"):
            ctx = kg.to_context_string()
            if ctx:
                parts.append("\n\n" + ctx)

        return "\n".join(parts)

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

            if registry:
                try:
                    result = await asyncio.to_thread(registry.execute, name, args)
                except Exception as e:
                    result = f"Error: {e}"
                    logger.error("Voice tool error: %s -> %s", name, e)
            else:
                result = "Error: no tool registry"

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

        logger.info("Voice turn complete — User: '%s' | VYREN: '%s'",
                     turn.user_text[:60], turn.model_text[:60])

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

        FAILED means the engine gave up reconnecting (see engine.py's
        max_consecutive_reconnect_failures) — that's the signal to stop
        banging on a dead connection and switch to the offline loop
        instead of retrying forever.
        """
        self._notify_state(state.value)
        if state == VoiceState.FAILED and self._active and not self._fallback_mode:
            logger.warning("Voice: Gemini Live gave up reconnecting — switching to offline mode")
            self._start_fallback(reason="engine_gave_up")

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
    # Fallback (no GEMINI_API_KEY or offline) — local STT/TTS
    # ------------------------------------------------------------------

    def _start_fallback(self, reason: str = "no_api_key"):
        """Start fallback voice mode — a real offline conversation loop
        (local STT + reasoning's existing Ollama fallback + local TTS),
        not just idle waiting. Auto-recovers to Gemini Live once a key
        and internet are both available again.
        """
        self._active = True
        self._fallback_mode = True
        self._fallback_reason = reason
        logger.info(f"Voice: Fallback mode starting ({reason}) — local STT/reasoning/TTS")

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

        recovery_check_interval = 30
        last_check = 0.0

        while self._active and not self._stop_event.is_set():
            now = time.time()

            if now - last_check >= recovery_check_interval:
                last_check = now
                if self._can_recover_to_live():
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
        logger.info("Fallback voice: stopped.")

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
            import sounddevice as sd
            return True
        except ImportError:
            return False