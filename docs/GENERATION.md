# VYREN Unified Generation & Multimodal Creation Layer

## Overview

VYREN's generation layer provides a unified interface for creating artifacts across multiple modalities: documents, presentations, spreadsheets, charts, images, analysis, OCR, and more. The architecture is designed around provider adapters, a capability router, job/artifact lifecycle management, and security/cost controls.

## Architecture

```
User Request
    ↓
Generation Tool (`generate_artifact`, `get_generation_job`, etc.)
    ↓
Generation Router
    ↓
Provider Adapter (Gemini, Document, Video, Audio)
    ↓
Job Manager / Artifact Manager
    ↓
Artifact Storage (`generated/`)
    ↓
REST API / WebSocket Events
```

## Files

- `generation/__init__.py` - Data models: `GenerationRequest`, `GenerationJob`, `Artifact`, `JobStatus`, `GenerationType`, `ProviderCapabilities`
- `generation/router.py` - `GenerationRouter`: selects provider based on `GenerationType` and capabilities
- `generation/jobs.py` - `JobManager` and `ArtifactManager`: lifecycle, persistence, summaries
- `generation/providers.py` - `GenerationProvider` abstract base class
- `generation/adapters.py` - Concrete adapters: `GeminiGenerationAdapter`, `DocumentGenerationAdapter`, `VideoGenerationAdapter`, `AudioGenerationAdapter`
- `generation/security.py` - Security controls: path validation, filename sanitization, MIME checks, size limits, budget checks
- `generation/eventing.py` - Event emission for generation lifecycle
- `tools/generation_tools.py` - Tool surface exposed to VYREN agent
- `runtime/web_server.py` - REST endpoints and WebSocket commands

## Generation Types

| Kind | Router Target | Status |
|------|---------------|--------|
| `image` | `GeminiGenerationAdapter` | Available when image-generation quota/model permits |
| `analysis` | `GeminiGenerationAdapter` | Available |
| `ocr` | `GeminiGenerationAdapter` | Available |
| `document` | `DocumentGenerationAdapter` | Available |
| `pdf` | `DocumentGenerationAdapter` | Available |
| `presentation` | `DocumentGenerationAdapter` | Available |
| `chart` | `DocumentGenerationAdapter` | Available |
| `spreadsheet` | `DocumentGenerationAdapter` | Available |
| `video` | None | Explicitly unavailable |
| `audio` | None | Explicitly unavailable |
| `music` | None | Explicitly unavailable |

## Tools

| Tool | Description |
|------|-------------|
| `generate_artifact` | Unified generation tool. Pass `kind` and `parameters` JSON. |
| `get_generation_job` | Get status/artifacts for a job by ID. |
| `list_generation_jobs` | List recent generation jobs. |
| `cancel_generation_job` | Cancel an in-progress job. |
| `list_generated_artifacts` | List recent generated artifacts. |

### Example Tool Calls

```json
{
  "name": "generate_artifact",
  "args": {
    "kind": "document",
    "parameters": {
      "title": "VYREN Report",
      "body": "Executive summary..."
    }
  }
}
```

```json
{
  "name": "generate_artifact",
  "args": {
    "kind": "analysis",
    "parameters": {
      "file_path": "/path/to/image.png",
      "question": "Describe this screenshot."
    }
  }
}
```

## REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/generation/jobs` | GET | List recent jobs |
| `/api/generation/jobs/{job_id}` | GET | Get job details |
| `/api/generation/jobs/{job_id}/cancel` | POST | Cancel job |
| `/api/generation/artifacts` | GET | List recent artifacts |
| `/api/generation/artifacts/{artifact_id}/download` | POST | Download artifact |

## WebSocket

Send `/generation` in the chat WebSocket to get a summary of recent generation jobs and artifacts.

## Security

- **Path traversal protection**: `validate_artifact_path()` rejects `..` segments
- **Filename sanitization**: `_normalize_filename()` strips directory components and null bytes
- **Extension validation**: Image save paths must have `.png`, `.jpg`, `.jpeg`, or `.webp`
- **Size limits**: Generated files validated against 50MB limit; parameters validated against 4KB
- **Budget checks**: `check_budget()` enforces per-request and daily limits before provider calls
- **Credential isolation**: Provider API keys never exposed to the browser or frontend

## Cost Controls

Every generation request passes through `check_budget()` before execution. Configure limits via the `generation.budget` section in `config.yaml`:

```yaml
generation:
  budget:
    per_request_limit: 1.0
    daily_limit: 10.0
```

## Provider Setup

### Gemini Image/Analysis/OCR

Set `GEMINI_API_KEY` in `.env`. The `GeminiGenerationAdapter` routes to the configured image-capable Gemini model. If quota is exhausted, the job fails with the real provider error and VYREN surfaces it explicitly.

### Document Generation

No external API required. `DocumentGenerationAdapter` generates Markdown/CSV artifacts locally using built-in templates.

### Video/Audio/Music

Currently explicitly unavailable. To add support, implement a new adapter class in `generation/adapters.py` with the required capabilities and register it in `tools/generation_tools.py`.

## Storage

Artifacts are stored under VYREN's generated directory:

```
generated/
├── image/
├── analysis/
├── ocr/
├── document/
├── pdf/
├── presentation/
├── chart/
└── spreadsheet/
```

Each artifact is written atomically via a `.tmp` write-then-replace pattern to avoid partial files.

## Adding a New Provider

1. Create an adapter in `generation/adapters.py` subclassing `GenerationProvider`
2. Declare capabilities via `ProviderCapabilities`
3. Implement `submit()`, `status()`, `cancel()`, `result()`
4. Register the adapter in `tools/generation_tools.py` inside `_get_router()`
5. Add routing rules in `generation/router.py` if needed

## Testing

Run generation tests:

```bash
python -m pytest tests/test_generation_layer.py -q
```

Run all tests:

```bash
scripts/run_tests.sh
```

## Known Limitations

- Image generation depends on Gemini free-tier quota; quota exhaustion returns a `429 RESOURCE_EXHAUSTED` error from the provider
- Video, audio, and music generation are explicitly blocked until adapters are implemented
- Document generation produces Markdown/CSV outputs by default; DOCX/PDF/XLSX/PPTX conversion requires additional libraries (`python-docx`, `reportlab`, `openpyxl`, `python-pptx`) which are not currently installed
- PDF export via `export_format: "pdf"` is explicitly blocked with `NotImplementedError` until a PDF library is added
- Cost tracking is placeholder-level; actual provider pricing is marked `unknown` until integrated

## Next Steps

1. Add DOCX/PDF/XLSX/PPTX export libraries to `DocumentGenerationAdapter`
2. Implement `VideoGenerationAdapter` with a real video provider
3. Implement `AudioGenerationAdapter` with real audio/music providers
4. Add persistent budget tracking with daily usage store
5. Integrate generation events into the existing VYREN event bus for live UI updates
6. Add artifact reference support in conversation context for follow-up commands ("make it darker", "turn it into a video")
