"""tools/generation_tools.py -- Tool surface for VYREN's unified generation layer."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from tools import ToolDef, ToolRegistry
from generation import GenerationRequest, GenerationType
from generation.adapters import (
    AudioGenerationAdapter,
    DocumentGenerationAdapter,
    GeminiGenerationAdapter,
    VideoGenerationAdapter,
)
from generation.jobs import ArtifactManager, JobManager
from generation.router import GenerationRouter

logger = logging.getLogger("vyren.tools.generation")

_generation_router: GenerationRouter | None = None
_job_manager = JobManager()
_artifact_manager = ArtifactManager()


def _get_budget_store():
    try:
        from generation.budget import GenerationBudgetStore
        return GenerationBudgetStore()
    except Exception:
        return None


def _get_router() -> GenerationRouter:
    global _generation_router
    if _generation_router is None:
        providers = [
            GeminiGenerationAdapter(_artifact_manager, _job_manager),
            DocumentGenerationAdapter(_artifact_manager, _job_manager),
            VideoGenerationAdapter(_artifact_manager, _job_manager),
            AudioGenerationAdapter(_artifact_manager, _job_manager),
        ]
        _generation_router = GenerationRouter(providers)
    return _generation_router


def _normalize_request(kind: str, parameters: dict[str, Any]) -> GenerationRequest:
    generation_type_map = {
        "image": GenerationType.IMAGE,
        "video": GenerationType.VIDEO,
        "audio": GenerationType.AUDIO,
        "music": GenerationType.MUSIC,
        "document": GenerationType.DOCUMENT,
        "pdf": GenerationType.PDF,
        "presentation": GenerationType.PRESENTATION,
        "spreadsheet": GenerationType.SPREADSHEET,
        "chart": GenerationType.CHART,
        "ocr": GenerationType.OCR,
        "analysis": GenerationType.ANALYSIS,
    }
    generation_type = generation_type_map.get(kind.lower(), GenerationType.ANALYSIS)
    return GenerationRequest(
        request_id=str(uuid.uuid4()),
        generation_type=generation_type,
        operation=str(parameters.get("operation") or kind.lower()),
        parameters=parameters,
    )


def register(registry: ToolRegistry) -> None:
    def generate_artifact(kind: str, parameters: str = "{}", store: bool = True) -> str:
        try:
            params = _parse_json_string(parameters)
        except ValueError as exc:
            return f"Error: parameters must be valid JSON: {exc}"
        try:
            from generation.security import sanitize_parameters, check_budget, GenerationSecurityError
            params = sanitize_parameters(params)
            store = _get_budget_store()
            check_budget(provider="unified", model="local", estimated_cost=0.0, store=store)
        except GenerationSecurityError as exc:
            return f"Error: {exc}"
        request = _normalize_request(kind, params)
        router = _get_router()
        provider = router.route(request)
        if provider is None:
            return f"Error: no generation provider is available for '{kind}'."
        try:
            job_id = provider.submit(request)
        except NotImplementedError as exc:
            return f"BLOCKED — {exc}"
        except Exception as exc:
            logger.exception("Generation failed")
            return f"Error: generation failed: {type(exc).__name__}: {exc}"
        job = _job_manager.get(job_id)
        if not job:
            return f"Error: generation job '{job_id}' could not be loaded."
        if job.status == JobStatus.COMPLETED:
            artifact_paths = [str(artifact.path) for artifact in job.artifacts]
            return f"Generation complete: {job_id}\nArtifacts:\n" + "\n".join(artifact_paths or ["(none)"])
        if job.status == JobStatus.FAILED:
            return f"Error: generation failed: {job.error or 'unknown failure'}"
        return f"Generation queued: {job_id}\nStatus: {job.status.value}\nPoll /api/generation/jobs/{job_id} for result."

    def get_generation_job(job_id: str) -> str:
        job = _job_manager.get(job_id)
        if not job:
            return f"No generation job found with id '{job_id}'."
        return _summarize_job(job)

    def list_generation_jobs(limit: int = 20) -> str:
        return "\n".join(_summarize_job_summary(summary) for summary in _job_manager.list_jobs(limit))

    def cancel_generation_job(job_id: str) -> str:
        success = _job_manager.cancel(job_id)
        return f"Cancelled: {success}" if success else f"Could not cancel job '{job_id}'."

    def list_generated_artifacts(limit: int = 20) -> str:
        return "\n".join(_summarize_artifact(artifact) for artifact in _artifact_manager.list_artifacts(limit))

    registry.register(ToolDef(
        name="generate_artifact",
        description=(
            "Generate an artifact through VYREN's unified generation layer. "
            "Supported kinds include: image, analysis, ocr, document, pdf, spreadsheet, video, audio, music. "
            "Pass provider-specific parameters as a JSON string."
        ),
        parameters={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "description": "Artifact kind: image, video, audio, music, document, pdf, spreadsheet, chart, ocr, analysis."},
                "parameters": {"type": "string", "description": "JSON object with generation parameters."},
                "store": {"type": "boolean", "description": "Persist the artifact to disk."},
            },
            "required": ["kind"],
        },
        handler=generate_artifact,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="get_generation_job",
        description="Get the current status and artifacts for a generation job.",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The generation job id."},
            },
            "required": ["job_id"],
        },
        handler=get_generation_job,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="list_generation_jobs",
        description="List recent generation jobs.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum jobs to return."},
            },
            "required": [],
        },
        handler=list_generation_jobs,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="cancel_generation_job",
        description="Cancel an in-progress generation job.",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The generation job id."},
            },
            "required": ["job_id"],
        },
        handler=cancel_generation_job,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="list_generated_artifacts",
        description="List generated artifacts.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum artifacts to return."},
            },
            "required": [],
        },
        handler=list_generated_artifacts,
        safety_level="safe",
    ))


def _parse_json_string(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


def _summarize_job(job) -> str:
    generation_type = job.request.generation_type
    if hasattr(generation_type, "value"):
        generation_type = generation_type.value
    lines = [
        f"Job: {job.id}",
        f"Status: {job.status.value}",
        f"Type: {generation_type}",
        f"Provider: {job.provider}",
        f"Model: {job.model}",
        f"Created: {job.created_at}",
        f"Artifacts: {len(job.artifacts)}",
    ]
    if job.error:
        lines.append(f"Error: {job.error}")
    if job.artifacts:
        lines.extend(f"- {artifact.path}" for artifact in job.artifacts)
    return "\n".join(lines)


def _summarize_job_summary(summary: dict[str, Any]) -> str:
    return (
        f"{summary.get('id')}: {summary.get('type')} | {summary.get('status')} | {summary.get('provider')} | {summary.get('created_at')}"
    )


def _summarize_artifact(artifact: dict[str, Any]) -> str:
    return f"{artifact.get('artifact_id')}: {artifact.get('type')} | {artifact.get('path')} | {artifact.get('size')} bytes"
