"""generation/jobs.py -- Job and artifact lifecycle management."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platform_paths import get_generated_dir

from . import Artifact, GenerationJob, GenerationRequest, GenerationType, JobStatus
from .eventing import publish, ARTIFACT_CREATED, GENERATION_FAILED, GENERATION_STARTED

logger = logging.getLogger("vyren.generation.jobs")


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, GenerationJob] = {}
        self._lock = threading.Lock()

    def create(self, request: GenerationRequest, provider: str = "", model: str = "") -> GenerationJob:
        job = GenerationJob(id=request.request_id, request=request, provider=provider, model=model)
        with self._lock:
            self._jobs[job.id] = job
        publish(None, GENERATION_STARTED, self._safe_job_payload(job))
        return job

    def get(self, job_id: str) -> GenerationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.EXPIRED}:
            return False
        job.status = JobStatus.CANCELLED
        job.completed_at = _now_iso()
        publish(None, GENERATION_CANCELLED, self._safe_job_payload(job))
        return True

    def complete(self, job_id: str, artifacts: list[Artifact], cost: dict[str, Any] | None = None) -> GenerationJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return None
        job.status = JobStatus.COMPLETED
        job.artifacts = artifacts
        job.completed_at = _now_iso()
        job.cost = cost
        for artifact in artifacts:
            publish(None, ARTIFACT_CREATED, {
                "job_id": job.id,
                "artifact_id": artifact.artifact_id,
                "type": artifact.type.value,
                "path": artifact.path,
                "provider": artifact.provider,
                "model": artifact.model,
            })
        return job

    def fail(self, job_id: str, error: str, cost: dict[str, Any] | None = None) -> GenerationJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return None
        job.status = JobStatus.FAILED
        job.error = error
        job.completed_at = _now_iso()
        job.cost = cost
        publish(None, GENERATION_FAILED, self._safe_job_payload(job))
        return job

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return [self._job_summary(j) for j in jobs[: max(1, limit)]]

    def _safe_job_payload(self, job: GenerationJob) -> dict[str, Any]:
        generation_type = job.request.generation_type
        if hasattr(generation_type, "value"):
            generation_type = generation_type.value
        return {
            "job_id": job.id,
            "type": generation_type,
            "status": job.status.value,
            "provider": job.provider,
            "model": job.model,
            "created_at": job.created_at,
            "error": job.error,
        }

    def _job_summary(self, job) -> dict[str, Any]:
        generation_type = job.request.generation_type
        if hasattr(generation_type, "value"):
            generation_type = generation_type.value
        return {
            "id": job.id,
            "type": generation_type,
            "status": job.status.value,
            "provider": job.provider,
            "model": job.model,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "artifact_count": len(job.artifacts),
            "error": job.error,
        }


class ArtifactManager:
    def __init__(self) -> None:
        self._base_dir = get_generated_dir()
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts: dict[str, Artifact] = {}
        self._lock = threading.Lock()

    def save(self, job_id: str, generation_type: GenerationType, filename: str, data: bytes, provider: str = "", model: str = "", mime_type: str = "application/octet-stream") -> Artifact:
        subdir = self._base_dir / generation_type.value
        subdir.mkdir(parents=True, exist_ok=True)
        path = subdir / filename
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        artifact = Artifact(
            artifact_id=str(uuid.uuid4()),
            type=generation_type,
            filename=path.name,
            mime_type=mime_type,
            path=str(path),
            size=path.stat().st_size,
            source_job=job_id,
            provider=provider,
            model=model,
        )
        with self._lock:
            self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def get(self, artifact_id: str) -> Artifact | None:
        with self._lock:
            return self._artifacts.get(artifact_id)

    def list_artifacts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._artifacts.values())
        items.sort(key=lambda a: a.created_at, reverse=True)
        return [self._artifact_summary(a) for a in items[: max(1, limit)]]

    def _artifact_summary(self, artifact: Artifact) -> dict[str, Any]:
        return {
            "artifact_id": artifact.artifact_id,
            "type": artifact.type.value,
            "filename": artifact.filename,
            "mime_type": artifact.mime_type,
            "path": artifact.path,
            "size": artifact.size,
            "created_at": artifact.created_at,
            "provider": artifact.provider,
            "model": artifact.model,
            "source_job": artifact.source_job,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
