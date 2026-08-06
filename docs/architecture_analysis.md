# VYREN Architecture Analysis — Phase 1

## Existing Components
- `main.py` — entrypoint → `RuntimeManager`
- `boot/manager.py` — 18-phase boot with dependency ordering and restart_on_failure flags
- `runtime/manager.py` — central orchestrator, supervisor thread, always-on loop
- `voice/runtime.py` — thin adapter to shared voice engine
- `voice_engine/engine.py` — production-grade Gemini Live voice engine with supervisor/restart
- `voice_engine/protocol.py` — voice FSM + config/tooling protocol
- `voice_engine/conversation_manager.py` — human-facing conversation phase tracking
- `voice_engine/voice_supervisor.py` — higher-level voice health/recovery checks
- `interaction/` — interaction controller, media awareness, mode manager
- `event_bus.py` — pub/sub event system with wildcard matching
- `world_model.py` — persistent project/app/device/schedule/workflow model
- `memory_v2.py` — multi-layer memory with decay, consolidation, hash embeddings
- `tools/` — registry + tool implementations for screen, vision, filesystem, web, etc.
- `runtime/web_server.py` — FastAPI + WS dashboard with thread-safe broadcast
- `runtime/terminal.py` — terminal REPL bridge
- `config.py` — YAML config loader with dotpath access
- `identity.py`, `environment.py`, `platform_paths.py` — identity, capability flags, paths
- `agent/`, `agents/`, `brain/`, `scheduler/`, `reliability.py` — planning, scheduling, circuit breakers

## Missing Components
- Camera Engine (`camera/`)
- Vision Engine (`vision/`)
- Awareness Engine (`awareness/`)
- Hand Tracking / Gesture Engine
- Face system
- Audio+Vision fusion context engine
- State Engine (`state_engine/`)
- Phone Bridge (`phone/`)
- RAG system
- ML training pipeline
- Persistent memory write-through guarantees
- Standalone test harnesses for multimodal subsystems

## Duplicate Logic
- `voice.py` and `voice/runtime.py` — dual voice entry paths; confirm only one is active at runtime
- `provider.py` and potential duplicate client construction; consolidate through `provider.get_cached_client()`
- Multiple `__pycache__`/duplicate imports across Python version variants; keep runtime single-interpreter

## Dead Code
- `voice.py` may be legacy; verify if still used by `main.py`
- Stale imports/comments referencing removed env vars like `MESSAGING_CWD`, `TERMINAL_CWD`
- Unused temp verification scripts under `AppData\Local\Temp`

## Runtime Risks
- Long-running async voice session depends on keepalive/resumption; reconnect loops still possible under prolonged outages
- `EventBus.publish_sync()` schedules async handlers without awaiting; failures can be silent
- `WorldModel._save()` on every mutation can become contention point under rapid observations
- Supervisor thread + voice thread + uvicorn threads increase thread count; ensure shutdown ordering is safe

## Performance Bottlenecks
- Sync disk writes in world model/memory on every mutation
- Blocking fallback TTS via `pyttsx3` in `_speak_fallback()`
- Synchronous tool execution in voice callbacks via `asyncio.to_thread(registry.execute, ...)`
- `publish_sync()` creates `create_task` without backpressure

## Race Conditions / Memory Leaps
- EventBus `_loop` may be `None` during early startup; async handlers are skipped
- `VoiceRuntime` state mutation from both engine thread and main thread without strong ordering guarantees
- `ConversationManager` history grows unbounded beyond 500 entries; acceptable but should be capped/configurable

## Blocking Operations
- `WorldModel._save()` is blocking file I/O
- `pyttsx3` runAndWait blocks fallback voice thread
- Tool registry `execute` in voice path blocks async loop unless run in thread

## Scalability Concerns
- EventBus history is in-memory only; no persistence or replay
- World model is single-file JSON; no versioning/transaction safety
- Memory v2 has local cache only; no cross-process/shared memory
- No camera/vision queue architecture yet

## Preserve
- Keep existing boot phases and service registry pattern
- Preserve voice-first architecture and barge-in behavior
- Keep world model + memory_v2 data contracts
- Maintain FastAPI web server and thread-safe broadcast
