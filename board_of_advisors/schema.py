"""
board_of_advisors/schema.py -- Data model for Board of Advisors.

Each seat has:
- id / name / role
- doctrine: list of numbered entries the seat may cite
- research: collected primary-source notes from stage 1
- draft_advice: per-seat draft from stage 2
- final_advice: post-adversarial-review advice
- citations: validated citation IDs from doctrine

A BoardMeeting carries the question, seat outputs, chair synthesis,
cost metadata, and verification results.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DoctrineEntry:
    id: str
    seat_id: str
    number: int
    title: str
    body: str
    source: str = ""
    source_url: str = ""
    added_at: str = field(default_factory=lambda: _now())


@dataclass
class SeatDossier:
    seat_id: str
    name: str
    role: str
    background: str = ""
    doctrine: list[DoctrineEntry] = field(default_factory=list)
    research_notes: list[str] = field(default_factory=list)
    draft_advice: str = ""
    final_advice: str = ""
    citations: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def doctrine_by_id(self) -> dict[str, DoctrineEntry]:
        return {e.id: e for e in self.doctrine}

    def doctrine_by_number(self) -> dict[int, DoctrineEntry]:
        return {e.number: e for e in self.dossier_doctrine()}

    def dossier_doctrine(self) -> list[DoctrineEntry]:
        return sorted(self.doctrine, key=lambda e: e.number)


@dataclass
class BoardSeat:
    seat_id: str
    name: str
    role: str
    perspective: str = ""
    model_override: str | None = None

    def to_dossier(self) -> SeatDossier:
        return SeatDossier(
            seat_id=self.seat_id,
            name=self.name,
            role=self.role,
            background=self.perspective,
        )


@dataclass
class BoardMeeting:
    meeting_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    question: str = ""
    seats: list[BoardSeat] = field(default_factory=list)
    dossiers: dict[str, SeatDossier] = field(default_factory=dict)
    chair_synthesis: str = ""
    raw_seat_outputs: dict[str, str] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _now())

    def seat_dossier(self, seat_id: str) -> SeatDossier | None:
        return self.dossiers.get(seat_id)


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
