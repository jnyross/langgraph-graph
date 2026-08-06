"""State schema for the jurisdiction catalog graph."""

from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict

from .models import Candidate, CatalogDiff, Verification


class CatalogState(TypedDict):
    subject: str
    levels: list[str]
    regions: list[str]
    seed_path: str
    discover_extra: bool
    write_target: str
    promote: bool
    run_id: str
    candidates: list[Candidate]
    candidate: NotRequired[Candidate]
    verifications: Annotated[list[Verification], operator.add]
    validated: Annotated[list[Candidate], operator.add]
    rejected: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]
    diff: CatalogDiff | dict
    output_path: str
    error: NotRequired[str | None]
