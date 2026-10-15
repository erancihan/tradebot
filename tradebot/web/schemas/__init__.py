"""Pydantic response models for the JSON endpoints (the chart data contracts)."""

from __future__ import annotations

from .arena import (  # noqa: F401
    LeaderboardEntry,
    ArenaCurve,
    ArenaRunDetail,
    RunSummary,
)
from .autopilot import (  # noqa: F401
    AutopilotCommand,
    AutopilotMode,
    AutopilotStateView,
    AutopilotView,
)
from .consortium import (  # noqa: F401
    ConsortiumMember,
    ConsortiumPosition,
    ConsortiumView,
)
from .jobs import (  # noqa: F401
    EquityCurve,
    StrategyParam,
    StrategySpec,
    CacheWindow,
    CacheEntry,
    JobRequest,
    JobView,
)
from .proposal import (  # noqa: F401
    ProposalLineView,
    ProposalView,
    ProposalEnvelope,
    HoldingRow,
    HoldingsView,
    DiscoverAdd,
    WatchlistChange,
    WatchlistView,
)
from .whatif import WhatIfRequest  # noqa: F401
from .season import (  # noqa: F401
    SeasonSummary,
    SeasonStanding,
    SeasonCurve,
    SeasonDetail,
)
from .trading import (  # noqa: F401
    BenchmarkPoint,
    EquityPoint,
    EquitySeries,
    OrderRow,
    Candle,
    CandleSeries,
    PositionView,
    AccountView,
    AllocationRow,
    AllocationsView,
)
