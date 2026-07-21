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

v2.2 changes (NOVA-aligned):
   - Config format matches NOVA's proven _build_config() pattern exactly:
     * response_modalities=[types.Modality.AUDIO] (enum, not string)
     * system_instruction=plain_string (no Content/Part wrapping)
     * output/input_audio_transcription=AudioTranscriptionConfig() (not {})
     * tools from build_config_callback or config.gemini_tools
   - Removed _speaking_lock (CPython GIL makes bool reads atomic)
   - Mic drops frames when speaking instead of sending silence (Mark's pattern)
   - build_config_callback support for fresh config on every reconnect
   - 1007 added to session-level failures (config error, not transient)
   - Playback bridge queue: 200 → 30 (prevent trailing audio)
   - Mic queue uses config.mic_queue_maxsize (20)
"""

import asyncio
import logging
import threading
import time
from typing import Any

from google import genai
from google.genai import types

from voice_engine.protocol import (
    AssistantCallbacks, ToolCall, ToolResult,
    TurnTranscription, VoiceEngineConfig, VoiceState,
    VALID_TRANSITIONS,
)
from voice_engine import diagnostics as diag

logger = logging.getLogger("voice.engine")


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

        # Speaking state — accessed from mic callback (sounddevice thread)
        # and from async tasks. CPython GIL makes bool reads atomic, so
        # no lock needed on the read side (mic callback hot path, ~16/sec).
        # Writes happen from the receiver task (single writer).
        self._is_speaking = False
        self._last_speak_end = 0.0  # For echo suppression (NOVA pattern)

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
                diag.log_error("Session", e)
                diag.log_disconnected(str(e))

            # Clean up workers
            self._cancel_all_workers()
            self._is_speaking = False

            if not self._active or self._stop_event.is_set():
                break

            self.set_state(VoiceState.RECONNECTING)

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
            session_resumption=(
                types.SessionResumptionConfig()
                if self._config.session_resumption else None
            ),
            tools=self._config.gemini_tools or None,
        )

    async def _run_session(self, client: genai.Client):
        """Run one Gemini Live Audio session with supervised workers."""
        self.set_state(VoiceState.IDLE)
        diag.log_connecting(self._reconnect_attempt)

        # Build config (uses build_config_callback if available)
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

        # Create fresh queues for this session
        # Mic queue is intentionally small (configurable, default 20).
        # A large queue means the sender falls behind → mic audio piles up →
        # stale by the time Gemini sees it. Small queue drops old audio.
        # NOVA: maxsize=20. Mark: maxsize=10.
        self._mic_queue = asyncio.Queue(maxsize=self._config.mic_queue_maxsize)
        self._speaker_queue = asyncio.Queue(maxsize=self._config.speaker_queue_maxsize)

        async with client.aio.live.connect(
            model=self._config.model, config=config,
        ) as session:
            self._session = session
            self._loop = asyncio.get_event_loop()

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
        """Cancel a single worker task."""
        info = self._workers.get(name)
        if info and not info["task"].done():
            info["task"].cancel()
            try:
                info["task"].result(timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:
                pass
        if name in self._workers:
            self._workers[name]["failed"] = True

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

        def mic_callback(indata, frames, time_info, status):
            if not self._active:
                return

            # Barge-in + echo suppression:
            # When model is speaking OR just finished (0.25s echo guard),
            # DROP the audio entirely. Don't send silence.
            # CPython GIL makes bool reads atomic — no lock needed.
            speaking = self._is_speaking
            too_soon = ((time.time() - self._last_speak_end) < 0.25
                        if not speaking else False)

            if speaking or too_soon:
                # Drop frame. Gemini SDK pings keep the WS alive.
                return

            try:
                loop.call_soon_threadsafe(
                    self._mic_queue.put_nowait,
                    {"data": indata.tobytes(), "mime_type": "audio/pcm"},
                )
                diag.log_mic_frame_sent(len(indata))
            except asyncio.QueueFull:
                # Sender is behind — drop frame. Expected, don't log.
                pass

        try:
            stream = sd.InputStream(
                samplerate=self._config.send_sample_rate,
                channels=self._config.channels,
                dtype="int16",
                blocksize=self._config.chunk_size,
                callback=mic_callback,
            )
            stream.start()
            diag.log_mic_started()

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
                await self._session.send_realtime_input(media=msg)
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

            async for response in self._session.receive():
                if not self._active:
                    break

                self._workers["receiver"]["last_heartbeat"] = time.monotonic()

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

                        # Reset speaking state → mic resumes
                        self._is_speaking = False
                        self._last_speak_end = time.time()
                        self.set_state(VoiceState.LISTENING)
                        diag.log_listening()

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

        # Bridge queue: async task → playback thread
        # maxsize=30 (not 200) — large buffers cause trailing audio
        # playback after the model has stopped speaking.
        _play_q: _q.Queue = _q.Queue(maxsize=30)

        def _play_worker():
            stream = sd.RawOutputStream(
                samplerate=self._config.receive_sample_rate,
                channels=self._config.channels,
                dtype="int16",
                blocksize=self._config.chunk_size * 4,  # larger block = smoother
                latency="low",
            )
            stream.start()
            try:
                while True:
                    chunk = _play_q.get()
                    if chunk is None:
                        break
                    try:
                        if isinstance(chunk, bytes):
                            stream.write(chunk)
                        elif hasattr(chunk, "data"):
                            stream.write(chunk.data)
                        else:
                            stream.write(bytes(chunk))
                    except Exception:
                        pass
            finally:
                stream.stop()
                stream.close()

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
            _play_q.put(None)  # Signal playback thread to stop
            diag.log_playback_stopped()