"""
voice/mobile_session.py -- Per-connection mobile Gemini Live sessions.

One MobileVoiceEngine per WebSocket connection (see
runtime/mobile_live.py for the /ws/live/mobile endpoint that owns these).

Threading model:
  - The engine runs in its own thread + asyncio loop (same as desktop).
  - Engine callbacks (tool calls, turn completion, state changes) fire on
    the engine's loop. All outbound frames are serialized through a
    single writer task on the FastAPI event loop; inbound audio/vision is
    pushed into the engine thread-safely.
"""

import asyncio
import logging
import os
import threading
import uuid

from voice_engine.protocol import (
    AssistantCallbacks, ToolCall, ToolResult, TurnTranscription, VoiceState,
    VoiceEngineConfig,
)

from voice.mobile_engine import MobileVoiceEngine
from voice.runtime import build_live_config, build_voice_system_prompt

logger = logging.getLogger("vyren.voice.mobile.session")

DEFAULT_MOBILE_MODEL = "gemini-3.1-flash-live-preview"
DEFAULT_VOICE_NAME = "Charon"


def default_mobile_model() -> str:
    return os.environ.get("VYREN_MOBILE_MODEL", DEFAULT_MOBILE_MODEL)


class MobileSession:
    """One mobile voice session, backed by one MobileVoiceEngine."""

    def __init__(self, ctx: dict, session_id: str, websocket=None,
                 loop: asyncio.AbstractEventLoop | None = None):
        self._ctx = ctx
        self._session_id = session_id or uuid.uuid4().hex[:12]
        self._websocket = websocket
        self._loop = loop
        self._model = default_mobile_model()
        self._voice_name = DEFAULT_VOICE_NAME

        self._engine: MobileVoiceEngine | None = None
        self._engine_thread: threading.Thread | None = None
        self._resumption_handle: str | None = None
        self._voice_state = "idle"
        self._closed = False

        # Rolling in-session history (Gemini-message format), kept for
        # audit continuity; live context itself is handled by Gemini.
        self.recent_turns: list[dict] = []
        self._max_recent_turns = 20

        # Downlink serialization: single writer task on the FastAPI loop.
        self._write_queue: asyncio.Queue | None = None
        self._writer_task: asyncio.Task | None = None
        self._idle_event: asyncio.Event | None = None

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def voice_state(self) -> str:
        return self._voice_state

    @property
    def engine(self):
        return self._engine

    @property
    def is_active(self) -> bool:
        return bool(self._engine and self._engine.is_active)

    @property
    def closed(self) -> bool:
        return self._closed

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def attach(self, websocket, loop: asyncio.AbstractEventLoop):
        """Bind to the WebSocket + FastAPI loop and start the writer task.

        Must be called from the FastAPI event loop.
        """
        self._websocket = websocket
        self._loop = loop
        if self._loop is not None and not self._closed:
            self._write_queue = asyncio.Queue()
            self._idle_event = asyncio.Event()
            self._idle_event.set()
            self._writer_task = self._loop.create_task(self._writer_loop())

    def start(self):
        """Create the engine and start it in a background thread."""
        if self._engine is not None:
            return
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self._send_json({
                "type": "error",
                "code": "no_api_key",
                "message": "GEMINI_API_KEY is not configured on the server.",
            })
            return

        callbacks = AssistantCallbacks(
            on_tool_call=self._on_tool_call,
            on_turn_complete=self._on_turn_complete,
            on_state_change=self._on_engine_state_change,
            on_transcription=self._on_transcription,
            on_connected=self._on_connected,
            on_error=self._on_error,
        )
        config = VoiceEngineConfig(
            api_key=api_key,
            model=self._model,
            system_prompt=build_voice_system_prompt(self._ctx),
            voice_name=self._voice_name,
            build_config_callback=self._build_live_config,
        )
        self._engine = MobileVoiceEngine(config, callbacks)
        self._engine_thread = threading.Thread(
            target=self._engine.run,
            name=f"vyren-mobile-{self._session_id}",
            daemon=True,
        )
        self._engine_thread.start()
        self._notify_state("connecting")

    def stop(self):
        """Stop the engine and tear down the writer task."""
        if self._closed:
            return
        # Signal the writer task to drain and exit FIRST (raw enqueue,
        # because the _closed guard would otherwise drop it).
        if self._loop is not None and self._write_queue is not None:
            try:
                self._loop.call_soon_threadsafe(
                    self._write_queue.put_nowait, None,
                )
            except Exception:
                pass
        self._closed = True

        engine = self._engine
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass
        if self._engine_thread and self._engine_thread.is_alive():
            self._engine_thread.join(timeout=5)
        if self._writer_task is not None and not self._writer_task.done():
            try:
                self._loop.call_soon_threadsafe(self._writer_task.cancel)
            except Exception:
                pass

    async def iter_audio(self):
        """Yield AI audio chunks (raw PCM 24kHz) for the WebSocket handler."""
        if self._engine is None:
            return
        try:
            async for chunk in self._engine.get_audio_out():
                if self._closed:
                    break
                yield chunk
        except Exception:
            return

    # ------------------------------------------------------------------
    # Client-driven controls
    # ------------------------------------------------------------------

    def push_audio(self, data: bytes):
        if self._engine is not None:
            self._engine.push_audio(data)

    def push_vision_frame(self, data: bytes, mime_type: str = "image/jpeg"):
        if self._engine is not None:
            self._engine.push_vision_frame(data, mime_type)

    def interrupt(self):
        if self._engine is not None:
            try:
                self._engine.interrupt()
            except Exception:
                pass

    def set_model(self, model: str):
        """Switch the underlying Gemini model by rebuilding the engine."""
        model = (model or "").strip()
        if not model or model == self._model:
            return
        old = self._engine
        if old is not None:
            try:
                old.stop()
            except Exception:
                pass
        self._model = model
        # A new model = a new Live context; the old resumption handle is
        # meaningless, so we drop it.
        self._resumption_handle = None
        self._engine = None
        self._engine_thread = None
        self.start()
        self._send_json({"type": "model_changed", "model": self._model})

    # ------------------------------------------------------------------
    # Live config (fresh system prompt + tools on every connect)
    # ------------------------------------------------------------------

    def _build_live_config(self):
        return build_live_config(
            self._ctx,
            voice_name=self._voice_name,
            resumption_handle=self._resumption_handle,
        )

    # ------------------------------------------------------------------
    # Engine callbacks
    # ------------------------------------------------------------------

    def _on_connected(self):
        logger.info("Mobile voice connected: session=%s model=%s",
                    self._session_id, self._model)
        self._send_json({"type": "connected"})

    def _on_engine_state_change(self, state: VoiceState):
        state_value = state.value if hasattr(state, "value") else str(state)
        self._voice_state = state_value
        if state == VoiceState.LISTENING and self._engine is not None:
            handle = getattr(self._engine, "_resumption_handle", None)
            if handle:
                self._resumption_handle = handle
        self._send_json({"type": "state_change", "state": state_value})

    def _on_transcription(self, user_text: str, model_text: str):
        if user_text:
            self._send_json({
                "type": "transcription",
                "user": user_text,
                "model": "",
                "final": False,
            })
        if model_text:
            self._send_json({
                "type": "transcription",
                "user": "",
                "model": model_text,
                "final": False,
            })

    def _on_turn_complete(self, turn: TurnTranscription):
        audit = self._ctx.get("audit")
        if audit:
            if turn.user_text:
                audit.model_turn("user", turn.user_text)
            if turn.model_text:
                audit.model_turn("model", turn.model_text)

        if turn.user_text or turn.model_text:
            self._record_turn(turn.user_text, turn.model_text)

        self._send_json({
            "type": "transcription",
            "user": turn.user_text or "",
            "model": turn.model_text or "",
            "final": True,
        })
        self._send_json({"type": "turn_complete"})

        logger.info("Mobile turn complete — User: '%s' | VYREN: '%s'",
                    (turn.user_text or "")[:60], (turn.model_text or "")[:60])

    def _record_turn(self, user_text: str, model_text: str):
        if user_text:
            self.recent_turns.append({"role": "user", "parts": [{"text": user_text}]})
        if model_text:
            self.recent_turns.append({"role": "model", "parts": [{"text": model_text}]})
        if len(self.recent_turns) > self._max_recent_turns:
            self.recent_turns = self.recent_turns[-self._max_recent_turns:]

    async def _on_tool_call(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        registry = self._ctx.get("registry")
        audit = self._ctx.get("audit")
        event_bus = self._ctx.get("event_bus")

        results = []
        for tc in tool_calls:
            name, args = tc.name, tc.args
            if audit:
                audit.tool_call(name, args, "(mobile)")

            self._send_json({
                "type": "tool_call",
                "name": name,
                "args": args,
                "status": "started",
            })

            if registry:
                try:
                    result = await asyncio.to_thread(registry.execute, name, args)
                except Exception as e:
                    result = f"Error: {e}"
                    logger.error("Mobile voice tool error: %s -> %s", name, e)
            else:
                result = "Error: no tool registry"

            self._send_json({
                "type": "tool_result",
                "name": name,
                "result": str(result)[:300],
                "status": "done",
            })

            if audit:
                audit.tool_call(name, args, str(result)[:100])

            if event_bus:
                try:
                    from event_bus import Event
                    event_bus.publish_sync(Event(
                        type="vyren.tool_called",
                        source="mobile",
                        data={"tool": name, "args": args, "result_preview": str(result)[:100]},
                    ))
                except Exception:
                    pass

            results.append(ToolResult(id=tc.id, name=name, result=str(result)))

        return results

    def _on_error(self, error: str):
        logger.error("Mobile voice engine error: %s", error)
        self._send_json({"type": "error", "code": "engine_error", "message": error})

    # ------------------------------------------------------------------
    # Downlink
    # ------------------------------------------------------------------

    async def _writer_loop(self):
        ws = self._websocket
        queue = self._write_queue
        idle = self._idle_event
        while queue is not None:
            try:
                item = await queue.get()
            except asyncio.CancelledError:
                break
            if item is None:
                break
            kind, payload = item
            if ws is None:
                continue
            if idle is not None:
                idle.clear()
            try:
                if kind == "text":
                    await ws.send_json(payload)
                else:
                    await ws.send_bytes(payload)
            except Exception:
                break
            if idle is not None:
                idle.set()
        self._closed = True

    async def flush_writer(self, timeout: float = 1.0):
        """Wait until previously enqueued frames have been sent by
        the writer task. Must be called from the FastAPI event loop.
        """
        queue = self._write_queue
        idle = self._idle_event
        if queue is None or idle is None:
            return
        deadline = asyncio.get_running_loop().time() + max(timeout, 0.0)
        while True:
            await asyncio.sleep(0.01)
            if queue.empty() and idle.is_set():
                break
            if asyncio.get_running_loop().time() > deadline:
                break

    def _send_json(self, msg: dict):
        self._enqueue(("text", msg))

    def _send_bytes(self, data: bytes):
        self._enqueue(("bytes", data))

    def _enqueue(self, item):
        if self._closed or self._loop is None or self._write_queue is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._write_queue.put_nowait, item)
        except Exception:
            pass

    def _notify_state(self, display_state: str):
        self._voice_state = display_state
        self._send_json({"type": "state_change", "state": display_state})


class MobileSessionManager:
    """Registry of active mobile sessions, one engine per connection."""

    def __init__(self):
        self._sessions: dict[str, MobileSession] = {}
        self._resumption_handles: dict[str, str] = {}
        self._lock = threading.Lock()

    def create(self, ctx: dict, session_id: str | None = None,
               websocket=None, loop=None) -> MobileSession:
        with self._lock:
            sid = (session_id or "").strip() or uuid.uuid4().hex[:12]
            existing = self._sessions.get(sid)
            if existing is not None and not existing.closed:
                existing.stop()
                del self._sessions[sid]
            session = MobileSession(ctx, sid, websocket, loop)
            stored = self._resumption_handles.pop(sid, None)
            if stored:
                session._resumption_handle = stored
            self._sessions[sid] = session
            return session

    def get(self, session_id: str):
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id: str) -> MobileSession | None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            # Best-effort: keep the Gemini resumption handle so a quick
            # reconnect with the same session_id can resume context.
            if session.engine is not None:
                handle = getattr(session.engine, "_resumption_handle", None)
                if handle:
                    self._resumption_handles[session_id] = handle
            session.stop()
        return session

    def close_all(self):
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            s.stop()