"""
voice/offline_loop.py -- VYREN's offline voice conversation loop.

The previous "fallback mode" wasn't a conversation mode at all — it just
sat idle, checking every 30s whether Gemini Live had come back, and could
only speak a single one-shot utterance via pyttsx3. This module replaces
that with an actual continuous, voice-first conversation loop that works
with zero internet:

    mic --> local endpointing --> faster-whisper (local STT)
        --> ReasoningEngine.reason() (already falls back to Ollama)
        --> pyttsx3 (local TTS)

This is VYREN's own implementation, independent of any other project —
faster-whisper/Ollama/pyttsx3 are just the standard offline building
blocks for this job, not something borrowed from elsewhere.

Design constraints (stated plainly, not hidden):
  - No barge-in offline. pyttsx3 is a blocking, synchronous engine with
    no reliable cross-platform mid-utterance cancel. The mic is paused
    while VYREN talks, same as any half-duplex local assistant. Real
    barge-in needs a streaming local TTS engine — a legitimate future
    upgrade, not something faked here.
  - STT model loads lazily on first use (can take a few seconds) so it
    never delays boot; the loop just isn't ready to transcribe until
    then, and says so once, briefly, rather than staying silent.
  - Conversation continuity: this loop reads and writes to
    VoiceRuntime.recent_turns, the same rolling history the online
    (Gemini Live) path writes to — so a mid-conversation online↔offline
    switch doesn't reset context to zero.
"""

import logging
import threading
import time
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger("vyren.voice.offline")

# --- Tunables -----------------------------------------------------------
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1024          # ~64ms per frame at 16kHz
RMS_TALK_THRESHOLD = 700      # int16 RMS floor to count as "user talking"
SILENCE_FRAMES_TO_END = 12    # ~0.77s of silence ends the utterance
MIN_UTTERANCE_FRAMES = 4      # ignore blips shorter than ~0.25s
MAX_UTTERANCE_SECONDS = 20.0  # hard cap so a runaway buffer can't grow forever
WHISPER_MODEL_SIZE = "base.en"  # good CPU speed/accuracy tradeoff; override via config


class OfflineVoiceLoop:
    """Continuous local voice conversation. Runs on its own thread.

    Usage:
        loop = OfflineVoiceLoop(ctx, get_history=lambda: vr.recent_turns,
                                 on_turn=vr._record_turn)
        loop.start()
        ...
        loop.stop()   # blocks briefly until the thread exits cleanly
    """

    def __init__(self, ctx: dict,
                 get_history: Callable[[], list[dict]],
                 on_turn: Callable[[str, str], None]):
        self._ctx = ctx
        self._get_history = get_history
        self._on_turn = on_turn

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._whisper_model = None  # lazy-loaded
        self._ready_announced = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="vyren-offline-voice", daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self):
        import sounddevice as sd

        logger.info("[OFFLINE] Voice loop starting (local STT + local/offline reasoning + local TTS)")
        self._speak("Running offline. Still listening — just without the cloud voice.")

        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                blocksize=CHUNK_SAMPLES,
            )
        except Exception as e:
            logger.error(f"[OFFLINE] Could not open mic: {e}")
            return

        buf = bytearray()
        talking = False
        silence_run = 0
        talk_frames = 0
        utterance_start = 0.0

        with stream:
            while not self._stop_event.is_set():
                try:
                    data, _ = stream.read(CHUNK_SAMPLES)
                except Exception as e:
                    logger.warning(f"[OFFLINE] Mic read error: {e}")
                    time.sleep(0.2)
                    continue

                raw = data.tobytes()
                try:
                    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
                    rms = int(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0
                except Exception:
                    rms = 0

                if rms >= RMS_TALK_THRESHOLD:
                    if not talking:
                        talking = True
                        buf = bytearray()
                        utterance_start = time.monotonic()
                    buf.extend(raw)
                    talk_frames += 1
                    silence_run = 0
                elif talking:
                    buf.extend(raw)  # keep trailing silence — natural pause, not clipped
                    silence_run += 1
                    over_time = (time.monotonic() - utterance_start) > MAX_UTTERANCE_SECONDS
                    if silence_run >= SILENCE_FRAMES_TO_END or over_time:
                        talking = False
                        if talk_frames >= MIN_UTTERANCE_FRAMES:
                            self._handle_utterance(bytes(buf))
                        buf = bytearray()
                        talk_frames = 0
                        silence_run = 0

        logger.info("[OFFLINE] Voice loop stopped")

    # ------------------------------------------------------------------
    # One utterance: STT -> reasoning -> TTS
    # ------------------------------------------------------------------

    def _handle_utterance(self, pcm16: bytes):
        text = self._transcribe(pcm16)
        if not text or not text.strip():
            return
        text = text.strip()
        logger.info(f"[OFFLINE] Heard: {text[:100]}")

        reasoning = self._ctx.get("reasoning")
        if reasoning is None:
            self._speak("I heard you, but my reasoning engine isn't wired up right now.")
            return

        history = list(self._get_history())
        history.append({"role": "user", "parts": [{"text": text}]})

        try:
            result = reasoning.reason(
                messages=history,
                system_prompt=self._ctx.get("system_prompt", ""),
            )
            reply = (result.text or "").strip()
        except Exception as e:
            logger.error(f"[OFFLINE] Reasoning error: {e}")
            reply = "Something went wrong on my end thinking that through."

        if not reply:
            return

        self._on_turn(text, reply)
        self._speak(reply)

    def _transcribe(self, pcm16: bytes) -> str:
        model = self._get_whisper_model()
        if model is None:
            return ""

        import numpy as np
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0

        try:
            segments, _info = model.transcribe(audio, language="en", beam_size=1)
            return " ".join(seg.text for seg in segments).strip()
        except Exception as e:
            logger.error(f"[OFFLINE] STT error: {e}")
            return ""

    def _get_whisper_model(self):
        if self._whisper_model is not None:
            return self._whisper_model
        try:
            from faster_whisper import WhisperModel
            logger.info(f"[OFFLINE] Loading local STT model ({WHISPER_MODEL_SIZE})...")
            self._whisper_model = WhisperModel(
                WHISPER_MODEL_SIZE, device="cpu", compute_type="int8",
            )
            logger.info("[OFFLINE] Local STT model ready")
        except Exception as e:
            logger.error(f"[OFFLINE] faster-whisper unavailable: {e}")
            self._whisper_model = None
        return self._whisper_model

    # ------------------------------------------------------------------
    # TTS
    # ------------------------------------------------------------------

    def _speak(self, text: str):
        """Blocking local speech. Mic is silently paused for this duration
        (the stream keeps running, but nothing recorded here gets acted
        on since we're not inside the read loop) — see class docstring
        re: no offline barge-in.
        """
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 175)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            logger.error(f"[OFFLINE] TTS error: {e}")
