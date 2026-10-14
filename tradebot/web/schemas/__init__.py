"""Pydantic response models for the JSON endpoints (the chart data contracts)."""

from __future__ import annotations

from .arena import (  # noqa: F401
    LeaderboardEntry,
    ArenaCurve,
    ArenaRunDetail,
    RunSummary,
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
from .season import (  # noqa: F401
    SeasonSummary,
    SeasonStanding,
    SeasonCurve,
    SeasonDetail,
)
from .trading import (  # noqa: F401
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
