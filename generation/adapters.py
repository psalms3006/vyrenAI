"""generation/adapters.py -- Concrete provider adapters for VYREN generation.

Each adapter implements a narrow provider capability set and returns
explicit unavailable errors when credentials/models are missing.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from . import Artifact, GenerationJob, GenerationRequest, GenerationType, JobStatus, ProviderCapabilities
from .jobs import ArtifactManager, JobManager
from .providers import GenerationProvider
from .router import GenerationRouter

logger = logging.getLogger("vyren.generation.adapters")


class GeminiGenerationAdapter(GenerationProvider):
    capabilities = ProviderCapabilities(
        text_to_image=True,
        image_analysis=True,
        ocr=True,
    )

    def __init__(self, artifact_manager: ArtifactManager, job_manager: JobManager) -> None:
        super().__init__(artifact_manager, job_manager)

    def submit(self, request: GenerationRequest) -> str:
        job = self._job_manager.create(request, provider="gemini", model="gemini-2.5-flash")
        try:
            if request.generation_type == GenerationType.IMAGE:
                artifacts = self._generate_image(job.id, request)
            elif request.generation_type == GenerationType.ANALYSIS:
                artifacts = self._analyze_media(job.id, request)
            elif request.generation_type == GenerationType.OCR:
                artifacts = self._run_ocr(job.id, request)
            else:
                raise NotImplementedError(f"Unsupported generation type: {request.generation_type}")
            self._job_manager.complete(job.id, artifacts, cost={"provider": "gemini", "model": job.model, "status": "unknown"})
        except Exception as exc:
            self._job_manager.fail(job.id, f"{type(exc).__name__}: {exc}", cost={"provider": "gemini", "model": job.model, "status": "unknown"})
        return job.id

    def status(self, job_id: str) -> JobStatus:
        job = self._job_manager.get(job_id)
        return job.status if job else JobStatus.FAILED

    def cancel(self, job_id: str) -> bool:
        return self._job_manager.cancel(job_id)

    def result(self, job_id: str) -> tuple[JobStatus, list[Artifact], str | None]:
        job = self._job_manager.get(job_id)
        if not job:
            return JobStatus.FAILED, [], "job not found"
        return job.status, job.artifacts, job.error

    def _generate_image(self, job_id: str, request: GenerationRequest) -> list[Artifact]:
        prompt = str(request.parameters.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Image generation requires a prompt.")
        save_path = str(request.parameters.get("save_path") or "")
        if save_path:
            from generation.security import validate_artifact_path, _normalize_filename, _validate_extension, GenerationSecurityError
            try:
                validated_path = validate_artifact_path(save_path)
                _normalize_filename(validated_path)
                _validate_extension(validated_path, {".png", ".jpg", ".jpeg", ".webp"})
            except GenerationSecurityError as exc:
                raise RuntimeError(f"Invalid save path: {exc}") from exc
        try:
            from tools import create_registry
            registry = create_registry()
            result_text = registry.execute("generate_image", {"prompt": prompt, "save_path": save_path})
        except Exception as exc:
            raise RuntimeError(f"generate_image tool execution failed: {type(exc).__name__}: {exc}") from exc
        if result_text.startswith("Image generated and saved to:"):
            path = result_path_from_result(result_text)
            filename = os.path.basename(path)
            mime_type = "image/png" if filename.endswith(".png") else "image/jpeg"
            from generation.security import validate_generated_file
            validate_generated_file(Path(path).read_bytes())
            return [self._artifact_manager.save(job_id, GenerationType.IMAGE, filename, Path(path).read_bytes(), provider="gemini", model="gemini-2.5-flash-image", mime_type=mime_type)]
        raise RuntimeError(result_text)

    def _analyze_media(self, job_id: str, request: GenerationRequest) -> list[Artifact]:
        file_path = str(request.parameters.get("file_path") or "").strip()
        question = str(request.parameters.get("question") or "Describe this image in detail.")
        if not file_path:
            raise ValueError("Image analysis requires a file_path.")
        from generation.security import validate_artifact_path
        validate_artifact_path(file_path)
        try:
            from tools import create_registry
            registry = create_registry()
            text = registry.execute("analyze_image", {"file_path": file_path, "question": question})
        except Exception as exc:
            raise RuntimeError(f"analyze_image tool execution failed: {type(exc).__name__}: {exc}") from exc
        summary = (text or "").encode("utf-8")
        from generation.security import validate_generated_file
        validate_generated_file(summary)
        filename = f"{request.request_id}_analysis.txt"
        return [self._artifact_manager.save(job_id, GenerationType.ANALYSIS, filename, summary, provider="gemini", model="gemini-2.5-flash", mime_type="text/plain")]

    def _run_ocr(self, job_id: str, request: GenerationRequest) -> list[Artifact]:
        file_path = str(request.parameters.get("file_path") or "").strip()
        backend = str(request.parameters.get("backend") or "auto")
        if not file_path:
            raise ValueError("OCR requires a file_path.")
        from generation.security import validate_artifact_path
        validate_artifact_path(file_path)
        try:
            from tools import create_registry
            registry = create_registry()
            result_json = registry.execute("ocr_image", {"file_path": file_path, "backend": backend})
        except Exception as exc:
            raise RuntimeError(f"ocr_image tool execution failed: {type(exc).__name__}: {exc}") from exc
        from generation.security import validate_generated_file
        validate_generated_file(result_json.encode("utf-8"))
        filename = f"{request.request_id}_ocr.json"
        return [self._artifact_manager.save(job_id, GenerationType.OCR, filename, result_json.encode("utf-8"), provider="gemini", model="local", mime_type="application/json")]


class DocumentGenerationAdapter(GenerationProvider):
    capabilities = ProviderCapabilities(
        document_generation=True,
        pdf_generation=True,
        presentation_generation=True,
        spreadsheet_generation=True,
    )

    def __init__(self, artifact_manager: ArtifactManager, job_manager: JobManager) -> None:
        super().__init__(artifact_manager, job_manager)

    def submit(self, request: GenerationRequest) -> str:
        job = self._job_manager.create(request, provider="local_document", model="builtin")
        try:
            if request.generation_type in {GenerationType.PDF, GenerationType.DOCUMENT}:
                artifacts = self._render_document(job.id, request)
            elif request.generation_type == GenerationType.CHART:
                artifacts = self._render_chart(job.id, request)
            elif request.generation_type == GenerationType.SPREADSHEET:
                artifacts = self._render_spreadsheet(job.id, request)
            elif request.generation_type == GenerationType.PRESENTATION:
                artifacts = self._render_presentation(job.id, request)
            else:
                raise NotImplementedError(f"Unsupported document generation type: {request.generation_type}")
            self._job_manager.complete(job.id, artifacts, cost={"provider": "local_document", "model": "builtin", "status": "unknown"})
        except Exception as exc:
            self._job_manager.fail(job.id, f"{type(exc).__name__}: {exc}", cost={"provider": "local_document", "model": "builtin", "status": "unknown"})
        return job.id

    def status(self, job_id: str) -> JobStatus:
        job = self._job_manager.get(job_id)
        return job.status if job else JobStatus.FAILED

    def cancel(self, job_id: str) -> bool:
        return self._job_manager.cancel(job_id)

    def result(self, job_id: str) -> tuple[JobStatus, list[Artifact], str | None]:
        job = self._job_manager.get(job_id)
        if not job:
            return JobStatus.FAILED, [], "job not found"
        return job.status, job.artifacts, job.error

    def _render_document(self, job_id: str, request: GenerationRequest) -> list[Artifact]:
        title = str(request.parameters.get("title") or request.request_id)
        body = str(request.parameters.get("body") or "")
        markdown = f"# {title}\n\n{body}\n"
        filename = f"{request.request_id}.md"
        content = markdown.encode("utf-8")
        from generation.security import validate_generated_file
        validate_generated_file(content)
        artifacts = [self._artifact_manager.save(job_id, GenerationType.DOCUMENT, filename, content, provider="local_document", model="builtin", mime_type="text/markdown")]
        export_format = str(request.parameters.get("export_format") or "").lower()
        if export_format == "pdf":
            artifacts.append(self._try_render_pdf(job_id, request.request_id, title, markdown))
        return artifacts

    def _try_render_pdf(self, job_id: str, request_id: str, title: str, markdown: str) -> Artifact:
        try:
            pdf_bytes = self._convert_markdown_to_pdf(title, markdown)
            return self._artifact_manager.save(job_id, GenerationType.PDF, f"{request_id}.pdf", pdf_bytes, provider="local_document", model="builtin", mime_type="application/pdf")
        except NotImplementedError:
            raise
        except Exception as exc:
            raise RuntimeError(f"PDF export failed: {type(exc).__name__}: {exc}") from exc

    def _render_spreadsheet(self, job_id: str, request: GenerationRequest) -> list[Artifact]:
        rows = request.parameters.get("rows") or []
        header = request.parameters.get("header") or []
        lines = []
        if header:
            lines.append(",".join(str(header_item) for header_item in header))
        for row in rows:
            if isinstance(row, dict):
                values = [str(row.get(str(header_item), "")) for header_item in header] if header else [str(v) for v in row.values()]
                lines.append(",".join(values))
            else:
                lines.append(",".join(str(v) for v in row))
        csv = "\n".join(lines)
        filename = f"{request.request_id}.csv"
        content = csv.encode("utf-8")
        from generation.security import validate_generated_file
        validate_generated_file(content)
        return [self._artifact_manager.save(job_id, GenerationType.SPREADSHEET, filename, content, provider="local_document", model="builtin", mime_type="text/csv")]

    def _render_chart(self, job_id: str, request: GenerationRequest) -> list[Artifact]:
        title = str(request.parameters.get("title") or request.request_id)
        body = str(request.parameters.get("body") or "")
        markdown = f"# {title}\n\n{body}\n\n```csv\nlabel,value\nA,10\nB,20\nC,30\n```\n"
        filename = f"{request.request_id}.md"
        content = markdown.encode("utf-8")
        from generation.security import validate_generated_file
        validate_generated_file(content)
        return [self._artifact_manager.save(job_id, GenerationType.CHART, filename, content, provider="local_document", model="builtin", mime_type="text/markdown")]

    def _render_presentation(self, job_id: str, request: GenerationRequest) -> list[Artifact]:
        title = str(request.parameters.get("title") or request.request_id)
        body = str(request.parameters.get("body") or "")
        lines = [
            f"# {title}",
            "",
            "## Slide 1",
            body or "Title slide.",
        ]
        if request.parameters.get("slides"):
            for idx, slide in enumerate(request.parameters["slides"], start=2):
                lines.append(f"## Slide {idx}")
                lines.append(str(slide))
                lines.append("")
        markdown = "\n".join(lines)
        filename = f"{request.request_id}.md"
        content = markdown.encode("utf-8")
        from generation.security import validate_generated_file
        validate_generated_file(content)
        return [self._artifact_manager.save(job_id, GenerationType.PRESENTATION, filename, content, provider="local_document", model="builtin", mime_type="text/markdown")]


class VideoGenerationAdapter(GenerationProvider):
    capabilities = ProviderCapabilities(
        text_to_video=False,
        image_to_video=False,
    )

    def __init__(self, artifact_manager: ArtifactManager, job_manager: JobManager) -> None:
        super().__init__(artifact_manager, job_manager)

    def submit(self, request: GenerationRequest) -> str:  # pragma: no cover - explicit unavailable path
        raise NotImplementedError("Video generation is not configured.")

    def status(self, job_id: str) -> JobStatus:  # pragma: no cover
        return JobStatus.FAILED

    def cancel(self, job_id: str) -> bool:  # pragma: no cover
        return False

    def result(self, job_id: str) -> tuple[JobStatus, list[Artifact], str | None]:  # pragma: no cover
        return JobStatus.FAILED, [], "VIDEO_GENERATION_UNAVAILABLE"


class AudioGenerationAdapter(GenerationProvider):
    capabilities = ProviderCapabilities(
        text_to_audio=False,
        text_to_music=False,
        audio_to_text=False,
    )

    def __init__(self, artifact_manager: ArtifactManager, job_manager: JobManager) -> None:
        super().__init__(artifact_manager, job_manager)

    def submit(self, request: GenerationRequest) -> str:  # pragma: no cover - explicit unavailable path
        raise NotImplementedError("Audio generation is not configured.")

    def status(self, job_id: str) -> JobStatus:  # pragma: no cover
        return JobStatus.FAILED

    def cancel(self, job_id: str) -> bool:  # pragma: no cover
        return False

    def result(self, job_id: str) -> tuple[JobStatus, list[Artifact], str | None]:  # pragma: no cover
        return JobStatus.FAILED, [], "AUDIO_GENERATION_UNAVAILABLE"


def result_path_from_result(result_text: str) -> str:
    for line in result_text.splitlines():
        if "saved to:" in line.lower():
            return line.split(":", 1)[1].strip()
    raise RuntimeError("Could not parse saved path from generation result.")
