"""generation/security.py -- Security controls for the generation layer."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

MAX_ARTIFACT_FILENAME_LENGTH = 255
MAX_SAFE_PATH_LENGTH = 4096


class GenerationSecurityError(Exception):
    """Raised when a generation request fails security validation."""


def _normalize_filename(filename: str) -> str:
    filename = os.path.basename(filename)
    if not filename:
        raise GenerationSecurityError("Filename must not be empty.")
    if len(filename) > MAX_ARTIFACT_FILENAME_LENGTH:
        raise GenerationSecurityError("Filename exceeds maximum length.")
    if "\x00" in filename:
        raise GenerationSecurityError("Filename contains null bytes.")
    return filename


def _validate_extension(filename: str, allowed_extensions: set[str]) -> None:
    ext = Path(filename).suffix.lower()
    if not ext:
        raise GenerationSecurityError("Filename must have an extension.")
    if ext not in allowed_extensions:
        raise GenerationSecurityError(f"Extension '{ext}' is not allowed.")


def sanitize_parameters(parameters: dict[str, Any], max_size: int = 4096) -> dict[str, Any]:
    if not isinstance(parameters, dict):
        raise GenerationSecurityError("Parameters must be a dict.")

    size = len(str(parameters))
    if size > max_size:
        raise GenerationSecurityError("Parameters exceed maximum size.")

    sanitized: dict[str, Any] = {}
    for key, value in parameters.items():
        if not isinstance(key, str):
            raise GenerationSecurityError("Parameter keys must be strings.")
        sanitized_key = re.sub(r"[^a-zA-Z0-9_.-]", "_", key)
        if isinstance(value, str):
            if len(value) > 4096:
                raise GenerationSecurityError(f"Parameter '{sanitized_key}' exceeds maximum length.")
            if "\x00" in value:
                raise GenerationSecurityError(f"Parameter '{sanitized_key}' contains null bytes.")
        sanitized[sanitized_key] = value
    return sanitized


def validate_artifact_path(path: str) -> str:
    if not isinstance(path, str):
        raise GenerationSecurityError("Artifact path must be a string.")
    if len(path) > MAX_SAFE_PATH_LENGTH:
        raise GenerationSecurityError("Artifact path exceeds maximum length.")
    if "\x00" in path:
        raise GenerationSecurityError("Artifact path contains null bytes.")
    if ".." in path.split(os.sep) or ".." in path.split("/"):
        raise GenerationSecurityError("Artifact path must not traverse directories.")
    return path


def validate_generated_file(content: bytes, max_size: int = 50 * 1024 * 1024) -> None:
    if not isinstance(content, (bytes, bytearray)):
        raise GenerationSecurityError("Generated file content must be bytes.")
    if len(content) > max_size:
        raise GenerationSecurityError("Generated file exceeds maximum size.")


def check_budget(
    provider: str,
    model: str,
    estimated_cost: float | None,
    *,
    daily_limit: float = 10.0,
    per_request_limit: float = 1.0,
    store: Any | None = None,
) -> None:
    if estimated_cost is None:
        return
    if estimated_cost > per_request_limit:
        raise GenerationSecurityError(
            f"Requested generation cost {estimated_cost} exceeds per-request limit {per_request_limit}."
        )
    if store is None:
        return
    usage = store.daily_usage(provider, model)
    projected = usage + float(estimated_cost)
    if projected > daily_limit:
        raise GenerationSecurityError(
            f"Projected daily generation cost {projected} exceeds limit {daily_limit}."
        )
