"""tests/test_generation_layer.py -- Targeted tests for VYREN's unified generation layer."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

from generation import GenerationRequest, GenerationType
from generation.adapters import AudioGenerationAdapter, DocumentGenerationAdapter, GeminiGenerationAdapter, VideoGenerationAdapter
from generation.jobs import ArtifactManager, JobManager
from generation.router import GenerationRouter
from generation.security import GenerationSecurityError, check_budget, sanitize_parameters, validate_artifact_path, validate_generated_file


@pytest.fixture()
def managers(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    monkeypatch.setattr("generation.jobs.get_generated_dir", lambda: artifact_dir)
    am = ArtifactManager()
    jm = JobManager()
    return am, jm


@pytest.fixture()
def router(managers):
    am, jm = managers
    return GenerationRouter([
        GeminiGenerationAdapter(am, jm),
        DocumentGenerationAdapter(am, jm),
        VideoGenerationAdapter(am, jm),
        AudioGenerationAdapter(am, jm),
    ])


def test_router_routes_known_capabilities(router):
    cases = {
        "image": "GeminiGenerationAdapter",
        "analysis": "GeminiGenerationAdapter",
        "ocr": "GeminiGenerationAdapter",
        "document": "DocumentGenerationAdapter",
        "pdf": "DocumentGenerationAdapter",
        "presentation": "DocumentGenerationAdapter",
        "chart": "DocumentGenerationAdapter",
        "spreadsheet": "DocumentGenerationAdapter",
    }
    for kind, expected in cases.items():
        req = GenerationRequest(request_id="rt-" + kind, generation_type=GenerationType(kind), operation=kind, parameters={}, input_artifacts=[], metadata={})
        provider = router.route(req)
        assert type(provider).__name__ == expected


def test_router_returns_none_for_unavailable(router):
    for kind in ["video", "audio", "music"]:
        req = GenerationRequest(request_id="rt-" + kind, generation_type=GenerationType(kind), operation="text_to_" + kind, parameters={}, input_artifacts=[], metadata={})
        assert router.route(req) is None


def test_document_adapter_generates_document(managers):
    am, jm = managers
    adapter = DocumentGenerationAdapter(am, jm)
    req = GenerationRequest(request_id="doc-1", generation_type=GenerationType.DOCUMENT, operation="document", parameters={"title": "VYREN", "body": "Hello"}, input_artifacts=[], metadata={})
    job_id = adapter.submit(req)
    job = jm.get(job_id)
    assert job.status.value == "completed"
    assert len(job.artifacts) == 1
    assert job.artifacts[0].path.endswith(".md")


def test_document_adapter_generates_presentation(managers):
    am, jm = managers
    adapter = DocumentGenerationAdapter(am, jm)
    req = GenerationRequest(request_id="pres-1", generation_type=GenerationType.PRESENTATION, operation="presentation", parameters={"title": "Deck", "body": "Intro", "slides": ["Slide 2"]}, input_artifacts=[], metadata={})
    job_id = adapter.submit(req)
    job = jm.get(job_id)
    assert job.status.value == "completed"
    assert len(job.artifacts) == 1


def test_document_adapter_generates_spreadsheet(managers):
    am, jm = managers
    adapter = DocumentGenerationAdapter(am, jm)
    req = GenerationRequest(request_id="sheet-1", generation_type=GenerationType.SPREADSHEET, operation="spreadsheet", parameters={"header": ["a", "b"], "rows": [{"a": "1", "b": "2"}]}, input_artifacts=[], metadata={})
    job_id = adapter.submit(req)
    job = jm.get(job_id)
    assert job.status.value == "completed"
    assert job.artifacts[0].path.endswith(".csv")


def test_document_adapter_generates_chart(managers):
    am, jm = managers
    adapter = DocumentGenerationAdapter(am, jm)
    req = GenerationRequest(request_id="chart-1", generation_type=GenerationType.CHART, operation="chart", parameters={"title": "Chart", "body": "Summary"}, input_artifacts=[], metadata={})
    job_id = adapter.submit(req)
    job = jm.get(job_id)
    assert job.status.value == "completed"
    assert len(job.artifacts) == 1


def test_video_adapter_is_unavailable(managers):
    adapter = VideoGenerationAdapter(*managers)
    with pytest.raises(NotImplementedError):
        adapter.submit(GenerationRequest(request_id="vid-1", generation_type=GenerationType.VIDEO, operation="text_to_video", parameters={}, input_artifacts=[], metadata={}))


def test_audio_adapter_is_unavailable(managers):
    adapter = AudioGenerationAdapter(*managers)
    with pytest.raises(NotImplementedError):
        adapter.submit(GenerationRequest(request_id="aud-1", generation_type=GenerationType.AUDIO, operation="text_to_audio", parameters={}, input_artifacts=[], metadata={}))


def test_security_artifact_path_traversal():
    with pytest.raises(GenerationSecurityError):
        validate_artifact_path("C:/tmp/../../etc/passwd")


def test_security_filename_sanitization():
    validate_generated_file(b"")
    with pytest.raises(GenerationSecurityError):
        validate_generated_file(b"x" * (50 * 1024 * 1024 + 1))


def test_security_parameter_sanitization():
    assert sanitize_parameters({"title": "ok", "weird-key": "1"}) == {"title": "ok", "weird-key": "1"}
    with pytest.raises(GenerationSecurityError):
        sanitize_parameters({"a": "x" * 5000})


def test_budget_check_blocks_high_cost():
    with pytest.raises(GenerationSecurityError):
        check_budget("p", "m", estimated_cost=999.0, per_request_limit=1.0)


def test_gemini_adapter_image_analysis_path(managers, monkeypatch):
    am, jm = managers
    adapter = GeminiGenerationAdapter(am, jm)
    called = {}

    def fake_execute(name, args):
        called["name"] = name
        return "Image analysis result."

    monkeypatch.setattr("tools.create_registry", lambda: type("R", (), {"execute": staticmethod(fake_execute)})())
    req = GenerationRequest(request_id="ana-1", generation_type=GenerationType.ANALYSIS, operation="image_analysis", parameters={"file_path": "tests/fixtures/sample.txt", "question": "Describe"}, input_artifacts=[], metadata={})
    job_id = adapter.submit(req)
    job = jm.get(job_id)
    assert job.status.value == "completed"
    assert called["name"] == "analyze_image"
