"""
voice_engine/engine.py -- The core Gemini Live Native Audio voice engine.

This is a production-grade, supervisor-pattern voice engine with:

1. PROPER FINITE STATE MACHINE
   - Every state transition is validated against VALID_TRANSITIONS.
   - Illegal transitions are logged and rejected.
   - The UI never claims "Listening" unless mic frames are actually flowing.

2. INDEPENDENT WORKER SUPERVISION
   - Four workers: mic, sender, receiver, speaker.
   - Each worker runs in its own asyncio task.
   - The supervisor monitors each worker's heartbeat.
   - If a worker dies, only THAT worker is restarted.
   - Conversation state and websocket are preserved.

3. MIC NEVER CLOSES
   - The mic stream stays open for the entire session lifetime.
   - Barge-in = dropping audio when _is_speaking is True (no silence injection).
   - Gemini SDK handles WebSocket keepalive via its own pings.
   - If the mic stream dies, the supervisor detects it (via heartbeat)
     and restarts ONLY the mic worker. The Gemini session survives.

4. SPEAKER NEVER CLOSES
   - The speaker stream stays open for the entire session lifetime.
   - Same supervision pattern as mic.

5. RECONNECTION
   - The outer reconnect loop handles Gemini session drops.
   - On reconnect, build_config_callback provides fresh config (NOVA pattern).
   - session_resumption means Gemini remembers context.
   - The mic and speaker streams are NOT torn down during reconnect.

6. NO SPURIOUS STATE CHANGES
   - _is_speaking is set ONLY when audio actually arrives at the speaker.
   - _is_speaking is cleared ONLY by turn_complete or speech_end_timeout.
   - The mic callback reads _is_speaking atomically (no lock — CPython GIL
     makes bool reads atomic, ~16 calls/sec hot path stays lock-free).

v2.4 changes (audio quality):
   - tools=None for ALL voice sessions (voice-first: conversation-only)
   - 1007 config errors are FATAL — engine stops retrying
   - Mic callback: _safe_enqueue wrapper catches QueueFull INSIDE the
     event loop thread (was unhandled → spam in console)
   - Mic queue: 20 → 50 (absorb sender hiccups without drops)
   - Speaker queue: 30 → 200 (absorb Gemini bursty output)
   - Speaker bridge queue: 30 → 200 (same reason)
   - Speaker blocksize: chunk_size*4 → 4800 (200ms at 24kHz, smoother)
   - False MIC DEAD fixed: init_session() sets heartbeat to NOW
   - Mic heartbeat timeout: 5s → 10s (less aggressive)
"""

import asyncio
import logging
import threading
import time
from typing import Any

try:
    import numpy as _np
except Exception:  # pragma: no cover - optional dependency absent
    _np = None  # type: ignore[assignment]

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - optional dependency absent
    class _FakeGenai:
        pass
    class _FakeTypes:
        pass
    genai = _FakeGenai()  # type: ignore
    types = _FakeTypes()  # type: ignore

from voice_engine.protocol import (
    AssistantCallbacks, ToolCall, ToolResult,
    TurnTranscription, VoiceEngineConfig, VoiceState,
    VALID_TRANSITIONS,
)
from voice_engine import diagnostics as diag

logger = logging.getLogger("vyren.voice.engine")

# Sentinel pushed into the playback bridge queue to mean "an interruption
# happened — drop everything queued and hard-stop the hardware buffer now."
# Distinct from `None`, which means "shut the playback thread down".
_FLUSH = object()


def _rms_from_int16_bytes(data: bytes) -> int:
    if _np is not None:
        samples = _np.frombuffer(data, dtype=_np.int16).astype(_np.float64)
        return int(_np.sqrt(_np.mean(_np.square(samples)))) if samples.size else 0
    samples = memoryview(data).cast("h")
    if not samples:
        return 0
    total = 0
    for sample in samples:
        total += sample * sample
    mean = total / len(samples)
    return int(mean ** 0.5)


