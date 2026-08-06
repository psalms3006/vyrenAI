"""
Smoke tests for VYREN v2 refactors.

Verifies the highest-priority architectural fixes using pytest.
Run: python -m pytest tests/test_refactors.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_post_confirmation_delete_file(tmp_path: Path):
    from post_confirmation import execute_post_confirmation

    target = tmp_path / "to_delete.txt"
    target.write_text("bye", encoding="utf-8")
    assert target.exists()

    result = execute_post_confirmation(
        "delete_file",
        {"file_path": str(target)},
        "DELETE_REQUESTED",
    )

    assert "Deleted:" in result
    assert not target.exists()


def test_post_confirmation_edit_file(tmp_path: Path):
    from post_confirmation import execute_post_confirmation

    target = tmp_path / "subdir" / "edit_me.txt"
    result = execute_post_confirmation(
        "edit_file",
        {"file_path": str(target), "content": "hello\n"},
        "EDIT_REQUESTED",
    )

    assert "File written:" in result
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_post_confirmation_run_python():
    from post_confirmation import execute_post_confirmation

    result = execute_post_confirmation(
        "run_python",
        {"code": "print(2+2)", "timeout": 10},
        "RUN_PYTHON_REQUESTED",
    )

    assert "4" in result


def test_post_confirmation_unknown_tool_returns_sentinel():
    from post_confirmation import execute_post_confirmation

    sentinel = "UNKNOWN_REQUESTED"
    result = execute_post_confirmation("unknown_tool", {}, sentinel)

    assert result == sentinel


def test_post_confirmation_delete_file_missing_path():
    from post_confirmation import execute_post_confirmation

    result = execute_post_confirmation(
        "delete_file", {"file_path": ""}, "DELETE_REQUESTED"
    )

    assert "Error:" in result


def test_post_confirmation_edit_file_missing_path():
    from post_confirmation import execute_post_confirmation

    result = execute_post_confirmation(
        "edit_file", {"file_path": "", "content": "x"}, "EDIT_REQUESTED"
    )

    assert "Error:" in result


def test_post_confirmation_run_python_missing_code():
    from post_confirmation import execute_post_confirmation

    result = execute_post_confirmation(
        "run_python", {"code": ""}, "RUN_PYTHON_REQUESTED"
    )

    assert "Error:" in result


def test_get_vyren_dir_custom(tmp_path: Path):
    import config as cfg

    old_config = cfg._config
    try:
        cfg._config = {"vyren": {"dir": str(tmp_path)}}
        assert cfg.get_vyren_dir() == tmp_path
    finally:
        cfg._config = old_config


def test_get_vyren_dir_default():
    import config as cfg

    old_config = cfg._config
    try:
        cfg._config = None
        assert cfg.get_vyren_dir() == Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "vyren"
    finally:
        cfg._config = old_config


def test_provider_cached_client_requires_key(monkeypatch: pytest.MonkeyPatch):
    from unittest import mock

    # The Google Gemini SDK is unavailable in this test environment,
    # so provide a lightweight fake package tree before importing provider.
    mock_genai = mock.MagicMock()
    mock_types = mock.MagicMock()
    mock_types.Tool = object
    mock_genai.types = mock_types

    fake_modules = {
        "google": mock.MagicMock(genai=mock_genai),
        "google.genai": mock_genai,
        "google.genai.types": mock_types,
        "google.genai.client": mock.MagicMock(),
    }
    with mock.patch.dict(sys.modules, fake_modules, clear=False):
        from provider import get_cached_client

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(EnvironmentError):
            get_cached_client()


def test_memory_v2_layers_and_decay(tmp_path: Path):
    from memory_v2 import MemoryManager, MemoryLayer

    mm = MemoryManager()
    mm.remember("city", "Lagos", layer=MemoryLayer.SEMANTIC, importance=0.9)
    mm.remember("greeting", "Hello", layer=MemoryLayer.WORKING)
    assert mm.recall("city") == "Lagos"
    assert mm.count() >= 1

    decay_stats = mm.apply_decay(half_life_days=0.0001, min_importance=0.01)
    assert "decayed" in decay_stats


def test_memory_v2_consolidate_and_dedupe(tmp_path: Path):
    from memory_v2 import MemoryManager, MemoryLayer

    mm = MemoryManager()
    mm.remember("alpha", "duplicate content", layer=MemoryLayer.SEMANTIC)
    mm.remember("beta", "duplicate content", layer=MemoryLayer.SEMANTIC)
    stats = mm.consolidate()
    assert "promoted_to_semantic" in stats or "summarized" in stats or "forgotten" in stats
    assert mm.count() >= 1


def test_learning_confidence_decay_and_application(tmp_path: Path):
    from learning import LessonStore, Learner

    store = LessonStore()
    learner = Learner(store)
    learner.learn_mistake("mistake", "fix", context="ctx")
    lessons = store.search("mistake")
    assert lessons
    lesson = lessons[0]
    baseline = store._effective_confidence(lesson)
    store.record_application(lesson.id, success=True)
    assert store._effective_confidence(store.all()[0]) >= baseline


def test_reflection_outcome_aware_and_search(tmp_path: Path):
    from reflection import ReflectionStore, Reflector

    store = ReflectionStore()
    reflector = Reflector(store)
    ref = reflector.reflect(task="test task", outcome="success", confidence_before=0.4)
    assert ref.outcome == "success"
    assert ref.confidence_after > ref.confidence_before

    refs = store.search("test")
    assert refs
    assert reflector.improvement_rate() > -1


def test_planner_records_learning(tmp_path: Path):
    class FakeLearner:
        def get_relevant_lessons(self, query, limit=5):
            return []

    class FakeCtx:
        learner = FakeLearner()

    from planner import Planner, PlanStore

    store = PlanStore()
    planner = Planner(store, ctx=FakeCtx())
    plan = planner.create_plan("test goal")
    step = planner.add_step(plan, "do work")
    planner.execute_step(plan, step)
    assert step.status.value == "completed"
    assert hasattr(step, "lessons_applied")


def test_identity_defaults_and_rename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import config as cfg
    import identity as ident

    monkeypatch.setattr(cfg, "_config", {"identity": {"assistant_name": "Atlas", "company": "Omniel", "aliases": []}}, raising=False)

    assert ident.get_assistant_name() == "Atlas"
    assert ident.get_wake_word() == "atlas"
    assert ident.get_product_name() == "Vyren"
    assert ident.get_company() == "Omniel"
    assert ident.build_identity_response("What is your name?") == "I'm Atlas."
    assert ident.build_identity_response("What is your real name?") == "My product name is Vyren, but you've chosen to call me Atlas."
    assert ident.build_identity_response("Who made you?") == "I was developed by Omniel."
    assert ident.build_identity_response("Who are you?") == "I'm Atlas."


def test_identity_persistence_and_reboot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import config as cfg
    import identity as ident

    cfg_path = tmp_path / "identity-config.yaml"
    cfg_path.write_text("identity:\n  assistant_name: Atlas\n  company: Omniel\n", encoding="utf-8")

    monkeypatch.setattr(cfg, "_find_config", lambda: cfg_path, raising=False)
    monkeypatch.setattr(cfg, "_config", None, raising=False)

    assert ident.get_assistant_name() == "Atlas"

    saved = ident.set_assistant_name("Echo")
    assert saved == "Echo"
    assert cfg.get("identity.assistant_name") == "Echo"

    # Simulate reboot by reloading config from disk
    cfg._config = None
    assert ident.get_assistant_name() == "Echo"
    assert ident.get_wake_word() == "echo"


def test_identity_memory_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import config as cfg
    import identity as ident
    from brain import Brain
    from memory_v2 import MemoryLayer

    monkeypatch.setattr(cfg, "_config", {"identity": {"assistant_name": "Atlas", "company": "Omniel", "aliases": []}}, raising=False)

    class FakeCtx:
        memory_v2 = None
        audit = None
        reflector = None
        learner = None
        event_bus = None
        registry = None
        watchdog = None
        knowledge_graph = None
        world_model = None
        scheduler = None
        heartbeat = None
        health = None
        service_registry = None
        voice_runtime = None
        server_port = 8420
        config = cfg

    class FakeMemoryV2:
        def __init__(self):
            self._store = {}
        def recall(self, key):
            return self._store.get(key)
        def remember(self, key, value, layer, importance):
            self._store[key] = value

    ctx = FakeCtx()
    ctx.memory_v2 = FakeMemoryV2()

    brain = Brain(ctx)
    brain._ensure_identity_memorized()

    assert ctx.memory_v2.recall("assistant_name") == "Atlas"
    assert ctx.memory_v2.recall("product_name") == "Vyren"
    assert ctx.memory_v2.recall("company") == "Omniel"

    # Calling again should not overwrite existing values
    brain._ensure_identity_memorized()
    assert ctx.memory_v2.recall("assistant_name") == "Atlas"


def test_identity_defaults_and_persistence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import config as cfg
    import identity as ident

    monkeypatch.setattr(cfg, "_config", {"identity": {"assistant_name": "Atlas", "company": "Omniel", "aliases": []}}, raising=False)
    assert ident.get_assistant_name() == "Atlas"
    assert ident.get_wake_word() == "atlas"
    assert ident.get_product_name() == "Vyren"
    assert ident.get_company() == "Omniel"
    assert ident.build_identity_response("What is your name?") == "I'm Atlas."
    assert ident.build_identity_response("What is your real name?") == "My product name is Vyren, but you've chosen to call me Atlas."
    assert ident.build_identity_response("Who made you?") == "I was developed by Omniel."
    assert ident.build_identity_response("Who are you?") == "I'm Atlas."

    isolated_cfg = tmp_path / "identity-config.yaml"
    isolated_cfg.write_text("identity:\n  assistant_name: Atlas\n  company: Omniel\n", encoding="utf-8")
    cfg._config_path = isolated_cfg
    cfg._config = None
    saved = ident.set_assistant_name("Echo")
    assert saved == "Echo"
    assert cfg.get("identity.assistant_name") == "Echo"


def test_identity_fallback_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import config as cfg
    import identity as ident

    monkeypatch.setattr(cfg, "_config", {"model": {"name": "test"}}, raising=False)
    assert ident.get_assistant_name() == "Vyren"
    assert ident.get_wake_word() == "vyren"
    assert ident.build_identity_response("Your name?") == "I'm Vyren."
