"""
board_of_advisors/research.py -- Two-stage research for board seats.

Stage 1: doctrine research
- For each seat, collect numbered doctrine entries from primary sources.
- Output is a structured dossier: only facts with source attribution.

Stage 2: adversarial review
- Seat drafts advice grounded in its own doctrine.
- A separate review pass rejects unsupported claims and strips
  citations that do not map to the seat's own doctrine numbers.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from board_of_advisors.schema import (
    BoardMeeting,
    BoardSeat,
    DoctrineEntry,
    SeatDossier,
)

logger = logging.getLogger("vyren.board.research")

_CITATION_RE = re.compile(r"\[\u200b]?(?P<number>[0-9]+)[\u200b]?")
_DOCTRINE_HEADING_RE = re.compile(r"(?im)^\s*doctrine\s*$")
_MAX_ADVICE_CHARS = 12000


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _normalize_number(raw: str) -> int | None:
    try:
        return int(re.sub(r"[^0-9]", "", raw))
    except Exception:
        return None


def validate_citations(text: str, dossier: SeatDossier) -> tuple[str, list[str]]:
    """Strip invalid citations from seat output.

    Returns (cleaned_text, invalid_citation_tokens).
    Only doctrine numbers present in this seat's own dossier are valid.
    """
    valid_numbers = {str(e.number) for e in dossier.doctrine_by_number().values()}
    invalid: list[str] = []
    cleaned_parts: list[str] = []

    last_end = 0
    for m in _CITATION_RE.finditer(text):
        token = m.group("number")
        if token not in valid_numbers:
            invalid.append(token)
        else:
            cleaned_parts.append(text[last_end : m.start()])
            cleaned_parts.append(f"[{token}]")
            last_end = m.end()
    cleaned_parts.append(text[last_end:])
    return "".join(cleaned_parts), invalid


def extract_citation_numbers(text: str) -> list[int]:
    """Return cited doctrine numbers after cleaning."""
    nums = []
    for m in _CITATION_RE.finditer(text):
        n = _normalize_number(m.group("number"))
        if n is not None:
            nums.append(n)
    return nums


def _run_model_sync(
    prompt: str,
    seat_id: str,
    model_override: str | None = None,
) -> str:
    """Run a model turn synchronously using VYREN's provider.

    This function is intentionally isolated per seat to prevent
    consensus theater. No state is shared between seat calls.
    """
    try:
        from provider import run_turn
    except Exception as exc:
        raise RuntimeError(f"Provider unavailable for board seat {seat_id}: {exc}") from exc

    messages = [{"role": "user", "parts": [{"text": prompt}]}]
    result = run_turn(messages=messages, system_prompt="", tools=None)
    text = str(getattr(result, "text", "") or "")
    if not text:
        return f"[Board seat {seat_id} returned empty output.]"
    return text


def stage1_doctrine_research(
    seat: BoardSeat,
    question: str,
    *,
    model_override: str | None = None,
) -> SeatDossier:
    """Collect primary-source doctrine for one seat.

    Returns a SeatDossier with doctrine entries and research notes.
    """
    dossier = seat.to_dossier()
    prompt = (
        "You are researching doctrine for an advisor seat.\n"
        f"Seat: {seat.name} ({seat.role})\n"
        f"Perspective: {seat.perspective}\n"
        f"Question under review: {question}\n\n"
        "Collect up to 8 numbered doctrine entries from primary sources. "
        "Each entry must be:\n"
        "- specific\n"
        "- attributed to a source or source URL\n"
        "- relevant to the seat's role and this question\n\n"
        "Return JSON only:\n"
        '{"entries": [{"number": 1, "title": "...", "body": "...", '
        '"source": "...", "source_url": "..."}]}\n'
    )
    raw = _run_model_sync(prompt, seat.seat_id, model_override)
    parsed: dict[str, Any] = {}
    try:
        parsed = json.loads(raw)
    except Exception:
        logger.debug("Stage1 JSON parse failed for seat %s: %s", seat.seat_id, raw[:200])

    entries: list[DoctrineEntry] = []
    seen: set[str] = set()
    for item in parsed.get("entries", []) if isinstance(parsed, dict) else []:
        try:
            number = int(item.get("number", 0))
            title = str(item.get("title", "")).strip()
            body = str(item.get("body", "")).strip()
            source = str(item.get("source", "")).strip()
            source_url = str(item.get("source_url", "")).strip()
        except Exception:
            continue
        if not title and not body:
            continue
        key = f"{number}:{title.lower()}:{body.lower()}"
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            DoctrineEntry(
                id=f"{seat.seat_id}_d{number}",
                seat_id=seat.seat_id,
                number=max(1, number),
                title=title or f"Doctrine {number}",
                body=body,
                source=source,
                source_url=source_url,
                added_at=_now(),
            )
        )

    entries.sort(key=lambda e: e.number)
    dossier.doctrine = entries
    dossier.research_notes = [
        raw[:2000] if isinstance(raw, str) else json.dumps(parsed, ensure_ascii=False)[:2000]
    ]
    return dossier


def stage2_draft_advice(
    seat: BoardSeat,
    question: str,
    dossier: SeatDossier,
    *,
    model_override: str | None = None,
) -> str:
    """Draft seat advice using only its own dossier."""
    doctrine_block = _format_doctrine(dossier)
    prompt = (
        "You are one member of a board of advisors. "
        "You must speak ONLY from the doctrine provided below. "
        "Do not invent facts, precedents, or sources.\n\n"
        f"Seat: {seat.name}\nRole: {seat.role}\n"
        f"Perspective: {seat.perspective}\n\n"
        f"QUESTION:\n{question}\n\n"
        "YOUR DOCTRINE:\n"
        f"{doctrine_block}\n\n"
        "Advice:\n"
        "- State your position clearly.\n"
        "- Cite only [N] using the doctrine numbers above.\n"
        "- If the doctrine is insufficient, say so explicitly.\n"
    )
    return _run_model_sync(prompt, seat.seat_id, model_override)


def adversarial_review(
    seat: BoardSeat,
    question: str,
    dossier: SeatDossier,
    draft: str,
    *,
    model_override: str | None = None,
) -> tuple[str, list[str]]:
    """Run adversarial review on a seat's draft advice.

    Returns (cleaned_advice, invalid_citations).
    Strips unsupported claims and invalid citations.
    """
    doctrine_block = _format_doctrine(dossier)
    review_prompt = (
        "You are an adversarial reviewer for one advisor seat.\n"
        "Your job is to strip unsupported claims and invalid citations.\n\n"
        f"Seat: {seat.name}\nRole: {seat.role}\n\n"
        f"QUESTION:\n{question}\n\n"
        "DOCTRINE:\n"
        f"{doctrine_block}\n\n"
        f"DRAFT ADVICE:\n{draft}\n\n"
        "Return JSON only:\n"
        '{"cleaned_advice": "...", "removed_claims": ["..."], '
        '"invalid_citations": ["N"]}\n'
    )
    raw = _run_model_sync(review_prompt, f"{seat.seat_id}_review", model_override)
    cleaned = draft
    invalid_citations: list[str] = []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            cleaned = str(parsed.get("cleaned_advice", draft)).strip() or draft
            invalid_citations = [str(x) for x in parsed.get("invalid_citations", [])]
    except Exception:
        logger.debug("Review JSON parse failed for seat %s: %s", seat.seat_id, raw[:200])

    if len(cleaned) > _MAX_ADVICE_CHARS:
        cleaned = cleaned[:_MAX_ADVICE_CHARS] + "…"

    return cleaned, invalid_citations


def research_seat(
    *,
    seat: BoardSeat,
    question: str,
    model_override: str | None = None,
) -> tuple[SeatDossier, str, list[str]]:
    """Run both research stages for one isolated seat.

    Returns (dossier, final_advice, invalid_citations).
    """
    dossier = stage1_doctrine_research(seat, question, model_override=model_override)
    draft = stage2_draft_advice(seat, question, dossier, model_override=model_override)
    final_advice, invalid_citations = adversarial_review(
        seat, question, dossier, draft, model_override=model_override
    )
    final_advice, _ = validate_citations(final_advice, dossier)
    return dossier, final_advice, invalid_citations


def _format_doctrine(dossier: SeatDossier) -> str:
    lines = []
    for entry in dossier.dossier_doctrine():
        lines.append(f"[{entry.number}] {entry.title}")
        lines.append(entry.body)
        if entry.source:
            lines.append(f"Source: {entry.source}")
        if entry.source_url:
            lines.append(f"URL: {entry.source_url}")
        lines.append("")
    return "\n".join(lines) if lines else "(No doctrine collected for this seat.)"
