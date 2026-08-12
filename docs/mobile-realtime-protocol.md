# Mobile Realtime Protocol (VYREN MRP v1.0)

## Overview
The VYREN Mobile Realtime Protocol (MRP) is a specialized adapter protocol designed to bridge the native React Native mobile application with the existing VYREN voice and AI infrastructure. It facilitates low-latency, full-duplex audio/video streaming while maintaining strict compatibility with the `VoiceState` FSM defined in `voice_engine/protocol.py`.

## 1. Connection Lifecycle

### Handshake & Authentication
- **Endpoint:** `wss://<host>:<port>/ws/live/mobile`
- **Authentication:** Standard JWT or API Key passed via query parameters or headers.
- **Handshake:**
  - Client sends `{"type": "init", "client": "mobile", "version": "1.0", "session_id": "optional-previous-id", "model": "optional-model"}`.
  - Server responds with `{"type": "init_ack", "voice_state": "idle", "capabilities": ["audio", "vision", "model_switch", "resumption"], "session_id": "...", "model": "gemini-3.1-flash-live-preview"}`.
  - The `session_id` is reused when the client reconnects; Gemini session resumption is a best-effort carryover of the Live resumption handle.
  - The first frame MUST be `init`; anything else is answered with `{"type": "error", "code": "bad_init"}` and the socket is closed.
  - The engine is booted asynchronously; after the handshake the server pushes a `{"type": "connected"}` frame once the Live session is up, and `state_change` frames throughout.

### Session Management
- **Keep-Alive:** Client sends a `ping` every 15s; Server responds with `pong`.
- **Termination:** Either party sends `{"type": "terminate", "reason": "user_exit|error"}`; the server acknowledges with `{"type": "terminate_ack", "reason": "..."}` before closing.
- **Reconnection:** The protocol supports session resumption. The client must include the `session_id` in the `init` message to attempt resumption of the existing Gemini Live context.

## 2. Message Types

### Downlink (Server -> Client)
| Type | Data | Description |
| :--- | :--- | :--- |
| `init_ack` | `{"voice_state", "capabilities", "session_id", "model"}` | Handshake acknowledgment. |
| `connected` | `{}` | Live session established. |
| `state_change` | `{"state": "listening|thinking|speaking|..."}` | Synchronizes the mobile UI Orb/Waveform with the backend FSM. |
| `audio_chunk` | `Binary (PCM 16-bit 24kHz)` | Realtime audio response from the AI. |
| `transcription` | `{"user": "...", "model": "...", "final": bool}` | Transcription fragments (final) and partials. |
| `tool_call` / `tool_result` | `{"name": "...", "args": {...}, "status": "started|done"}` | Notification that the AI is executing a tool, then its result. |
| `turn_complete` | `{}` | A spoken/text turn fully finished. |
| `model_changed` | `{"model": "..."}` | Confirmation after a `model_request`. |
| `terminate_ack` | `{"reason": "..."}` | Acknowledgment of a client `terminate`. |
| `error` | `{"code": "...", "message": "..."}` | Protocol or backend error notifications. |

### Uplink (Client -> Server)
| Type | Data | Description |
| :--- | :--- | :--- |
| `audio_stream` | `Binary (PCM 16-bit 16kHz)` | Raw microphone stream from the mobile device. |
| `vision_frame` | `Binary (JPEG/WebP/PNG)` | Camera frame for visual understanding (sent @ 1-2 FPS). |
| `interrupt` | `{"type": "interrupt"}` | Triggered by user speech or manual tap to stop AI playback. |
| `model_request` | `{"model": "..."}` | Request to switch the underlying Gemini model. |
| `ping` | `{"type": "ping"}` | Keep-alive; answered with `{"type": "pong"}`. |
| `terminate` | `{"type": "terminate", "reason": "..."}` | Graceful shutdown of the session. |

## 3. Binary Uplink Discriminator

Uplink binary frames are ambiguous (audio vs vision), so every binary
frame from the client carries a **1-byte type prefix**:

| Prefix | Meaning |
| :--- | :--- |
| `0x00` | PCM 16-bit mono mic audio, 16,000 Hz |
| `0x01` | Vision frame (JPEG/WebP/PNG) |

Downlink binary frames are unambiguous (always AI audio) and need no
prefix.

## 4. Media Specifications

### Audio Format
- **Uplink (Mic):** PCM 16-bit Mono, 16,000 Hz.
- **Downlink (Speaker):** PCM 16-bit Mono, 24,000 Hz (matching Gemini Live native output).
- **Packetization:** 20ms to 50ms chunks to balance latency and overhead.

### Vision Format
- **Format:** JPEG (quality 60-80) or WebP.
- **Resolution:** Max 720p (preferred 480p or 640x480 for latency).
- **Frequency:** 1.0 Hz to 2.0 Hz depending on network conditions.
- **Optimization:** Frames should only be sent when the AI is in a state capable of processing vision or when explicitly requested.

## 4. Error & Backpressure

### Backpressure Handling
- **Uplink:** If the server's processing queue (`mic_queue_maxsize`) is full, it may send a `backpressure` message. The client should temporarily drop non-critical vision frames.
- **Downlink:** If the client's playback buffer is overflowing, it should signal the server to pause the stream or adjust the bitrate.

### Reconnection Strategy
- Exponential backoff (starting at 1s, max 60s).
- Maximum of 5 consecutive failures before transitioning to a "Degraded/Offline" state in the UI.

## 5. Security
- All traffic MUST be over WSS (WebSocket Secure).
- Sensitive metadata (like location or file contents) sent during the session must be encrypted if the underlying transport is not trusted.

## 6. Server Health & Configuration
- **`GET /api/mobile/status`** returns `{"enabled", "model", "voice_name", "capabilities", "active_sessions"}` so the app can render a degraded/ready state before connecting.
- The mobile voice model defaults to `gemini-3.1-flash-live-preview` and can be overridden with the `VYREN_MOBILE_MODEL` environment variable.
- `GEMINI_API_KEY` must be set on the server; if it is absent, `start` emits `{"type": "error", "code": "no_api_key"}` so the app can surface it immediately.
- Implementation reference: `register_mobile_live(app, ctx)` in `runtime/mobile_live.py`, wired into both `runtime/web_server.py` (RuntimeManager path) and `server.py` (standalone).
