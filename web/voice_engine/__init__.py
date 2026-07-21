"""
voice_engine/__init__.py -- Shared Voice Engine.

A reusable, assistant-agnostic voice subsystem built on Gemini Live Native Audio.

Architecture:

    Supervisor (async loop, checks heartbeats every 2s)
      ├── Mic Worker      (sounddevice InputStream, queues PCM bytes)
      ├── Sender Worker   (reads mic queue → sends to Gemini)
      ├── Receiver Worker (reads Gemini responses → routes audio/tools/transcription)
      └── Speaker Worker  (reads speaker queue → writes to speakers)

Key design principles:

1. INDEPENDENT WORKERS — NOT in a TaskGroup.
   Each worker is an independent asyncio.create_task. If one dies,
   the supervisor restarts ONLY that worker. The others keep running.

2. The mic stream stays OPEN the entire session.
   Barge-in is handled by checking _is_speaking in the mic callback.
   When the model speaks, mic audio is dropped. When done, mic flows again.

3. turn_complete is the ONLY signal that ends a turn.
   Gemini decides when a turn is done. We set _is_speaking = False.
   The mic callback sees _is_speaking = False and resumes sending audio.

4. Reconnection: outer while-True loop. On any exception, back off and reconnect.
   Session resumption config means Gemini remembers the conversation.
   Mic and speaker streams are NOT torn down during reconnect.

5. FSM: Every state transition is validated. Illegal transitions are logged
   and rejected. The reported state always reflects reality.

6. Mic heartbeat: If no mic frames arrive for N seconds while in LISTENING
   state, the supervisor detects it and restarts the mic worker only.

Usage by any assistant:
    engine = GeminiLiveVoiceEngine(config, callbacks)
    engine.run()  # Blocks until shutdown
"""

from voice_engine.engine import GeminiLiveVoiceEngine
from voice_engine.protocol import AssistantCallbacks, VoiceState

__all__ = ["GeminiLiveVoiceEngine", "AssistantCallbacks", "VoiceState"]
__version__ = "2.2.0"