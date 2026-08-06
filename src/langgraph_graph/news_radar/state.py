"""Graph state for the news/radar intelligence pipeline."""

from __future__ import annotations

import operator
from typing import Annotated, Any, NotRequired, TypedDict

from langgraph_graph.news_radar.models import (
    CellError,
    RejectedSignal,
    SignalCluster,
    SignalDraft,
    SignalRecord,
    WatchCell,
)


class RadarState(TypedDict):
    """State that flows through every news_radar node."""

    # inputs
    jurisdictions: list[str]
    domains: list[str]
    subject: str
    lookback_days: int
    levels: list[str]
    dossier_run_id: NotRequired[str | None]
    previous_run_id: NotRequired[str | None]
    max_cells: NotRequired[int | None]
    include_rumors: bool

    # context
    known_laws: Annotated[list[dict[str, Any]], operator.add]
    catalog_version: NotRequired[str]
    catalog_jurisdictions: NotRequired[list[dict[str, Any]]]

    # plan + fan-in reducers
    cells: list[WatchCell]
    drafts: Annotated[list[SignalDraft], operator.add]
    accepted: Annotated[list[SignalRecord], operator.add]
    rejected: Annotated[list[RejectedSignal], operator.add]
    cell_errors: Annotated[list[CellError], operator.add]

    # post-fan-in
    clusters: list[SignalCluster]
    signals: list[SignalRecord]
    radar_path: str
    run_id: str
    error: NotRequired[str | None]