class GeminiLiveVoiceEngine:
    """
    Production-quality Gemini Live Native Audio voice engine.

    Architecture:
        Supervisor (async loop)
          ├── Mic Worker (asyncio task + sounddevice InputStream callback)
          ├── Sender Worker (asyncio task)
          ├── Receiver Worker (asyncio task)
          ├── Speaker Worker (asyncio task + sounddevice OutputStream)
          └── State Machine (guarded transitions)
    """

    def __init__(self, config: VoiceEngineConfig, callbacks: AssistantCallbacks):
        self._config = config
        self._callbacks = callbacks
        self._session = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # Audio queues
        self._mic_queue: asyncio.Queue | None = None
        self._speaker_queue: asyncio.Queue | None = None
        self._play_q: Any = None  # threading.Queue, set by _worker_speaker

        # Local (client-side) end-of-speech guess, used only to flip the UI
        # to THINKING immediately — a perceptual trick so the person sees a
        # reaction the instant they stop talking, instead of a frozen
        # "LISTENING" state until Gemini's own turn_complete arrives.
        self._local_talk_streak = 0
        self._local_silence_streak = 0
        self._barge_in_streak = 0

        # Speaking state — accessed from mic callback (sounddevice thread)
        # and from async tasks. CPython GIL makes bool reads atomic, so
        # no lock needed on the read side (mic callback hot path, ~16/sec).
        # Writes happen from the receiver task (single writer).
        self._is_speaking = False
        self._last_speak_end = 0.0  # For echo suppression (NOVA pattern)

        # Session resumption handle, captured from Gemini's periodic
        # `session_resumption_update` messages. Passed back into
        # SessionResumptionConfig on the NEXT connect so a reconnect
        # actually resumes prior context instead of starting fresh.
        self._resumption_handle: str | None = None
        self._go_away_pending: bool = False
        # Set when the speaker has actually finished rendering everything
        # queued (not when Gemini's turn_complete arrives — those are
        # different moments, sometimes seconds apart, because turn_complete
        # fires the instant Gemini finishes GENERATING, while _play_q can
        # still hold several seconds of audio the speaker hasn't played
        # yet). Mic reactivation waits on this, not on turn_complete.
        self._playback_drained = threading.Event()
        self._playback_drained.set()  # nothing queued yet

        # State machine
        self._state = VoiceState.BOOTING
        self._state_lock = threading.Lock()

        # Lifecycle
        self._active = False
        self._stop_event = threading.Event()

        # Worker supervision — each worker has a task ref and a "last heartbeat"
        # timestamp. The supervisor checks these periodically.
        self._workers: dict[str, dict] = {}
        self._supervisor_interval = 2.0  # seconds between health checks

        # Reconnect state
        self._reconnect_delay = config.reconnect_delay
        self._reconnect_attempt = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> VoiceState:
        with self._state_lock:
            return self._state

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    @property
    def is_active(self) -> bool:
        return self._active

    def set_state(self, new_state: VoiceState):
        """Transition the FSM. Logs and rejects illegal transitions."""
        with self._state_lock:
            old = self._state
            if old == new_state:
                return  # No-op, not logged

            # Validate transition
            allowed = VALID_TRANSITIONS.get(old, set())
            if new_state not in allowed:
                # Allow transitions to FAILED and RECONNECTING from any state
                if new_state not in (VoiceState.FAILED, VoiceState.RECONNECTING):
                    diag.log_illegal_transition(old.value, new_state.value)
                    return  # Reject

            self._state = new_state

        # Notify callback (outside lock)
        if self._callbacks.on_state_change:
            try:
                self._callbacks.on_state_change(new_state)
            except Exception:
                pass

    def send_text(self, text: str):
        """Send text input into the active voice session (from UI, etc.)."""
        if not self._session or not self._loop:
            return
        text = text.strip()
        if not text:
            return

        async def _do():
            try:
                await self._session.send_client_content(
                    turns={"parts": [{"text": text}]},
                    turn_complete=True,
                )
                diag.log_transcription_user(text)
            except Exception as e:
                diag.log_error("send_text", e)

        if self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_do(), self._loop)

    def speak_text(self, text: str):
        """Send text that the model should speak aloud."""
        self.send_text(text)

    def interrupt(self):
        """Request an immediate barge-in / playback cutoff.

        This flushes queued playback and transitions the engine back
        to listening so the user can speak again. It is intentionally
        lightweight: Gemini's own server-side VAD/interrupted signal
        remains the source of truth for whether the user actually
        interrupted; this method only improves perceived latency when
        the assistant should stop talking immediately.
        """
        try:
            self._flush_playback()
        except Exception:
            pass
        self._is_speaking = False
        try:
            self.set_state(VoiceState.LISTENING)
        except Exception:
            pass

    def stop(self):
        """Request the engine to stop."""
        self._active = False
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_async(self):
        """Run the voice engine. Reconnects automatically."""
        self._active = True
        diag.reset_counters()
        self.set_state(VoiceState.BOOTING)

        client = genai.Client(
            api_key=self._config.api_key,
            http_options={"api_version": "v1beta"},
        )

        while self._active and not self._stop_event.is_set():
            self._reconnect_attempt += 1
            try:
                await self._run_session(client)
            except Exception as e:
                if not self._active or self._stop_event.is_set():
                    break

                error_str = str(e)

                # FATAL CONFIG ERRORS — do NOT retry these.
                # 1007 with "Invalid function name", "tool", or "setup" means
                # the LiveConnectConfig itself is broken. Retrying with the
                # same config will produce the same error forever.
                if "1007" in error_str and any(
                    keyword in error_str.lower()
                    for keyword in ("invalid function name", "tool", "setup.", "must start with a letter")
                ):
                    logger.critical(
                        "[FATAL] Config error (1007) — will NOT retry: %s",
                        error_str[:200],
                    )
                    diag.log_error("Session", e)
                    diag.log_disconnected(error_str)
                    break

                diag.log_error("Session", e)
                diag.log_disconnected(error_str)

            # Clean up workers
            self._cancel_all_workers()
            self._is_speaking = False

            if not self._active or self._stop_event.is_set():
                break

            self.set_state(VoiceState.RECONNECTING)

            # Give up after too many consecutive failures — this is what
            # tells VoiceRuntime "stop retrying, switch to the offline
            # loop" (via the FAILED state callback). Without this, a real
            # outage just retries forever at the 60s-capped backoff with
            # no signal to the rest of the system.
            if self._reconnect_attempt >= self._config.max_consecutive_reconnect_failures:
                logger.warning(
                    "[RECONNECT] %d consecutive failures — giving up on Gemini Live "
                    "for now (will not retry further this session).",
                    self._reconnect_attempt,
                )
                break

            # Exponential backoff with cap
            delay = min(self._reconnect_delay * (1.5 ** (self._reconnect_attempt - 1)),
                        self._config.max_reconnect_delay)
            diag.log_reconnecting(delay)
            await asyncio.sleep(delay)

        self.set_state(VoiceState.FAILED)

    def run(self):
        """Blocking entry point. Run in a thread if needed."""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            pass
        finally:
            self._active = False
            self.set_state(VoiceState.FAILED)

    # ------------------------------------------------------------------
    # Single session
    # ------------------------------------------------------------------

    def _build_session_config(self) -> types.LiveConnectConfig:
        """Build the LiveConnectConfig for a Gemini Live session.

        Priority:
          1. build_config_callback (NOVA's _build_config pattern — fresh
             config on every connect/reconnect with current memory/time)
          2. Built-in config using self._config fields

        Config matches NOVA's proven pattern exactly:
          - response_modalities=[types.Modality.AUDIO] (enum, not string)
          - system_instruction=plain_string
          - AudioTranscriptionConfig() (not empty dict)
          - tools from registry (raw dicts, not types.FunctionDeclaration)
        """
        # If the assistant provided a dynamic config builder, use it
        if self._config.build_config_callback:
            try:
                callback_config = self._config.build_config_callback()
                if callback_config is not None:
                    return callback_config
            except Exception as e:
                logger.warning("build_config_callback failed, using built-in config: %s", e)

        # Built-in config — matches NOVA's _build_config() exactly
        # NOTE: No tools for voice sessions (voice-first architecture)
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=self._config.system_prompt,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self._config.voice_name,
                    )
                )
            ),
            # Turn-taking tuning — this is the fix for "waiting for a
            # chatbot": without it, Gemini uses conservative defaults for
            # both how fast it notices you started talking and how long it
            # waits through silence before deciding you're done.
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=(
                        types.StartSensitivity.START_SENSITIVITY_HIGH
                        if self._config.vad_start_sensitivity == "high"
                        else types.StartSensitivity.START_SENSITIVITY_LOW
                    ),
                    end_of_speech_sensitivity=(
                        types.EndSensitivity.END_SENSITIVITY_HIGH
                        if self._config.vad_end_sensitivity == "high"
                        else types.EndSensitivity.END_SENSITIVITY_LOW
                    ),
                    prefix_padding_ms=self._config.vad_prefix_padding_ms,
                    silence_duration_ms=self._config.vad_silence_duration_ms,
                ),
            ),
            thinking_config=types.ThinkingConfig(
                thinking_level=self._config.thinking_level,
            ),
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=self._config.context_compression_trigger_tokens,
                sliding_window=types.SlidingWindow(
                    target_tokens=self._config.context_compression_target_tokens,
                ),
            ),
            session_resumption=(
                types.SessionResumptionConfig(handle=self._resumption_handle)
                if self._config.session_resumption else None
            ),
            tools=None,
        )

    async def _run_session(self, client: genai.Client):
        """Run one Gemini Live Audio session with supervised workers."""
        self.set_state(VoiceState.IDLE)
        diag.log_connecting(self._reconnect_attempt)

        # Build config (uses build_config_callback if available)
        config = self._build_session_config()

        config = self._build_session_config()

        # Log tool info for diagnostics (helps catch 1007 errors)
        tool_count = 0
        if config.tools:
            for t in config.tools:
                if hasattr(t, "function_declarations"):
                    tool_count += len(t.function_declarations)
                elif isinstance(t, dict) and "function_declarations" in t:
                    tool_count += len(t["function_declarations"])
        logger.info("Connecting with %d tools, model=%s", tool_count, self._config.model)
        self._mic_queue = asyncio.Queue(maxsize=self._config.mic_queue_maxsize)
        self._speaker_queue = asyncio.Queue(maxsize=self._config.speaker_queue_maxsize)

        # Initialize mic heartbeat to NOW so the first supervisor check
        # doesn't trigger a false "MIC DEAD" (was 0.0 → instant false positive)
        diag.init_session()

        async with client.aio.live.connect(
            model=self._config.model, config=config,
        ) as session:
            self._session = session
            self._loop = asyncio.get_event_loop()
            self._go_away_pending = False

            diag.log_connected()
            if self._reconnect_attempt > 0:
                diag.log_reconnect_success()
            self._reconnect_attempt = 0  # Reset on successful connect

            self.set_state(VoiceState.LISTENING)

            if self._callbacks.on_connected:
                try:
                    self._callbacks.on_connected()
                except Exception:
                    pass

            # Start four INDEPENDENT workers (NOT in a TaskGroup)
            # Each worker is supervised individually.
            self._start_worker("mic", self._worker_mic)
            self._start_worker("sender", self._worker_sender)
            self._start_worker("receiver", self._worker_receiver)
            self._start_worker("speaker", self._worker_speaker)

            # Supervisor loop — runs until session ends or stop requested
            await self._supervisor_loop()

            # Session ending — cancel remaining workers
            self._cancel_all_workers()

        self._session = None

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    def _start_worker(self, name: str, coro_fn, restart_count: int = 0):
        """Start a supervised worker task."""
        task = asyncio.create_task(coro_fn(), name=f"voice-{name}")
        self._workers[name] = {
            "task": task,
            "started": time.monotonic(),
            "last_heartbeat": time.monotonic(),
            "restarts": restart_count,
            "failed": False,
        }

    def _cancel_worker(self, name: str):
        """Cancel a single worker task and drain its exception state."""
        info = self._workers.get(name)
        if not info:
            return
        task = info["task"]
        if not task.done():
            task.cancel()
        # Always try to retrieve the result/exception so it doesn't
        # surface later as an unretrieved task exception.
        try:
            if task.done() and not task.cancelled():
                task.result(timeout=2.0)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        info["failed"] = True

    async def _restart_worker(self, name: str):
        """Restart a single failed worker. Preserves everything else."""
        coro_map = {
            "mic": self._worker_mic,
            "sender": self._worker_sender,
            "receiver": self._worker_receiver,
            "speaker": self._worker_speaker,
        }
        coro_fn = coro_map.get(name)
        if not coro_fn:
            return False

        info = self._workers.get(name, {})
        new_count = info.get("restarts", 0) + 1

        max_worker_restarts = 5
        if new_count > max_worker_restarts:
            logger.error(
                "[SUPERVISOR] Worker '%s' exceeded %d restarts — will NOT restart again",
                name, max_worker_restarts,
            )
            return False

        backoff = min(0.1 * (2 ** (new_count - 1)), 3.2)
        logger.warning(
            "[SUPERVISOR] Restarting worker '%s' (restart #%d, backoff %.2fs)",
            name, new_count, backoff,
        )

        self._cancel_worker(name)
        await asyncio.sleep(backoff)
        self._start_worker(name, coro_fn, restart_count=new_count)
        logger.info("[SUPERVISOR] Worker '%s' restarted (now at restart #%d)", name, new_count)
        return True

    def _cancel_all_workers(self):
        """Cancel all worker tasks."""
        for name in list(self._workers.keys()):
            self._cancel_worker(name)

    # ------------------------------------------------------------------
    # Supervisor
    # ------------------------------------------------------------------

    async def _supervisor_loop(self):
        """
        Monitor all workers. Restart any that die (with limits).
        Detect mic death (no frames for N seconds).
        """
        max_worker_restarts = 5

        while self._active and not self._stop_event.is_set():
            await asyncio.sleep(self._supervisor_interval)

            # GoAway already told us the server is closing this session.
            # Exit the `async with client.aio.live.connect(...)` block on
            # our own terms now, while the socket is still alive, instead
            # of waiting for the server to force-close it — that force
            # close is what produces the 1008 policy-violation errors.
            # The outer reconnect loop resumes via self._resumption_handle.
            if self._go_away_pending:
                logger.info(
                    "[SUPERVISOR] GoAway pending — closing session proactively "
                    "for clean reconnect (resumption_handle=%s)",
                    "present" if self._resumption_handle else "none",
                )
                diag.log_disconnected("go_away: proactive close")
                return

            # Check each worker
            for name, info in list(self._workers.items()):
                task = info["task"]

                if info.get("failed"):
                    continue

                if task.done():
                    exc = task.exception()
                    if exc and not isinstance(exc, asyncio.CancelledError):
                        exc_str = str(exc).lower()

                        # SESSION-LEVEL FAILURES: WebSocket is dead.
                        # Restarting sender/receiver on a dead session is futile.
                        # The entire session must be torn down and reconnected.
                        is_session_death = (
                            "1011" in exc_str          # keepalive ping timeout
                            or "1006" in exc_str       # abnormal closure
                            or "1007" in exc_str       # protocol error (bad config)
                            or "1008" in exc_str       # policy violation — GoAway close, not a worker bug
                            or "connection closed" in exc_str
                            or "websocket" in exc_str
                        )

                        if is_session_death and name in ("sender", "receiver"):
                            logger.error(
                                "[SUPERVISOR] Session-level failure on '%s': %s — "
                                "ending session for clean reconnect",
                                name, exc,
                            )
                            diag.log_disconnected(f"session death: {exc}")
                            return  # Break to outer reconnect loop

                        logger.error("[SUPERVISOR] Worker '%s' crashed: %s", name, exc)
                        diag.log_error(f"worker_{name}", exc)

                        if info["restarts"] >= max_worker_restarts:
                            logger.error(
                                "[SUPERVISOR] Worker '%s' exceeded %d restarts, ending session",
                                name, max_worker_restarts,
                            )
                            return

                        success = await self._restart_worker(name)
                        if not success:
                            return
                    elif isinstance(exc, asyncio.CancelledError):
                        info["failed"] = True

            # Mic heartbeat check
            counters = diag.get_counters()
            time_since_mic = time.monotonic() - counters.get("last_mic_frame_time", 0)
            if (time_since_mic > self._config.mic_heartbeat_timeout
                    and self.state == VoiceState.LISTENING):
                diag.log_mic_dead(time_since_mic)
                mic_info = self._workers.get("mic", {})
                if mic_info.get("restarts", 0) < max_worker_restarts:
                    success = await self._restart_worker("mic")
                    if not success:
                        return
                else:
                    logger.error("[SUPERVISOR] Mic exceeded %d restarts, ending session",
                                 max_worker_restarts)
                    return

            # Check if receiver is alive (receiver is the canary for the session)
            receiver = self._workers.get("receiver")
            if receiver and receiver["task"].done() and not receiver.get("failed"):
                exc = receiver["task"].exception()
                if exc and not isinstance(exc, asyncio.CancelledError):
                    if receiver.get("restarts", 0) >= max_worker_restarts:
                        logger.warning("[SUPERVISOR] Receiver dead and over restart limit, ending session")
                        break
                elif not exc:
                    break

    # ------------------------------------------------------------------
    # Worker: Mic capture
    #
    # CRITICAL: The mic stream stays OPEN the entire session.
    # Barge-in = dropping audio when _is_speaking is True.
    # Gemini handles VAD internally.
    # Gemini SDK handles WebSocket keepalive via its own pings.
    #
    # DROP-NOT-SILENCE (Mark's proven pattern):
    # When the model is speaking, we simply RETURN from the callback
    # without sending anything. This is better than sending zero-byte
    # silence because:
    #   1. Less CPU (no memcpy + queue.put for silence)
    #   2. Less network traffic (no WS frames for silence)
    #   3. Gemini's VAD works better with silence gaps than with
    #      continuous zero-byte frames
    # ------------------------------------------------------------------

    async def _worker_mic(self):
        """Open mic and stream audio to mic queue. Never closes until cancelled."""
        import sounddevice as sd

        loop = asyncio.get_event_loop()

        def _safe_enqueue(data):
            try:
                self._mic_queue.put_nowait(data)
                diag.log_mic_frame_sent(len(data["data"]))
            except asyncio.QueueFull:
                diag.log_mic_dropped("queue full")

        def mic_callback(indata, frames, time_info, status):
            if not self._active:
                return

            data = indata.tobytes()
            speaking = self._is_speaking

            if speaking:
                if not self._config.barge_in_enabled:
                    # Old behavior, opt-in only: mic fully muted while VYREN
                    # talks. Simple, but Gemini's VAD never sees an
                    # interruption, so barge-in cannot work at all.
                    return
                # Full-duplex: keep streaming so Gemini's server-side VAD can
                # actually detect the interruption (that's what fires
                # `server_content.interrupted`, which is what really stops
                # playback — see _worker_receiver). Gate on loudness so
                # quiet speaker bleed-through doesn't send a constant stream
                # of false "user is talking" audio on non-headphone setups.
                try:
                    rms = _rms_from_int16_bytes(data)
                except Exception:
                    rms = self._config.barge_in_rms_threshold  # fail open
                if rms < self._config.barge_in_rms_threshold:
                    self._barge_in_streak = 0
                    return
                # A single loud frame is cheap to produce from bleed/pop
                # noise; require several in a row before treating it as
                # a real interruption. This is on the local mic->send
                # gate only — it doesn't affect Gemini's own VAD, it
                # just avoids handing Gemini a burst of one frame that
                # could be a false trigger.
                self._barge_in_streak += 1
                if self._barge_in_streak < 3:
                    return
            else:
                # Resume sending immediately after the model stops speaking.
                # There is no post-speech drop window; returning to streaming
                # fast is what makes conversation feel live. If the model's
                # tail audio is still playing, Gemini's own VAD and barge-in
                # path handle it — we do not need to blind the mic here.
                pass

                # Local end-of-speech guess, purely for perceived
                # responsiveness — flips the UI to THINKING the instant the
                # person stops talking rather than waiting on the server.
                try:
                    samples = _np.frombuffer(data, dtype=_np.int16).astype(_np.float64)
                    rms = int(_np.sqrt(_np.mean(_np.square(samples)))) if samples.size else 0
                except Exception:
                    rms = 0
                if rms >= self._config.barge_in_rms_threshold:
                    self._local_talk_streak += 1
                    self._local_silence_streak = 0
                else:
                    self._local_silence_streak += 1
                    if self._local_talk_streak >= 3 and self._local_silence_streak == 4:
                        loop.call_soon_threadsafe(self._maybe_signal_thinking)
                    if self._local_silence_streak > 50:
                        self._local_talk_streak = 0

            loop.call_soon_threadsafe(
                _safe_enqueue,
                {"data": data, "mime_type": "audio/pcm"},
            )

        try:
            # Identify what device we're actually about to record from.
            # sd.InputStream() with no `device=` arg silently opens
            # whatever the OS calls its current default input — on
            # Windows that can be "Stereo Mix" / "What U Hear" / a
            # virtual loopback cable if one was ever set as default
            # (common after installing streaming/recording software).
            # That device doesn't record the room — it records whatever
            # is currently being PLAYED, i.e. VYREN's own voice, byte
            # for byte. That produces a self-conversation that's
            # completely deterministic and immune to headphones, which
            # is exactly the pattern in your logs. Refuse to proceed on
            # a device that looks like that instead of silently talking
            # to itself forever.
            try:
                dev_info = sd.query_devices(kind="input")
                dev_name = dev_info.get("name", "unknown")
            except Exception:
                dev_name = "unknown (could not query)"

            _LOOPBACK_MARKERS = (
                "stereo mix", "what u hear", "wave out", "loopback",
                "cable output", "voicemeeter",
            )
            if any(m in dev_name.lower() for m in _LOOPBACK_MARKERS):
                raise RuntimeError(
                    f"Input device '{dev_name}' looks like a system-audio "
                    f"loopback/monitor device, not a real microphone. "
                    f"Recording from it means VYREN would hear its own "
                    f"speech, not you — that's the self-conversation bug. "
                    f"Set a real microphone as your Windows default "
                    f"recording device (Settings > Sound > Input) and "
                    f"restart VYREN."
                )
            logger.info("[MIC] Recording from input device: '%s'", dev_name)

            stream = sd.InputStream(
                samplerate=self._config.send_sample_rate,
                channels=self._config.channels,
                dtype="int16",
                blocksize=self._config.chunk_size,
                callback=mic_callback,
            )
            stream.start()
            diag.log_mic_started()
            diag.mark_mic_alive()

            # Keep this task alive. Update heartbeat each iteration.
            while self._active:
                await asyncio.sleep(0.5)
                self._workers["mic"]["last_heartbeat"] = time.monotonic()

        except Exception as e:
            diag.log_error("mic", e)
            raise
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            diag.log_mic_stopped()

    def _maybe_signal_thinking(self):
        """Flip the UI to THINKING on our own local guess that speech ended.

        Purely perceptual — the real turn-taking decision still comes from
        Gemini. This just removes the "did it hear me?" dead air.
        """
        if self.state in (VoiceState.LISTENING, VoiceState.STREAMING):
            self.set_state(VoiceState.THINKING)
            diag.log_thinking()

    def _flush_playback(self):
        """Drop everything queued for playback right now (barge-in cutoff).

        Called when Gemini's `server_content.interrupted` confirms the user
        actually interrupted the model. Clears both the asyncio hand-off
        queue and, via the _FLUSH sentinel, the playback thread's buffer —
        including telling the audio device to discard whatever it already
        has buffered in hardware, so playback stops within milliseconds
        instead of draining out the remaining ~1-2s of queued audio.
        """
        if self._speaker_queue is not None:
            try:
                while True:
                    self._speaker_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        if self._play_q is not None:
            try:
                self._play_q.put_nowait(_FLUSH)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Worker: Sender (mic queue → Gemini)
    # ------------------------------------------------------------------

    async def _worker_sender(self):
        """Read from mic queue, send to Gemini."""
        while self._active:
            try:
                msg = await asyncio.wait_for(self._mic_queue.get(), timeout=0.5)
                if not self._session:
                    break
                await self._session.send_realtime_input(
                    audio=types.Blob(data=msg["data"], mime_type=msg["mime_type"])
                )
                self._workers["sender"]["last_heartbeat"] = time.monotonic()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._active:
                    break
                diag.log_error("sender", e)
                raise

    # ------------------------------------------------------------------
    # Worker: Receiver (Gemini → route to speaker queue / tools / FSM)
    #
    # This is the ONLY worker that touches the state machine for
    # speaking/thinking/tool transitions.
    # ------------------------------------------------------------------

    async def _worker_receiver(self):
        """Read Gemini responses. Route audio, tools, transcriptions."""
        in_buf: list[str] = []
        out_buf: list[str] = []

        try:
            if not self._session:
                raise RuntimeError("Receiver started but session is None — startup ordering bug")

            # NOTE ON THE OUTER while LOOP (do not remove):
            # google-genai's session.receive() is an async generator that
            # BREAKS the moment it yields a turn_complete message — see
            # live.py: `while result := await self._receive(): ... if
            # turn_complete: yield result; break`. That is documented,
            # correct SDK behavior, not a crash. Calling receive() exactly
            # once per session (the old code) meant every turn_complete
            # silently ended this task, which the supervisor then read as
            # "receiver crashed" and burned a worker restart on — repeated
            # every single turn, exhausting the restart budget and forcing
            # full session teardown far sooner than the connection itself
            # warranted. Looping receive() here keeps one long-lived task
            # per session and calls receive() again for the next turn,
            # exactly as Google's own examples do.
            while self._active:
                async for response in self._session.receive():
                    if not self._active:
                        break

                    self._workers["receiver"]["last_heartbeat"] = time.monotonic()

                    # --- GoAway: server is about to close this session
                    # (session duration limit). Ignoring this is what
                    # produces "1008 policy violation: client failed to
                    # close the connection after receiving a GoAway
                    # signal" — the server was telling us to wrap up. We
                    # can't force-close the SDK's socket from here, but we
                    # log it, and the resumption handle captured below
                    # means the reconnect that follows actually resumes
                    # this session's context instead of starting fresh.
                    if getattr(response, "go_away", None):
                        time_left = getattr(response.go_away, "time_left", None)
                        logger.warning(
                            "[SESSION] GoAway received — server closing this "
                            "session soon (time_left=%s)", time_left,
                        )
                        self._go_away_pending = True

                    # --- Session resumption handle: capture it so the
                    # NEXT connect (_build_session_config) can resume this
                    # session instead of always sending a blank
                    # SessionResumptionConfig(), which was silently
                    # discarding conversational context on every reconnect.
                    update = getattr(response, "session_resumption_update", None)
                    if update and getattr(update, "resumable", False) and getattr(update, "new_handle", None):
                        self._resumption_handle = update.new_handle

                    # --- Audio output → speaker queue ---
                    if response.data:
                        try:
                            self._speaker_queue.put_nowait(response.data)
                            diag.log_speaker_frame(len(response.data))
                        except asyncio.QueueFull:
                            logger.warning("[AUDIO] Speaker queue full, dropping chunk")

                        # Mark speaking (idempotent) — no lock needed (single writer)
                        if not self._is_speaking:
                            self._is_speaking = True
                            self.set_state(VoiceState.SPEAKING)
                            diag.log_speech_started()

                    # --- Server content ---
                    if response.server_content:
                        sc = response.server_content

                        # The user actually interrupted (server-confirmed via
                        # VAD on the full-duplex mic stream). Cut playback NOW —
                        # this is what makes barge-in feel instant instead of
                        # the model talking over/through the interruption.
                        if getattr(sc, "interrupted", False):
                            self._flush_playback()
                            self._is_speaking = False
                            self._last_speak_end = time.time()
                            self.set_state(VoiceState.LISTENING)
                            diag.log_listening()

                        # Model transcription (what VYREN is saying)
                        if sc.output_transcription and sc.output_transcription.text:
                            txt = sc.output_transcription.text.strip()
                            if txt:
                                out_buf.append(txt)
                                diag.log_transcription_model(txt)
                                if self._callbacks.on_transcription:
                                    try:
                                        self._callbacks.on_transcription("", txt)
                                    except Exception:
                                        pass

                        # User transcription (what user said)
                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                in_buf.append(txt)
                                diag.log_transcription_user(txt)
                                if self._callbacks.on_transcription:
                                    try:
                                        self._callbacks.on_transcription(txt, "")
                                    except Exception:
                                        pass

                        # Turn complete — THE key state transition
                        if sc.turn_complete:
                            full_in = " ".join(in_buf).strip()
                            full_out = " ".join(out_buf).strip()

                            diag.log_turn_complete(full_in, full_out)

                            # NOTE: mic/state reactivation happens immediately
                            # below. This helper is now a best-effort cleanup
                            # waiter only; it no longer blocks listening state
                            # or mic audio after a turn ends.
                            asyncio.ensure_future(
                                self._await_playback_drain_cleanup(),
                            )

                            # Notify assistant
                            if self._callbacks.on_turn_complete:
                                try:
                                    self._callbacks.on_turn_complete(
                                        TurnTranscription(
                                            user_text=full_in,
                                            model_text=full_out,
                                        )
                                    )
                                except Exception:
                                    pass

                            in_buf = []
                            out_buf = []

                    # --- Tool calls ---
                    if response.tool_call and response.tool_call.function_calls:
                        self.set_state(VoiceState.EXECUTING_TOOL)
                        await self._handle_tool_calls(response.tool_call.function_calls)
                # Inner `async for` ended — either turn_complete (SDK's
                # documented per-turn boundary) or `not self._active`. The
                # `while self._active` above decides whether we call
                # receive() again (next turn) or fall through to `finally`.

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not self._stop_event.is_set():
                diag.log_error("receiver", e)
                raise
        finally:
            self._is_speaking = False

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _await_playback_drain_cleanup(self):
        """
        Best-effort playback cleanup waiter.

        Runs as its own task so it never blocks the receiver's read loop.
        This no longer controls when listening resumes; listening state
        and mic audio resume independently after turn_complete.
        """
        try:
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, self._playback_drained.wait),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.debug("[AUDIO] Playback drain cleanup timed out — continuing.")

    async def _handle_tool_calls(self, function_calls):
        """Execute tool calls via the assistant callback with timeout."""
        tool_calls = [
            ToolCall(
                id=fc.id,
                name=fc.name,
                args=dict(fc.args) if fc.args else {},
            )
            for fc in function_calls
        ]

        for tc in tool_calls:
            diag.log_tool_received(tc.name, tc.args)

        try:
            results = await asyncio.wait_for(
                self._callbacks.on_tool_call(tool_calls),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            diag.log_tool_error("callback", "timeout (30s)")
            results = [
                ToolResult(id=tc.id, name=tc.name, result="Error: tool execution timed out (30s)")
                for tc in tool_calls
            ]
        except Exception as e:
            diag.log_tool_error("callback", str(e))
            results = [
                ToolResult(id=tc.id, name=tc.name, result=f"Error: {e}")
                for tc in tool_calls
            ]

        for r in results:
            diag.log_tool_result(r.name, r.result)

        # Send results back to Gemini
        try:
            fn_responses = [
                types.FunctionResponse(
                    id=r.id, name=r.name, response={"result": r.result},
                )
                for r in results
            ]
            await self._session.send_tool_response(function_responses=fn_responses)
            logger.info("[TOOL] %d tool results sent back to Gemini", len(fn_responses))

            self.set_state(VoiceState.THINKING)
            diag.log_thinking()
        except Exception as e:
            diag.log_tool_error("send_tool_response", str(e))

    # ------------------------------------------------------------------
    # Worker: Speaker (speaker queue → audio output)
    #
    # Opens the speaker stream ONCE and keeps it open.
    # Writes chunks as they arrive.
    # Does NOT manage _is_speaking — that's the receiver's job.
    # ------------------------------------------------------------------

    async def _worker_speaker(self):
        """Read from speaker queue, write to speakers. Stream stays open.

        Uses a dedicated playback thread (NOVA pattern) to avoid asyncio
        overhead per audio chunk. The async task bridges asyncio.Queue
        → threading.Queue. The playback thread writes directly to
        sounddevice with a larger blocksize for smoother audio.
        """
        import sounddevice as sd
        import queue as _q

        diag.log_playback_started()

        _play_q: _q.Queue = _q.Queue(maxsize=200)
        self._play_q = _play_q

        def _play_worker():
            stream = sd.RawOutputStream(
                samplerate=self._config.receive_sample_rate,
                channels=self._config.channels,
                dtype="int16",
                blocksize=4800,  # 200ms at 24kHz — smooth, no cracking
                latency="low",
            )
            stream.start()
            try:
                while True:
                    try:
                        chunk = _play_q.get(timeout=0.05)
                    except _q.Empty:
                        # Nothing pending and nothing in flight — playback
                        # is genuinely caught up.
                        self._playback_drained.set()
                        continue
                    if chunk is None:
                        break
                    if chunk is _FLUSH:
                        # Barge-in: drop anything else already queued, then
                        # hard-stop so buffered-in-hardware audio doesn't
                        # keep dribbling out after the interrupt.
                        try:
                            while True:
                                _play_q.get_nowait()
                        except _q.Empty:
                            pass
                        try:
                            stream.abort()
                            stream.start()
                        except Exception:
                            pass
                        self._playback_drained.set()
                        continue
                    # A real chunk is about to be written to hardware —
                    # playback is definitively NOT drained until this
                    # (and anything queued behind it) has been played.
                    self._playback_drained.clear()
                    try:
                        if isinstance(chunk, bytes):
                            stream.write(chunk)
                        elif hasattr(chunk, "data"):
                            stream.write(chunk.data)
                        else:
                            stream.write(bytes(chunk))
                    except Exception:
                        pass
                    if _play_q.empty():
                        self._playback_drained.set()
            finally:
                stream.stop()
                stream.close()
                self._playback_drained.set()

        _pt = threading.Thread(target=_play_worker, daemon=True, name="AudioPlay")
        _pt.start()

        try:
            while self._active:
                try:
                    chunk = await asyncio.wait_for(
                        self._speaker_queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    self._workers["speaker"]["last_heartbeat"] = time.monotonic()
                    continue

                self._workers["speaker"]["last_heartbeat"] = time.monotonic()
                try:
                    _play_q.put_nowait(chunk)
                except _q.Full:
                    pass  # Drop — safe, avoids blocking

        except asyncio.CancelledError:
            pass
        except Exception as e:
            diag.log_error("speaker", e)
            raise
        finally:
            # Signal playback thread to stop without blocking on a full
            # queue. If the queue is saturated, drain stale chunks first
            # so the sentinel is accepted immediately.
            try:
                while True:
                    _play_q.get_nowait()
            except _q.Empty:
                pass
            try:
                _play_q.put_nowait(None)
            except _q.Full:
                pass
            self._play_q = None
            diag.log_playback_stopped()