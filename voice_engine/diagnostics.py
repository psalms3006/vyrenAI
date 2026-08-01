"""
voice_engine/diagnostics.py -- Structured diagnostic logging with heartbeat tracking.

Every voice event is logged with a consistent prefix and level.
This makes it trivial to follow the conversation flow in logs.

CRITICAL ADDITION: Frame counters and heartbeats.
The old diagnostics had no way to detect when the mic died silently.
Now we track:
  - mic_frames_sent:  total frames sent to Gemini
  - mic_frames_dropped: frames dropped (barge-in, queue full)
  - speaker_frames_played: frames written to speakers
  - last_mic_frame_time: monotonic timestamp of the last mic frame
  - last_speaker_frame_time: monotonic timestamp of the last speaker frame
"""

import logging
import threading
import time

logger = logging.getLogger("vyren.voice.engine")

# Global counters — updated from multiple threads, read from supervisor
_counters_lock = threading.Lock()
_counters: dict = {
    "mic_frames_sent": 0,
    "mic_frames_dropped": 0,
    "speaker_frames_played": 0,
    "last_mic_frame_time": 0.0,
    "last_speaker_frame_time": 0.0,
    "turns_completed": 0,
    "reconnect_count": 0,
    "errors": 0,
    "tool_calls": 0,
    "session_start_time": 0.0,
}


def reset_counters():
    global _counters
    with _counters_lock:
        _counters = {k: 0.0 if isinstance(v, float) else 0 for k, v in _counters.items()}
        _counters["session_start_time"] = time.monotonic()


def init_session():
    """Initialize session counters. Call when a new session starts.

    Sets last_mic_frame_time to NOW (not 0.0) to prevent false
    "MIC DEAD" on the first supervisor check.
    """
    global _counters
    now = time.monotonic()
    with _counters_lock:
        _counters["last_mic_frame_time"] = now
        _counters["session_start_time"] = now


def get_counters() -> dict:
    with _counters_lock:
        return dict(_counters)


def _inc(key: str, n: int = 1):
    with _counters_lock:
        _counters[key] += n


def _touch(key: str):
    with _counters_lock:
        _counters[key] = time.monotonic()


# ---------------------------------------------------------------------------
# Mic events
# ---------------------------------------------------------------------------

def log_mic_started():
    logger.info("[MIC] Microphone stream opened. Listening continuously.")
    with _counters_lock:
        _counters["session_start_time"] = time.monotonic()


def log_mic_stopped():
    logger.info("[MIC] Microphone stream closed.")


def log_mic_frame_sent(size: int):
    with _counters_lock:
        _counters["mic_frames_sent"] += 1
        _counters["last_mic_frame_time"] = time.monotonic()


def log_mic_dropped(reason: str = "speaking"):
    _inc("mic_frames_dropped")
    logger.debug("[MIC] Audio dropped (%s).", reason)


def log_mic_dead(seconds_since_last: float):
    logger.warning("[MIC] DEAD — no frames for %.1fs. Mic stream is open but not producing audio.",
                   seconds_since_last)


# ---------------------------------------------------------------------------
# Playback events
# ---------------------------------------------------------------------------

def log_playback_started():
    logger.info("[PLAYBACK] Speaker stream opened. Ready to play.")


def log_playback_stopped():
    logger.info("[PLAYBACK] Speaker stream closed.")


def log_speech_started():
    logger.info("[STATE] -> SPEAKING")


def log_speech_ended():
    logger.info("[STATE] SPEAKING -> LISTENING")


def log_speaker_frame(size: int):
    _inc("speaker_frames_played")
    _touch("last_speaker_frame_time")


# ---------------------------------------------------------------------------
# Connection events
# ---------------------------------------------------------------------------

def log_connecting(attempt: int = 1):
    logger.info("[CONNECT] Connecting to Gemini Live Audio (attempt %d)...", attempt)


def log_connected(session_id: str = ""):
    logger.info("[CONNECT] Connected to Gemini Live Audio. Session active.")


def log_disconnected(reason: str = ""):
    logger.warning("[DISCONNECT] Session ended. %s", reason if reason else "Reconnecting...")
    _inc("reconnect_count")
    _inc("errors")


def log_reconnecting(delay: float):
    logger.info("[RECONNECT] Waiting %.1fs before reconnecting...", delay)


def log_reconnect_success():
    logger.info("[RECONNECT] Reconnected successfully.")


# ---------------------------------------------------------------------------
# State events
# ---------------------------------------------------------------------------

def log_thinking():
    logger.info("[STATE] -> THINKING")


def log_listening():
    logger.info("[STATE] -> LISTENING")


def log_tool_received(name: str, args: dict):
    _inc("tool_calls")
    logger.info("[TOOL] Received: %s  args=%s", name, str(args)[:100])


def log_tool_result(name: str, result_preview: str):
    logger.info("[TOOL] Result: %s -> %s", name, result_preview[:80])


def log_tool_error(name: str, error: str):
    logger.error("[TOOL] Error: %s -> %s", name, error[:120])


def log_turn_complete(user_text: str, model_text: str):
    _inc("turns_completed")
    u = user_text[:80] + "..." if len(user_text) > 80 else user_text
    m = model_text[:80] + "..." if len(model_text) > 80 else model_text
    logger.info("[TURN] Complete. User: \"%s\" | Model: \"%s\"", u, m)


# ---------------------------------------------------------------------------
# Transcription / Audio
# ---------------------------------------------------------------------------

def log_transcription_user(text: str):
    logger.debug("[STT] User: %s", text[:100])


def log_transcription_model(text: str):
    logger.debug("[TTS] Model: %s", text[:100])


def log_audio_chunk(direction: str, size: int):
    logger.debug("[AUDIO] %s %d bytes", direction, size)


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

def log_error(context: str, error: Exception):
    _inc("errors")
    logger.error("[ERROR] %s: %s", context, error)


def log_illegal_transition(old: str, new: str):
    _inc("errors")
    logger.error("[FSM] ILLEGAL transition: %s -> %s", old, new)