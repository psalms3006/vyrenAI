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
    api_key: str = ""
    model: str = "models/gemini-2.5-flash-native-audio-preview-12-2025"
    voice_name: str = "Charon"

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

    # Audio queue sizing
    # Mic queue: small (20) to drop stale audio and keep latency low.
    # Large queues buffer old frames → trailing playback after model stops.
    # NOVA uses maxsize=20. Mark uses maxsize=10.
    mic_queue_maxsize: int = 20
    # Speaker queue: moderate (30) to absorb brief Gemini output bursts
    # without buffering seconds of stale audio.
    speaker_queue_maxsize: int = 30

    # Speaking detection: how long with no audio before declaring speech ended
    speech_end_timeout: float = 0.8

    # Mic heartbeat: if no frames queued in this many seconds, mic is dead
    mic_heartbeat_timeout: float = 5.0