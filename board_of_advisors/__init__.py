"""
board_of_advisors -- Board of Advisors subsystem for VYREN.

Tier 0: schema + research primitives (isolated per-seat calls)
Tier 1: board tool integration into VYREN registry
Tier 2: adversarial chair synthesis + citation gate
Tier 3: persistence + event bus integration + frontend routes

Design constraints honored:
- Consensus theater defense: each seat gets its own isolated model call
  containing exactly one dossier.
- Confident fabrication defense: citation gate requires numbered doctrine
  entries from the seat's own dossier; invalid citations are stripped
  server-side before any output is returned.
- Cost ceiling: per meeting, 1 router call + 1 per-seat draft + 1 chair
  call maximum.
"""
from __future__ import annotations

from board_of_advisors.schema import (
    BoardMeeting,
    BoardSeat,
    DoctrineEntry,
    SeatDossier,
)
from board_of_advisors.research import (
    _format_doctrine,
    adversarial_review,
    extract_citation_numbers,
    research_seat,
    stage1_doctrine_research,
    stage2_draft_advice,
    validate_citations,
)

__all__ = [
    "BoardMeeting",
    "BoardSeat",
    "DoctrineEntry",
    "SeatDossier",
    "_format_doctrine",
    "adversarial_review",
    "extract_citation_numbers",
    "research_seat",
    "stage1_doctrine_research",
    "stage2_draft_advice",
    "validate_citations",
]
