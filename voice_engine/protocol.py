"""
voice_engine/protocol.py -- Interface between the voice engine and any assistant.

The voice engine knows NOTHING about VYREN, NOVA, or any specific assistant.
It communicates exclusively through this protocol.

v2.2 changes:
  - Added build_config_callback to VoiceEngineConfig (NOVA's _build_config pattern)
  - Reduced queue defaults: mic 100→20, speaker 100→30
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable


class VoiceState(Enum):
    """Voice engine finite state machine states.

    Transitions:
        BOOTING → IDLE
        IDLE → LISTENING (mic stream confirmed active)
        LISTENING → STREAMING (audio being sent to Gemini)
        STREAMING → THINKING (user stopped, Gemini processing)
        THINKING → SPEAKING (audio arriving from Gemini)
        SPEAKING → LISTENING (turn_complete or audio ended)
        LISTENING → EXECUTING_TOOL (tool call received)
        EXECUTING_TOOL → THINKING (tool results sent, waiting for Gemini)
        SPEAKING → LISTENING (barge-in: user spoke while model speaking)
        Any → RECONNECTING (connection lost)
        RECONNECTING → LISTENING (reconnected)
        Any → FAILED (fatal error)
        FAILED → RECONNECTING (supervisor restarts)
    """
    BOOTING = "booting"
    IDLE = "idle"
    LISTENING = "listening"
    STREAMING = "streaming"
    THINKING = "thinking"
    SPEAKING = "speaking"
    EXECUTING_TOOL = "executing_tool"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


# Valid state transitions. Any transition NOT in this set is illegal.
VALID_TRANSITIONS: dict[VoiceState, set[VoiceState]] = {
    VoiceState.BOOTING: {VoiceState.IDLE, VoiceState.FAILED},
    VoiceState.IDLE: {VoiceState.LISTENING, VoiceState.RECONNECTING, VoiceState.FAILED},
    VoiceState.LISTENING: {VoiceState.STREAMING, VoiceState.THINKING, VoiceState.SPEAKING,
                           VoiceState.EXECUTING_TOOL, VoiceState.RECONNECTING, VoiceState.FAILED},
    VoiceState.STREAMING: {VoiceState.THINKING, VoiceState.LISTENING, VoiceState.SPEAKING,
                           VoiceState.RECONNECTING, VoiceState.FAILED},
    VoiceState.THINKING: {VoiceState.SPEAKING, VoiceState.EXECUTING_TOOL, VoiceState.LISTENING,
                          VoiceState.RECONNECTING, VoiceState.FAILED},
    VoiceState.SPEAKING: {VoiceState.LISTENING, VoiceState.THINKING, VoiceState.RECONNECTING,
                          VoiceState.FAILED},
    VoiceState.EXECUTING_TOOL: {VoiceState.THINKING, VoiceState.SPEAKING, VoiceState.LISTENING,
                                VoiceState.RECONNECTING, VoiceState.FAILED},
    VoiceState.RECONNECTING: {VoiceState.LISTENING, VoiceState.IDLE, VoiceState.FAILED},
    VoiceState.FAILED: {VoiceState.RECONNECTING},
}


@dataclass
class ToolCall:
    """A tool/function call from the voice model."""
    id: str
    name: str
    args: dict


@dataclass
class ToolResult:
    """Result to send back after executing a tool."""
    id: str
    name: str
    result: str


@dataclass
class TurnTranscription:
    """Transcription of a completed turn (user spoke, model responded)."""
    user_text: str = ""
    model_text: str = ""


@dataclass
class AssistantCallbacks:
    """Callbacks that any assistant must provide to the voice engine.

    The voice engine calls these during operation. The assistant implements
    them to inject its own personality, tools, memory, etc.

    All methods can be sync or async. The engine handles both.
    """

    # Called when a tool/function call arrives from the model.
    # Return a list of ToolResult (one per function call).
    on_tool_call: Callable[[list[ToolCall]], Awaitable[list[ToolResult]]]

    # Called when a complete turn finishes (user spoke, model responded).
    on_turn_complete: Callable[[TurnTranscription], None] | None = None

    # Called when voice state changes (listening, speaking, etc.)
    on_state_change: Callable[[VoiceState], None] | None = None

    # Called with real-time transcription fragments as they arrive.
    # user_text: partial transcription of what the user is saying
    # model_text: partial transcription of what the model is saying
    on_transcription: Callable[[str, str], None] | None = None

    # Called when the engine connects or reconnects.
    on_connected: Callable[[], None] | None = None

    # Called when an error occurs (for UI display / logging).
    on_error: Callable[[str], None] | None = None


@dataclass
class VoiceEngineConfig:
    """Configuration for the voice engine."""

    # Gemini
    # v2.5's model is deprecated (Google migration notice, 2026) — 3.1 is the
    # current low-latency Live model. tools=None means the sequential-only
    # tool-calling change on 3.1 is a non-issue for the voice channel.
    api_key: str = ""
    model: str = "gemini-3.1-flash-live-preview"
    voice_name: str = "Charon"

    # --- Turn-taking / VAD (server-side endpointing) ---
    # These are the single biggest lever on perceived latency: how long
    # Gemini waits through silence before it decides you're done talking,
    # and how much audio it keeps before the detected speech onset.
    # Unset, the API defaults are tuned for accuracy over snappiness.
    vad_start_sensitivity: str = "high"   # "low" | "high" — reacts to speech onset faster
    vad_end_sensitivity: str = "high"     # "low" | "high" — ends turn faster on silence
    vad_prefix_padding_ms: int = 50       # look-back so first syllable isn't clipped
    vad_silence_duration_ms: int = 300    # silence required before turn is considered over

    # --- Thinking budget ---
    # Native-audio models can "think" before speaking; a nonzero/unset budget
    # adds a delay before the first audio byte. "minimal" trades deep
    # reasoning for immediacy — voice-first conversation wants immediacy.
    thinking_level: str = "minimal"

    # --- Long-session token compression ---
    # Native audio accumulates ~25 tokens/sec. Left uncompressed, a long
    # session's context keeps growing and per-turn latency creeps up.
    context_compression_trigger_tokens: int = 100_000
    context_compression_target_tokens: int = 4_000

    # Audio
    send_sample_rate: int = 16000
    receive_sample_rate: int = 24000
    channels: int = 1
    chunk_size: int = 1024

    # System prompt (built by the assistant, passed to Gemini)
    system_prompt: str = ""

    # Tool declarations in Gemini format:
    # [{"function_declarations": [...]}]
    # Can be raw dicts (NOVA's proven pattern) or types.Tool objects.
    gemini_tools: list[dict] = field(default_factory=list)

    # Dynamic config builder (NOVA's _build_config pattern).
    # If provided, the engine calls this on every connect/reconnect
    # to get a fresh LiveConnectConfig. This ensures memory context,
    # time, and other dynamic data stays current across reconnects.
    # Signature: () -> types.LiveConnectConfig
    # If it returns None, the engine falls back to its built-in config.
    build_config_callback: Callable[[], Any] | None = None

    # Behavior
    reconnect_delay: float = 3.0
    max_reconnect_delay: float = 60.0
    session_resumption: bool = True

    # After this many consecutive failed reconnect attempts, stop retrying
    # and transition to FAILED instead of backing off forever. This is
    # the signal VoiceRuntime uses to give up on Gemini Live and switch
    # to the offline conversation loop — without it, the engine just
    # retries with capped backoff indefinitely while offline, and nothing
    # ever tells the rest of the system "give up, go local."
    max_consecutive_reconnect_failures: int = 4

    # Audio queue sizing
    # Mic queue: 50 — large enough to absorb brief sender hiccups
    # without dropping frames. At ~16 chunks/sec (480 samples @ 16kHz
    # with default sounddevice blocksize), this is ~3 seconds of buffer.
    # The sender drains fast (pure async I/O), so it rarely fills up.
    # Speaker queue: 200 — Gemini output is bursty. We need a large
    # buffer so the playback thread never starves (starvation = cracking).
    mic_queue_maxsize: int = 50
    speaker_queue_maxsize: int = 200

    # Barge-in: mic stays hot even while VYREN is speaking (true full-duplex —
    # required for Gemini's server-side VAD to ever see the interruption and
    # fire `server_content.interrupted`, which is what actually stops
    # playback). A short energy gate still exists (see engine.py) purely to
    # avoid re-triggering off VYREN's own voice bleeding into the mic on
    # speaker setups without hardware echo cancellation; use headphones for
    # the cleanest barge-in.
    barge_in_enabled: bool = True
    barge_in_rms_threshold: int = 900  # int16 RMS floor to count as "real" speech

    # Mic heartbeat: if no frames queued in this many seconds, mic is dead
    # 10s gives the mic time to start producing after session connect.
    # The first check after session start skips this (initialized to now).
    mic_heartbeat_timeout: float = 10.0