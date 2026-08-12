"""generation/providers.py -- Provider adapter interfaces for the generation layer."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from . import Artifact, GenerationRequest, GenerationType, JobStatus, ProviderCapabilities


class GenerationProvider(ABC):
    capabilities: ProviderCapabilities = ProviderCapabilities()

    def __init__(self, artifact_manager: ArtifactManager, job_manager: JobManager) -> None:
        self._artifact_manager = artifact_manager
        self._job_manager = job_manager

    @abstractmethod
    def submit(self, request: GenerationRequest) -> str:
        """Submit a generation request. Returns a job id."""

    @abstractmethod
    def status(self, job_id: str) -> JobStatus:
        """Return the current job status."""

    @abstractmethod
    def cancel(self, job_id: str) -> bool:
        """Cancel a running job when possible."""

    @abstractmethod
    def result(self, job_id: str) -> tuple[JobStatus, list[Artifact], str | None]:
        """Return final status, artifacts, and optional error."""
