"""Graph state for the Meta legal research pipeline.

List fan-in fields use ``Annotated[..., operator.add]`` so parallel Send workers
can append without clobbering siblings.
"""

from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict

from langgraph_graph.meta_legal.models import (
    CellError,
    LawRecord,
    LawRecordDraft,
    RejectedRecord,
    ResearchCell,
)


class ResearchState(TypedDict):
    """State that flows through every meta_legal node."""

    jurisdictions: list[str]
    domains: list[str]
    explicit_cells: NotRequired[list[dict[str, str]]]
    subject: str
    cells: list[ResearchCell]
    drafts: Annotated[list[LawRecordDraft], operator.add]
    accepted: Annotated[list[LawRecord], operator.add]
    rejected: Annotated[list[RejectedRecord], operator.add]
    cell_errors: Annotated[list[CellError], operator.add]
    dossier_path: str
    run_id: str
    error: NotRequired[str | None]
