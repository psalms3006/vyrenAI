"""
runtime/mobile_live.py -- Mobile Realtime Protocol (MRP) endpoints.

Implements the VYREN Mobile Realtime Protocol (docs/mobile-realtime-protocol.md)
as a single reusable registration helper:

    register_mobile_live(app, ctx)

so both entry points wire the identical surface:
  - runtime/web_server.py  (full RuntimeManager path, rich context)
  - server.py              (standalone, minimal context from module globals)

Surface:
  - GET  /api/mobile/status      -- capability/model health for the app
  - WS   /ws/live/mobile         -- full-duplex audio/vision/control session

Binary uplink discriminator (1 byte prefix):
  - \\x00  = 16 kHz PCM mono mic audio (used to be int 0)
  - \\x01  = vision frame (JPEG/WebP/PNG)

Downlink is unambiguous: binary frames are always AI audio (PCM 24 kHz).
"""

import asyncio
import json
import logging
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from voice.mobile_session import (
    MobileSessionManager, default_mobile_model, DEFAULT_VOICE_NAME,
)

logger = logging.getLogger("vyren.mobile_live")

# Binary discriminator bytes (approved: \x00 audio, \x01 vision)
_PREFIX_AUDIO = b"\x00"
_PREFIX_VISION = b"\x01"

VISION_MIME_BY_SIGNATURE = (
    (b"\x89PNG", "image/png"),
    (b"\xFF\xD8", "image/jpeg"),
)


def _sniff_vision_mime(body: bytes) -> str:
    for signature, mime in VISION_MIME_BY_SIGNATURE:
        if body.startswith(signature):
            return mime
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def register_mobile_live(app: FastAPI, ctx: dict):
    """Register MRP endpoints on ``app`` for context ``ctx``.

    Safe to call multiple times; only the first registration per app is
    effective. ``ctx`` is accessed defensively with .get() so the minimal
    context built by server.py works as well as the RuntimeManager ctx.
    """
    if getattr(app.state, "mobile_live_registered", False):
        return
    app.state.mobile_live_registered = True
    app.state.vyren_ctx = ctx
    app.state.mobile_sessions = MobileSessionManager()

    @app.get("/api/mobile/status")
    async def mobile_status():
        try:
            active = len(app.state.mobile_sessions._sessions)
        except Exception:
            active = 0
        return {
            "enabled": bool(os.environ.get("GEMINI_API_KEY")),
            "model": default_mobile_model(),
            "voice_name": DEFAULT_VOICE_NAME,
            "capabilities": ["audio", "vision", "model_switch", "resumption"],
            "active_sessions": active,
        }

    @app.websocket("/ws/live/mobile")
    async def mobile_live(websocket: WebSocket):
        manager = app.state.mobile_sessions
        await websocket.accept()

        loop = asyncio.get_running_loop()
        session = None
        audio_task = None
        try:
            # ---- Handshake: first frame MUST be init -------------------
            first = await websocket.receive_text()
            try:
                init = json.loads(first)
            except Exception:
                await _send_json(websocket, {
                    "type": "error",
                    "code": "bad_init",
                    "message": "First frame must be a JSON init message.",
                })
                await websocket.close()
                return

            if init.get("type") != "init":
                await _send_json(websocket, {
                    "type": "error",
                    "code": "bad_init",
                    "message": "First frame must be {type: init}.",
                })
                await websocket.close()
                return

            client = str(init.get("client", "mobile"))
            version = str(init.get("version", "1.0"))
            session_id = str(init.get("session_id") or "").strip()

            session = manager.create(
                ctx, session_id=session_id, websocket=websocket, loop=loop,
            )
            session.attach(websocket, loop)

            requested_model = str(init.get("model") or "").strip()
            if requested_model:
                session._model = requested_model

            logger.info(
                "Mobile init: session=%s client=%s version=%s model=%s",
                session.session_id, client, version, session.model,
            )

            session._send_json({
                "type": "init_ack",
                "voice_state": session.voice_state,
                "capabilities": ["audio", "vision", "model_switch", "resumption"],
                "session_id": session.session_id,
                "model": session.model,
            })

            # Boot the engine and start streaming AI audio downlink.
            session.start()
            audio_task = asyncio.create_task(_stream_audio(session))

            # ---- Main receive loop --------------------------------
            while True:
                data = await websocket.receive()
                if data is None:
                    break
                data_type = data.get("type")
                if data_type == "websocket.disconnect":
                    break
                if data_type == "websocket.receive":
                    if "bytes" in data and data["bytes"]:
                        await _handle_binary(session, data["bytes"])
                    elif "text" in data and data["text"]:
                        handled = await _handle_text(session, data["text"])
                        if handled is False:  # terminate
                            break
        except WebSocketDisconnect:
            logger.info("Mobile websocket disconnected: session=%s",
                        session.session_id if session else "?")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception("Mobile live handler error")
            if session is not None:
                session._send_json({
                    "type": "error",
                    "code": "internal",
                    "message": str(exc),
                })
        finally:
            if audio_task is not None:
                audio_task.cancel()
                try:
                    await audio_task
                except Exception:
                    pass
            if session is not None:
                manager.remove(session.session_id)
                logger.info("Mobile session removed: %s", session.session_id)

    @app.on_event("shutdown")
    async def _close_mobile_sessions():
        try:
            app.state.mobile_sessions.close_all()
        except Exception:
            pass


async def _stream_audio(session):
    """Drain AI audio and route it through the session's writer queue."""
    try:
        async for chunk in session.iter_audio():
            session._send_bytes(chunk)
    except Exception:
        pass


async def _handle_binary(session, payload: bytes):
    if not payload:
        return
    prefix = payload[:1]
    body = payload[1:]
    if not body:
        return
    if prefix == _PREFIX_AUDIO:
        session.push_audio(body)
    elif prefix == _PREFIX_VISION:
        session.push_vision_frame(body, _sniff_vision_mime(body))


async def _handle_text(session, text: str):
    """Handle an uplink control message. Returns False to signal close."""
    try:
        msg = json.loads(text)
    except Exception:
        session._send_json({
            "type": "error",
            "code": "bad_json",
            "message": "Uplink frames must be valid JSON.",
        })
        return True

    mtype = msg.get("type")
    if mtype == "ping":
        session._send_json({"type": "pong"})
    elif mtype == "interrupt":
        session.interrupt()
    elif mtype == "model_request":
        model = str(msg.get("model") or "").strip()
        if not model:
            session._send_json({
                "type": "error",
                "code": "bad_model",
                "message": "model_request requires a 'model' field.",
            })
        else:
            session.set_model(model)
    elif mtype == "terminate":
        reason = str(msg.get("reason") or "")
        if reason:
            session._send_json({"type": "terminate_ack", "reason": reason})
            await session.flush_writer()
        return False
    else:
        session._send_json({
            "type": "error",
            "code": "unknown_message",
            "message": f"Unsupported message type: {mtype}",
        })
    return True


async def _send_json(websocket: WebSocket, msg: dict):
    try:
        await websocket.send_json(msg)
    except Exception:
        pass