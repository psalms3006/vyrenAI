"""Tests for the mobile realtime bridge.

Covers:
  - shared prompt/config builders (behavior-preserving VoiceRuntime wrappers)
  - MobileSession lifecycle + model switching
  - MobileSessionManager resumption-handle carryover
  - register_mobile_live() REST + /ws/live/mobile MRP handshake
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from google.genai import types

from voice.runtime import (
    VoiceRuntime,
    build_voice_system_prompt,
    build_live_config,
    VOICE_TOOL_SUBSET,
)
import voice.mobile_session as mobile_session_mod
from voice.mobile_session import (
    MobileSession,
    MobileSessionManager,
    default_mobile_model,
)

from runtime.mobile_live import register_mobile_live


class _Mem:
    def build_context(self):
        return "Memory v1: placeholder fact."


class _Registry:
    def to_gemini_tools(self, names=None):
        return [{"function_declarations": [{"name": n} for n in (names or [])]}]


def base_ctx():
    return {
        "system_prompt": "You are VYREN, an autonomous AI operating system.",
        "memory": _Mem(),
        "registry": _Registry(),
    }


def _norm(s: str) -> str:
    return re.sub(r"Current date and time:.*", "<TS>", s)


# ---------------------------------------------------------------------------
# Shared builders
# ---------------------------------------------------------------------------


def test_voice_runtime_wrappers_match_shared_builders():
    ctx = base_ctx()
    vr = VoiceRuntime(ctx)

    assert _norm(vr._build_system_prompt()) == _norm(build_voice_system_prompt(ctx))

    vr_cfg = vr._build_live_config()
    direct_cfg = build_live_config(ctx)
    assert _norm(repr(vr_cfg)) == _norm(repr(direct_cfg))


def test_build_voice_system_prompt_contains_identity_and_rules():
    prompt = build_voice_system_prompt(base_ctx())
    assert "You are VYREN." in prompt or "You are VYREN, an autonomous" in prompt
    assert "## Identity (read this first" in prompt
    assert "Voice Conversation Rules" in prompt
    assert "Memory Context" in prompt
    assert len(prompt) <= 5000


def test_build_live_config_shape_and_resumption():
    ctx = base_ctx()
    cfg = build_live_config(ctx, resumption_handle="HANDLE-1", tools_override=["remember"])
    assert cfg.response_modalities == [types.Modality.AUDIO]
    assert cfg.session_resumption is not None
    assert cfg.session_resumption.handle == "HANDLE-1"
    # LiveConnectConfig coerces the dict tool declarations into Tool objects.
    declarations = cfg.tools[0].function_declarations
    assert [d.name for d in declarations] == ["remember"]
    assert cfg.system_instruction is not None

    no_tools = build_live_config({})
    assert getattr(no_tools, "tools", None) is None
    assert VOICE_TOOL_SUBSET  # stays non-empty


# ---------------------------------------------------------------------------
# MobileSession lifecycle
# ---------------------------------------------------------------------------


class FakeEngine:
    def __init__(self, config, callbacks):
        self.config = config
        self.callbacks = callbacks
        self._resumption_handle = None
        self.stopped = False
        self.interrupted = False
        self.audio = []
        self.vision = []

    @property
    def is_active(self):
        return True

    def run(self):
        return

    def stop(self):
        self.stopped = True

    def interrupt(self):
        self.interrupted = True

    def push_audio(self, data):
        self.audio.append(data)

    def push_vision_frame(self, data, mime_type="image/jpeg"):
        self.vision.append((data, mime_type))


def test_mobile_session_creates_engine_with_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("VYREN_MOBILE_MODEL", "gemini-2.5-flash")
    created = []
    monkeypatch.setattr(
        mobile_session_mod,
        "MobileVoiceEngine",
        lambda config, callbacks: created.append(config) or FakeEngine(config, callbacks),
    )

    session = MobileSession(base_ctx(), "sess-1")
    session.start()

    assert session.is_active
    assert len(created) == 1
    assert created[0].model == "gemini-2.5-flash"
    assert created[0].system_prompt
    assert created[0].voice_name == "Charon"
    session.stop()


def test_mobile_session_model_switch_rebuilds_engine(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    created = []
    monkeypatch.setattr(
        mobile_session_mod,
        "MobileVoiceEngine",
        lambda config, callbacks: created.append(config) or FakeEngine(config, callbacks),
    )

    session = MobileSession(base_ctx(), "sess-2")
    session.start()
    assert len(created) == 1
    old = session.engine
    assert old.stopped is False

    session.set_model("gemini-2.5-pro")
    assert session.model == "gemini-2.5-pro"
    assert len(created) == 2
    assert created[1].model == "gemini-2.5-pro"
    assert session.engine is not old
    assert old.stopped is True
    session.stop()


def test_mobile_session_no_api_key_sends_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    session = MobileSession(base_ctx(), "sess-3")
    session.start()
    assert session.engine is None
    # Not closed, just idle — the error frame is the client's signal.


def test_mobile_session_push_and_interrupt(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(
        mobile_session_mod, "MobileVoiceEngine",
        lambda config, callbacks: FakeEngine(config, callbacks),
    )
    session = MobileSession(base_ctx(), "sess-4")
    session.start()
    session.push_audio(b"\x00audio")
    session.push_vision_frame(b"JPEGDATA", "image/jpeg")
    session.interrupt()
    assert session.engine.audio == [b"\x00audio"]
    assert session.engine.vision == [(b"JPEGDATA", "image/jpeg")]
    assert session.engine.interrupted is True
    session.stop()


def test_manager_resumption_handle_carryover():
    mgr = MobileSessionManager()
    fake_engine = SimpleNamespace(_resumption_handle="RESUME-7")

    session = mgr.create(base_ctx(), session_id="sess-9")
    session._engine = fake_engine  # simulate an active engine
    mgr.remove("sess-9")

    session2 = mgr.create(base_ctx(), session_id="sess-9")
    assert session2._resumption_handle == "RESUME-7"
    session2.stop()


# ---------------------------------------------------------------------------
# register_mobile_live — REST + MRP WebSocket
# ---------------------------------------------------------------------------


def _build_test_app():
    app = FastAPI(title="VYREN-TEST")
    register_mobile_live(app, base_ctx())
    return app


def test_mobile_status_endpoint():
    client = TestClient(_build_test_app())
    resp = client.get("/api/mobile/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["capabilities"] == ["audio", "vision", "model_switch", "resumption"]
    assert "model" in body
    assert "voice_name" in body
    assert body["active_sessions"] == 0


def test_mobile_ws_handshake_and_cleanup(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(_build_test_app())

    with client.websocket_connect("/ws/live/mobile") as ws:
        ws.send_json({"type": "init", "client": "mobile", "version": "1.0"})
        ack = ws.receive_json()
        assert ack["type"] == "init_ack"
        assert ack["capabilities"] == ["audio", "vision", "model_switch", "resumption"]
        assert ack["session_id"]

        # No API key -> start() emits an informative error frame.
        assert ws.receive_json()["type"] == "error"

        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}

        ws.send_json({"type": "bad_type"})
        assert ws.receive_json()["type"] == "error"

        ws.send_json({"type": "terminate", "reason": "done"})
        assert ws.receive_json()["type"] == "terminate_ack"

    status = client.get("/api/mobile/status").json()
    assert status["active_sessions"] == 0


def test_mobile_ws_rejects_non_init_first_frame(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(_build_test_app())
    with client.websocket_connect("/ws/live/mobile") as ws:
        ws.send_json({"type": "ping"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "bad_init"
    status = client.get("/api/mobile/status").json()
    assert status["active_sessions"] == 0


def test_register_mobile_live_is_idempotent():
    app = FastAPI(title="VYREN-TEST2")
    register_mobile_live(app, base_ctx())
    register_mobile_live(app, base_ctx())
    client = TestClient(app)
    assert client.get("/api/mobile/status").status_code == 200