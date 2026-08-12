"""
voice/mobile_engine.py -- Mobile-optimized Gemini Live voice engine.

Replaces local hardware I/O with WebSocket-ready queues and adds
support for vision frames (multimodal Gemini Live).

Threading model:
  - The engine runs on its own asyncio event loop (engine thread), the
    same as the desktop VoiceRuntime.
  - All inter-thread queue access from the WebSocket/server thread is
    marshalled with call_soon_threadsafe (uplink) or
    run_coroutine_threadsafe (downlink). This mirrors the shared
    voice_engine + runtime.web_server bridge pattern.
"""

import asyncio
import logging
import time
from typing import Any, AsyncGenerator

try:
    from google.genai import types
except Exception:
    class types:
        Blob = Any
        LiveConnectConfig = Any
        Modality = Any

from voice_engine.engine import GeminiLiveVoiceEngine
from voice_engine.protocol import (
    AssistantCallbacks, VoiceEngineConfig, VoiceState,
    ToolCall, ToolResult, TurnTranscription
)
from voice_engine import diagnostics as diag

logger = logging.getLogger("vyren.voice.mobile")

class MobileVoiceEngine(GeminiLiveVoiceEngine):
    """
    Mobile-optimized Gemini Live voice engine.
    Swaps sounddevice for WebSocket-fed queues.
    """

    def __init__(self, config: VoiceEngineConfig, callbacks: AssistantCallbacks):
        super().__init__(config, callbacks)
        # Loop-bound queues are created in run_async() (engine loop), NOT
        # here — an asyncio.Queue created outside a running loop binds to
        # a synthetic loop and is unsafe to touch from either real loop.
        self._vision_queue: asyncio.Queue | None = None
        self._audio_out_queue: asyncio.Queue | None = None

    # ------------------------------------------------------------------
    # Engine lifecycle
    # ------------------------------------------------------------------

    async def run_async(self):
        """Create loop-bound queues, then run the normal engine loop."""
        self._vision_queue = asyncio.Queue(maxsize=10)
        self._audio_out_queue = asyncio.Queue(maxsize=200)
        await super().run_async()

    # ------------------------------------------------------------------
    # Mobile API (called from the WebSocket/server thread)
    # ------------------------------------------------------------------

    def push_audio(self, data: bytes):
        """Push PCM 16-bit 16kHz audio from mobile app (thread-safe)."""
        if not self._active or not self._mic_queue or not self._loop:
            return
        try:
            item = {
                "data": data,
                "mime_type": f"audio/pcm;rate={self._config.send_sample_rate}",
            }
            self._loop.call_soon_threadsafe(
                self._mic_queue.put_nowait, item,
            )
            diag.log_mic_frame_sent(len(data))
            if "mic" in self._workers:
                self._workers["mic"]["last_heartbeat"] = time.monotonic()
        except asyncio.QueueFull:
            diag.log_mic_dropped("mobile_queue_full")
        except Exception:
            diag.log_mic_dropped("mobile_push_failed")

    def push_vision_frame(self, data: bytes, mime_type: str = "image/jpeg"):
        """Push a vision frame (JPEG/WebP) for multimodal understanding."""
        if not self._active or not self._vision_queue or not self._loop:
            return
        try:
            item = {"data": data, "mime_type": mime_type}
            self._loop.call_soon_threadsafe(
                self._vision_queue.put_nowait, item,
            )
        except asyncio.QueueFull:
            pass  # Vision is lower priority, safe to drop
        except Exception:
            pass

    async def get_audio_out(self) -> AsyncGenerator[bytes, None]:
        """Async drain of AI audio for the WebSocket handler.

        Runs on the CONSUMER's loop (the FastAPI event loop). Each read
        is bridged onto the engine loop with run_coroutine_threadsafe so
        the queue itself is only ever touched by its owning loop.
        """
        engine_loop = self._loop
        queue = self._audio_out_queue
        if engine_loop is None or queue is None:
            return
        while self._active or not self._closed_signal():
            try:
                chunk = await asyncio.run_coroutine_threadsafe(
                    queue.get(), engine_loop,
                )
            except (asyncio.CancelledError, RuntimeError, Exception):
                break
            if chunk is None:
                break
            yield chunk

    def _closed_signal(self) -> bool:
        """Best-effort check used by get_audio_out to stop draining."""
        try:
            return not self._active and self._audio_out_queue is not None and self._audio_out_queue.empty()
        except Exception:
            return True

    # ------------------------------------------------------------------
    # Overrides: Hardware removal
    # ------------------------------------------------------------------

    async def _worker_mic(self):
        """No-op hardware worker: data is pushed via push_audio()."""
        logger.info("[MOBILE_ENGINE] Mic hardware worker disabled (mobile-fed)")
        while self._active:
            await asyncio.sleep(2.0)
            if "mic" in self._workers:
                self._workers["mic"]["last_heartbeat"] = time.monotonic()

    async def _worker_speaker(self):
        """No-op hardware worker: audio is drained via get_audio_out()."""
        logger.info("[MOBILE_ENGINE] Speaker hardware worker disabled (websocket-fed)")
        while self._active:
            try:
                chunk = await asyncio.wait_for(self._speaker_queue.get(), timeout=1.0)
                self._workers["speaker"]["last_heartbeat"] = time.monotonic()

                if isinstance(chunk, bytes):
                    data = chunk
                elif hasattr(chunk, "data"):
                    data = chunk.data
                else:
                    data = bytes(chunk)

                try:
                    self._audio_out_queue.put_nowait(data)
                except asyncio.QueueFull:
                    pass
            except asyncio.TimeoutError:
                if "speaker" in self._workers:
                    self._workers["speaker"]["last_heartbeat"] = time.monotonic()
                continue
            except Exception as e:
                logger.error("[MOBILE_ENGINE] Speaker bridge error: %s", e)

    # ------------------------------------------------------------------
    # Overrides: Multimodal support
    # ------------------------------------------------------------------

    def _build_session_config(self):
        """Override config to ensure audio modality (vision is sent as input)."""
        config = super()._build_session_config()
        # Gemini Live only responds with audio, but can receive image blobs.
        config.response_modalities = [types.Modality.AUDIO]
        return config

    async def _worker_sender(self):
        """Sender that interleaves audio AND vision frames (engine loop).

        Audio (mic) is read from the engine loop's _mic_queue; vision
        frames are drained non-blocking from _vision_queue with audio
        taking priority.
        """
        while self._active:
            if not self._session:
                await asyncio.sleep(0.1)
                if "sender" in self._workers:
                    self._workers["sender"]["last_heartbeat"] = time.monotonic()
                continue

            # 1) Drain any queued vision frames (non-blocking, lower priority).
            if self._vision_queue is not None:
                while True:
                    try:
                        vision = self._vision_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    try:
                        async with self._send_lock:
                            await self._session.send_realtime_input(
                                image=types.Blob(
                                    data=vision["data"],
                                    mime_type=vision["mime_type"],
                                )
                            )
                    except Exception as e:
                        logger.error("[SENDER] Vision send failed: %s", e)

            # 2) Wait briefly for audio.
            if self._mic_queue is not None:
                try:
                    msg = await asyncio.wait_for(self._mic_queue.get(), timeout=0.5)
                    async with self._send_lock:
                        await self._session.send_realtime_input(
                            audio=types.Blob(
                                data=msg["data"],
                                mime_type=msg["mime_type"],
                            )
                        )
                except asyncio.TimeoutError:
                    pass
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("[SENDER] Audio send failed: %s", e)

            if "sender" in self._workers:
                self._workers["sender"]["last_heartbeat"] = time.monotonic()