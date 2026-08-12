"""
tools/board_tools.py -- Board of Advisors tool surface for VYREN.

Exposes a small, opinionated set of tools so the agent can use the
``board_of_advisors`` subsystem without dropping into raw module internals:

  - ``convene_board``: run one board meeting from a natural-language question
    and optional seat/model overrides, then return the chair synthesis plus
    per-seat advice and citation validation results.
  - ``board_meeting``: retrieve a previously stored board meeting by id.
  - ``list_board_meetings``: list recent board meetings.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from tools import ToolDef, ToolRegistry
from board_of_advisors import BoardMeeting, BoardSeat, research_seat
from board_of_advisors.research import validate_citations

logger = logging.getLogger("vyren.tools.board")

_BOARD_DIR_NAME = "board_meetings"


def _board_dir() -> Path:
    try:
        from platform_paths import get_vyren_dir
        return get_vyren_dir() / _BOARD_DIR_NAME
    except Exception:
        return Path.home() / ".vyren" / _BOARD_DIR_NAME


def _load_meeting(meeting_id: str) -> dict[str, Any] | None:
    path = _board_dir() / f"{meeting_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Failed to load board meeting %s: %s", meeting_id, exc)
        return None


def _save_meeting(payload: dict[str, Any]) -> None:
    path = _board_dir() / f"{payload.get('meeting_id', 'unknown')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _default_seats() -> list[dict[str, Any]]:
    return [
        {
            "seat_id": "strategy",
            "name": "Strategy Advisor",
            "role": "Strategic Planning",
            "perspective": "Focus on long-term goals, risks, and opportunity costs.",
            "model_override": None,
        },
        {
            "seat_id": "engineering",
            "name": "Engineering Advisor",
            "role": "Technical Implementation",
            "perspective": "Focus on architecture, feasibility, maintainability, and tradeoffs.",
            "model_override": None,
        },
        {
            "seat_id": "safety",
            "name": "Safety Advisor",
            "role": "Risk and Safety",
            "perspective": "Focus on failure modes, misuse, security, and rollback safety.",
            "model_override": None,
        },
    ]


def register(registry: ToolRegistry) -> None:
    def convene_board(
        question: str,
        seats: str | None = None,
        model_overrides: str | None = None,
        store: bool = True,
    ) -> str:
        """
        Convene a board meeting for a complex question.

        seats/model_overrides are optional JSON strings.
        """
        if not question.strip():
            return "Error: question is empty."

        try:
            seat_defs = json.loads(seats) if seats else _default_seats()
        except Exception as exc:
            return f"Error: seats JSON is invalid: {exc}"

        try:
            overrides_raw = json.loads(model_overrides) if model_overrides else {}
        except Exception as exc:
            return f"Error: model_overrides JSON is invalid: {exc}"

        board_seats = []
        for idx, seat_def in enumerate(seat_defs, start=1):
            seat_id = str(seat_def.get("seat_id") or seat_def.get("name") or f"seat_{idx}")
            board_seats.append(BoardSeat(
                seat_id=seat_id,
                name=str(seat_def.get("name", seat_id)),
                role=str(seat_def.get("role", seat_id)),
                perspective=str(seat_def.get("perspective", "")),
                model_override=overrides_raw.get(seat_id) if isinstance(overrides_raw, dict) else None,
            ))

        meeting = BoardMeeting(question=question.strip(), seats=board_seats)
        meeting_id = meeting.meeting_id
        start = time.time()
        costs: dict[str, Any] = {"seat_calls": 0, "review_calls": 0}

        try:
            for seat in board_seats:
                dossier, advice, invalid_citations = research_seat(
                    seat=seat,
                    question=meeting.question,
                    model_override=seat.model_override,
                )
                meeting.dossiers[seat.seat_id] = dossier
                meeting.raw_seat_outputs[seat.seat_id] = advice
                meeting.verification[seat.seat_id] = {
                    "invalid_citations": invalid_citations,
                    "doctrine_entries": len(dossier.doctrine),
                }
                costs["seat_calls"] += 1
        except Exception as exc:
            logger.exception("Board meeting failed: %s", exc)
            meeting.verification["error"] = f"{type(exc).__name__}: {exc}"

        meeting.cost = {
            **costs,
            "duration_seconds": round(time.time() - start, 3),
        }

        chair_parts = []
        for seat in board_seats:
            advice = meeting.raw_seat_outputs.get(seat.seat_id, "")
            chair_parts.append(
                f"## {seat.name} ({seat.role})\n{advice}"
            )
        meeting.chair_synthesis = "\n\n".join(chair_parts)

        payload = {
            "meeting_id": meeting_id,
            "question": meeting.question,
            "seats": [
                {
                    "seat_id": s.seat_id,
                    "name": s.name,
                    "role": s.role,
                    "perspective": s.perspective,
                }
                for s in meeting.seats
            ],
            "chair_synthesis": meeting.chair_synthesis,
            "raw_seat_outputs": meeting.raw_seat_outputs,
            "verification": meeting.verification,
            "cost": meeting.cost,
            "created_at": meeting.created_at,
        }

        if store:
            try:
                _save_meeting(payload)
            except Exception as exc:
                logger.debug("Board meeting store skipped: %s", exc)

        text = (
            f"Board meeting complete: {meeting_id}\n"
            f"Question: {meeting.question}\n\n"
            f"{meeting.chair_synthesis}\n\n"
            f"Verification: {json.dumps(meeting.verification, ensure_ascii=False)}\n"
            f"Cost: {json.dumps(meeting.cost, ensure_ascii=False)}"
        )
        return text

    def board_meeting(meeting_id: str) -> str:
        data = _load_meeting(meeting_id)
        if not data:
            return f"No board meeting found with id '{meeting_id}'."
        return json.dumps(data, indent=2, ensure_ascii=False)

    def list_board_meetings(limit: int = 20) -> str:
        directory = _board_dir()
        if not directory.exists():
            return "No board meetings stored."
        entries = sorted(directory.glob("*.json"), key=os.path.getmtime, reverse=True)
        items = []
        for path in entries[: max(1, limit)]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items.append({
                    "meeting_id": data.get("meeting_id", path.stem),
                    "question": data.get("question", ""),
                    "created_at": data.get("created_at", ""),
                    "seat_count": len(data.get("seats", [])),
                })
            except Exception:
                continue
        return json.dumps(items, indent=2, ensure_ascii=False)

    registry.register(ToolDef(
        name="convene_board",
        description=(
            "Convene a board of advisors for a complex question. "
            "Returns chair synthesis, per-seat advice, citation validation, "
            "and cost metadata."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question or decision under review.",
                },
                "seats": {
                    "type": "string",
                    "description": "Optional JSON array of seat definitions.",
                },
                "model_overrides": {
                    "type": "string",
                    "description": "Optional JSON mapping seat_id to model override.",
                },
                "store": {
                    "type": "boolean",
                    "description": "Persist the meeting to disk.",
                },
            },
            "required": ["question"],
        },
        handler=convene_board,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="board_meeting",
        description="Retrieve a stored board meeting by id.",
        parameters={
            "type": "object",
            "properties": {
                "meeting_id": {
                    "type": "string",
                    "description": "The board meeting id.",
                },
            },
            "required": ["meeting_id"],
        },
        handler=board_meeting,
        safety_level="safe",
    ))

    registry.register(ToolDef(
        name="list_board_meetings",
        description="List recent stored board meetings.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum meetings to return.",
                },
            },
            "required": [],
        },
        handler=list_board_meetings,
        safety_level="safe",
    ))
