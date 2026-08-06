"""
provider.py — The thin seam between VYREN's brain and the model.

This is the ONLY file that touches model SDKs directly.
Everything else calls run_turn() and never knows which provider is running.

Swapping providers means rewriting THIS FILE ONLY.

Supports:
  - Google Gemini (online, primary)
  - Ollama (offline fallback, auto-detected)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable

import httpx
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gemini-2.5-flash"
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1"

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - optional dependency
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]

    class _DummyClient:  # type: ignore[no-redef]
        pass

    class _DummyTypes:  # type: ignore[no-redef]
        GenerateContentConfig = dict
        Tool = object

    genai = _DummyClient()  # type: ignore[assignment]
    types = _DummyTypes()  # type: ignore[assignment]


def _get_model() -> str:
    return os.environ.get("VYREN_MODEL", DEFAULT_MODEL)


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY not set. "
            "Copy .env.example to .env and add your key from "
            "https://aistudio.google.com/apikey"
        )
    try:
        return genai.Client(api_key=api_key)
    except AttributeError as exc:
        raise EnvironmentError(
            "Gemini SDK unavailable or misconfigured. "
            "Install google-genai or set GEMINI_API_KEY."
        ) from exc


_gemini_client: genai.Client | None = None


def get_cached_client() -> genai.Client:
    """Return a reused Gemini client, creating it on first call."""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = _get_client()
    return _gemini_client


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FunctionCall:
    name: str
    args: dict
    id: str = ""


@dataclass
class TurnResult:
    text: str = ""
    function_calls: list[FunctionCall] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Ollama (offline fallback)
# ---------------------------------------------------------------------------

def _ollama_available() -> bool:
    """Check if Ollama is running locally."""
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def _ollama_run_turn(
    messages: list,
    system_prompt: str,
    on_chunk: Callable[[str], None] | None = None,
) -> TurnResult:
    """Run a turn using a local Ollama model. No tool calling in offline mode."""
    ollama_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        role = msg.get("role", "user")
        parts = msg.get("parts", [])
        for part in parts:
            if "text" in part:
                ollama_role = "user" if role == "user" else "assistant"
                ollama_messages.append({
                    "role": ollama_role,
                    "content": part["text"],
                })
            elif "function_response" in part:
                fr = part["function_response"]
                ollama_messages.append({
                    "role": "user",
                    "content": f"[Tool {fr['name']} returned: {fr['response'].get('result', '')}]",
                })
            elif "function_call" in part:
                fc = part["function_call"]
                ollama_messages.append({
                    "role": "assistant",
                    "content": f"[Calling tool: {fc['name']} with args {fc['args']}]",
                })

    model = os.environ.get("VYREN_OLLAMA_MODEL", OLLAMA_MODEL)
    text_parts = []

    try:
        with httpx.stream(
            "POST",
            f"{OLLAMA_BASE_URL}/api/chat",
            json={"model": model, "messages": ollama_messages, "stream": True},
            timeout=120,
        ) as resp:
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk_data = json.loads(line)
                    text = chunk_data.get("message", {}).get("content", "")
                    if text:
                        text_parts.append(text)
                        if on_chunk:
                            on_chunk(text)
                    if chunk_data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue

        return TurnResult(text="".join(text_parts))

    except Exception as e:
        return TurnResult(
            text=f"\n[Ollama error: {type(e).__name__} — {e}]\n"
            "Make sure Ollama is running: ollama serve\n"
        )


# ---------------------------------------------------------------------------
# Gemini (online, primary)
# ---------------------------------------------------------------------------

def _gemini_run_turn(
    messages: list,
    system_prompt: str,
    tools: list[types.Tool] | None = None,
    on_chunk: Callable[[str], None] | None = None,
) -> TurnResult:
    """Run a turn using Google Gemini."""
    client = get_cached_client()
    model_name = _get_model()

    config_kwargs = {
        "system_instruction": system_prompt,
        "temperature": float(os.environ.get("VYREN_TEMPERATURE", "0.8")),
        "max_output_tokens": int(os.environ.get("VYREN_MAX_TOKENS", "4096")),
    }
    if tools:
        config_kwargs["tools"] = tools

    config = types.GenerateContentConfig(**config_kwargs)

    response = client.models.generate_content_stream(
        model=model_name,
        contents=messages,
        config=config,
    )

    text_parts = []
    function_calls = []

    for chunk in response:
        if not chunk.candidates:
            continue
        for candidate in chunk.candidates:
            if not candidate.content or not candidate.content.parts:
                continue
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    text_parts.append(part.text)
                    if on_chunk:
                        on_chunk(part.text)
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    function_calls.append(
                        FunctionCall(
                            name=fc.name,
                            args=dict(fc.args) if fc.args else {},
                            id=fc.id if hasattr(fc, "id") else "",
                        )
                    )

    return TurnResult(text="".join(text_parts), function_calls=function_calls)


# ---------------------------------------------------------------------------
# Public interface — tries Gemini, falls back to Ollama
# ---------------------------------------------------------------------------

_run_ollama_last: bool = False  # Track if we're in offline mode


def run_turn(
    messages: list,
    system_prompt: str,
    tools: list[types.Tool] | None = None,
    on_chunk: Callable[[str], None] | None = None,
) -> TurnResult:
    """Send a conversation turn to the model.

    Tries Gemini first. If it fails with a network error and Ollama
    is available locally, falls back automatically. In offline mode,
    tool calling is disabled (local models have limited support).

    Never raises — errors are returned as text in the TurnResult.
    """
    global _run_ollama_last

    # If we previously fell back to Ollama, try it first this time
    # (avoids a slow timeout on every turn while offline)
    if _run_ollama_last:
        if _ollama_available():
            result = _ollama_run_turn(messages, system_prompt, on_chunk)
            _run_ollama_last = False
            return result
        return _ollama_run_turn(messages, system_prompt, on_chunk)

    # Try Gemini if available
    if genai is None or types is None:
        if _ollama_available():
            _run_ollama_last = True
            return _ollama_run_turn(messages, system_prompt, on_chunk)
        return TurnResult(text="[Gemini SDK unavailable and Ollama is not running.]")

    try:
        result = _gemini_run_turn(messages, system_prompt, tools, on_chunk)
        if "GEMINI_API_KEY" in result.text:
            if _ollama_available():
                _run_ollama_last = True
                return _ollama_run_turn(messages, system_prompt, on_chunk)
            return result
        return result

    except (httpx.ConnectError, httpx.TimeoutException, ConnectionError, OSError) as e:
        if _ollama_available():
            _run_ollama_last = True
            return _ollama_run_turn(messages, system_prompt, on_chunk)
        return TurnResult(
            text=(
                f"\n[No connection to Gemini and Ollama is not running.]\n"
                f"Error: {type(e).__name__} — {e}\n\n"
                "To fix:\n"
                "  1. Check your internet connection, or\n"
                "  2. Install Ollama (ollama.com) and run: ollama serve\n"
            )
        )

    except EnvironmentError as e:
        if _ollama_available():
            _run_ollama_last = True
            return _ollama_run_turn(messages, system_prompt, on_chunk)
        return TurnResult(text=str(e))

    except Exception as e:
        return TurnResult(
            text=f"\n[VYREN hit a problem: {type(e).__name__} — {e}]\n"
            "Try again in a moment.\n"
        )
