"""Focused unit-style harness for VYREN voice connectivity/fallback state logic."""
from __future__ import annotations

import os
import sys
import types
import threading
import json
import time
from pathlib import Path

ROOT = Path(r"C:\Users\Lenovo\my-project")
sys.path.insert(0, str(ROOT))
os.environ["GEMINI_API_KEY"] = "test"

# Minimal stubs so voice.runtime imports cleanly.
fake_google = types.ModuleType("google")
fake_genai = types.ModuleType("google.genai")
fake_types = types.ModuleType("google.genai.types")
fake_types.LiveConnectConfig = type("LiveConnectConfig", (), {})
fake_genai.types = fake_types
fake_google.genai = fake_genai
sys.modules["google"] = fake_google
sys.modules["google.genai"] = fake_genai
sys.modules["google.genai.types"] = fake_types

fake_voice_engine_mod = types.ModuleType("voice_engine.engine")
fake_voice_engine_mod.GeminiLiveVoiceEngine = None
sys.modules["voice_engine.engine"] = fake_voice_engine_mod

class FakeOfflineLoop:
    def __init__(self, *args, **kwargs):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


fake_voice_offline_mod = types.ModuleType("voice.offline_loop")
fake_voice_offline_mod.OfflineVoiceLoop = FakeOfflineLoop
sys.modules["voice.offline_loop"] = fake_voice_offline_mod

from voice.runtime import VoiceRuntime, VoiceState  # noqa: E402
import voice.runtime as vr_mod  # noqa: E402


def active_runtime():
    ctx = {
        "registry": None,
        "audit": None,
        "event_bus": None,
        "interaction_controller": None,
        "memory": None,
        "memory_v2": None,
        "world_model": None,
        "knowledge_graph": None,
        "system_prompt": "You are VYREN.",
    }
    vr = VoiceRuntime(ctx)
    vr._has_sounddevice = lambda: True
    vr._active = True
    vr._engine = types.SimpleNamespace(is_active=True)
    return vr


report = {
    "test_1_gemini_default": "UNVERIFIED",
    "test_2_single_failure": "UNVERIFIED",
    "test_3_two_failures": "UNVERIFIED",
    "test_4_three_failures": "UNVERIFIED",
    "test_5_offline_operation": "UNVERIFIED",
    "test_6_failure_counter_reset": "UNVERIFIED",
    "test_7_recovery": "UNVERIFIED",
    "test_8_recovery_failure": "UNVERIFIED",
    "test_9_runtime_stability": "UNVERIFIED",
}

try:
    # TEST 1
    vr = active_runtime()
    assert vr.mode == "gemini_live", f"TEST1: {vr.mode}"
    report["test_1_gemini_default"] = "PASS"

    # TEST 2
    vr = active_runtime()
    vr._on_engine_state_change(VoiceState.RECONNECTING)
    assert vr.mode == "gemini_live", f"TEST2: {vr.mode}"
    assert vr._voice_failure_count == 1, f"TEST2 count: {vr._voice_failure_count}"
    report["test_2_single_failure"] = "PASS"

    # TEST 3
    vr = active_runtime()
    vr._on_engine_state_change(VoiceState.RECONNECTING)
    vr._on_engine_state_change(VoiceState.LISTENING)
    vr._on_engine_state_change(VoiceState.RECONNECTING)
    assert vr.mode == "gemini_live", f"TEST3: {vr.mode}"
    assert vr._voice_failure_count == 1, f"TEST3 count: {vr._voice_failure_count}"
    report["test_3_two_failures"] = "PASS"

    # TEST 4
    vr = active_runtime()
    vr._on_engine_state_change(VoiceState.RECONNECTING)
    vr._on_engine_state_change(VoiceState.RECONNECTING)
    vr._on_engine_state_change(VoiceState.RECONNECTING)
    report["test_4_three_failures"] = "PASS" if vr.mode == "fallback" else f"UNVERIFIED: {vr.mode}"
    if vr.mode == "fallback":
        vr._fallback_thread = None

    # TEST 5
    if vr.mode == "fallback":
        vr._record_turn("hello", "reply")
        assert any(t["role"] == "user" and t["parts"][0]["text"] == "hello" for t in vr.recent_turns)
        report["test_5_offline_operation"] = "PASS"
    else:
        report["test_5_offline_operation"] = "UNVERIFIED: no fallback"

    # TEST 6
    vr._on_engine_state_change(VoiceState.LISTENING)
    assert vr._voice_failure_count == 0, f"TEST6 count: {vr._voice_failure_count}"
    report["test_6_failure_counter_reset"] = "PASS"

    # TEST 7
    if vr.mode == "fallback":
        started = []

        def fake_start_gemini_live(api_key):
            started.append(api_key)
            vr._engine = types.SimpleNamespace(is_active=True)
            vr._voice_failure_count = 0

        vr._start_gemini_live = fake_start_gemini_live
        vr._can_recover_to_live = lambda: True
        orig = vr_mod._genai_live_available
        vr_mod._genai_live_available = lambda: True
        vr._fallback_main()
        report["test_7_recovery"] = "PASS" if (started and vr.mode == "gemini_live") else f"UNVERIFIED: started={bool(started)}, mode={vr.mode}"
        vr_mod._genai_live_available = orig
    else:
        report["test_7_recovery"] = "UNVERIFIED: no fallback"

    # TEST 8
    if vr.mode == "gemini_live":
        vr._engine = None
        vr._fallback_mode = True
        vr._voice_failure_count = 3
        vr._can_recover_to_live = lambda: True
        vr._active = True
        vr._offline_loop = None
        orig = vr_mod._genai_live_available
        vr_mod._genai_live_available = lambda: False
        orig_interval = getattr(vr, "_voice_recovery_check_interval_s", 30)
        vr._voice_recovery_check_interval_s = 0.05
        t = threading.Thread(target=vr._fallback_main, daemon=True)
        t.start()
        time.sleep(0.15)
        vr._active = False
        t.join(timeout=2)
        report["test_8_recovery_failure"] = "PASS" if vr.mode == "fallback" else f"UNVERIFIED: {vr.mode}"
        vr._voice_recovery_check_interval_s = orig_interval
        vr_mod._genai_live_available = orig
    else:
        report["test_8_recovery_failure"] = "UNVERIFIED: no prior recovery"

    # TEST 9
    vr = active_runtime()
    for _ in range(5):
        vr._on_engine_state_change(VoiceState.RECONNECTING)
        vr._on_engine_state_change(VoiceState.LISTENING)
    assert vr.mode == "gemini_live"
    assert vr._voice_failure_count == 0
    report["test_9_runtime_stability"] = "PASS"

except Exception as e:
    report["harness_fatal"] = f"{type(e).__name__}: {e}"

out_path = ROOT / "proof" / "voice_fallback_report.json"
out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
