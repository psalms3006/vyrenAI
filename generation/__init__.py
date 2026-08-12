"""generation/ -- Unified Generation & Multimodal Creation Layer for VYREN.

Public surface:
  - GenerationRouter
  - provider adapters
  - job/artifact lifecycle helpers

Design rules:
  - Providers are isolated behind adapters.
  - The LLM/tool layer never imports a provider SDK directly.
  - All artifacts are stored under platform_paths.get_generated_dir().
  - Events are emitted through the existing event bus.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("vyren.generation")


class GenerationType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    MUSIC = "music"
    DOCUMENT = "document"
    PDF = "pdf"
    PRESENTATION = "presentation"
    SPREADSHEET = "spreadsheet"
    CHART = "chart"
    OCR = "ocr"
    ANALYSIS = "analysis"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class ProviderCapabilities:
    text_to_image: bool = False
    image_to_image: bool = False
    text_to_video: bool = False
    image_to_video: bool = False
    text_to_audio: bool = False
    text_to_music: bool = False
    audio_to_text: bool = False
    document_generation: bool = False
    pdf_generation: bool = False
    presentation_generation: bool = False
    spreadsheet_generation: bool = False
    image_analysis: bool = False
    ocr: bool = False
    video_analysis: bool = False
    upscaling: bool = False


@dataclass
class GenerationRequest:
    request_id: str
    generation_type: GenerationType
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    input_artifacts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Artifact:
    artifact_id: str
    type: GenerationType
    filename: str
    mime_type: str
    path: str
    size: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_job: str = ""
    provider: str = ""
    model: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationJob:
    id: str
    request: GenerationRequest
    status: JobStatus = JobStatus.QUEUED
    provider: str = ""
    model: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    completed_at: str | None = None
    progress: float = 0.0
    artifacts: list[Artifact] = field(default_factory=list)
    error: str | None = None
    cost: dict[str, Any] | None = None
