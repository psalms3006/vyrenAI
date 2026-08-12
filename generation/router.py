"""generation/router.py -- Selects the best available provider for a request."""
from __future__ import annotations

import logging
from typing import Any

from . import GenerationRequest, GenerationType, ProviderCapabilities
from .providers import GenerationProvider

logger = logging.getLogger("vyren.generation.router")


class GenerationRouter:
    def __init__(self, providers: list[GenerationProvider]) -> None:
        self._providers = providers
        self._capability_map = self._build_capability_map()

    def _build_capability_map(self) -> dict[GenerationType, tuple[str, ...]]:
        return {
            GenerationType.IMAGE: ("text_to_image", "image_to_image"),
            GenerationType.VIDEO: ("text_to_video", "image_to_video"),
            GenerationType.AUDIO: ("text_to_audio",),
            GenerationType.MUSIC: ("text_to_music",),
            GenerationType.DOCUMENT: ("document_generation",),
            GenerationType.PDF: ("pdf_generation",),
            GenerationType.PRESENTATION: ("presentation_generation",),
            GenerationType.SPREADSHEET: ("spreadsheet_generation",),
            GenerationType.CHART: ("document_generation",),
            GenerationType.OCR: ("ocr",),
            GenerationType.ANALYSIS: ("image_analysis", "video_analysis"),
            GenerationType.PRESENTATION: ("presentation_generation",),
        }

    def route(self, request: GenerationRequest) -> GenerationProvider | None:
        capability_names = self._capability_map.get(request.generation_type, ())
        candidates = []
        for provider in self._providers:
            supported = any(getattr(provider.capabilities, name, False) for name in capability_names)
            if not supported:
                continue
            candidates.append(provider)

        if not candidates:
            logger.info("No provider supports %s", request.generation_type)
            return None

        return candidates[0]

    def available_capabilities(self) -> dict[str, Any]:
        capabilities: dict[str, Any] = {}
        for provider in self._providers:
            capabilities[type(provider).__name__] = {
                k: v for k, v in provider.capabilities.__dict__.items() if not k.startswith("_")
            }
        return capabilities
