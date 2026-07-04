"""A Scenario fixes the market environment every contestant competes in.

Same symbols, same data, same starting capital, same cost/risk model — only the
algorithms differ. Phase 1 supports `synthetic` (seeded, reproducible, offline)
and `csv` data sources; `alpaca` (pull + local cache) arrives in Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from ..data.synthetic import load_csv, synthetic_ohlcv, synthetic_regime_ohlcv
from ..risk import RiskConfig


@dataclass
class Scenario:
    name: str = "default"
    symbols: list[str] = field(default_factory=lambda: ["DEMO"])
    source: str = "synthetic"           # synthetic | csv | alpaca
    initial_cash: float = 10_000.0
    commission: float = 0.0
    slippage_bps: float = 1.0
    risk: RiskConfig = field(default_factory=lambda: RiskConfig(max_position_pct=0.95))
    # synthetic params
    periods: int = 500
    seed: int = 7
    drift: float = 0.0004
    volatility: float = 0.012
    # synthetic regime segments (override drift/volatility/periods when set):
    # [{periods: 250, drift: 0.0006, volatility: 0.008}, ...] — the price path
    # is continuous across segments, so crash/recovery scenarios are one series.
    regimes: list[dict] = field(default_factory=list)
    # per-symbol drift/volatility overrides for the plain synthetic source:
    # {AAA: {drift: 0.001}, ...} — gives the pool a cross-sectional spread so
    # selection has something real to find. Ignored when `regimes` is set.
    symbol_overrides: dict[str, dict] = field(default_factory=dict)
    # csv params: {symbol: path}
    csv_paths: dict[str, str] = field(default_factory=dict)
    # alpaca params (pulled once, then cached + replayed)
    timeframe: str = "1day"
    start: str | None = None
    end: str | None = None
    cache_dir: str = "data/cache"

    @classmethod
    def default(cls) -> "Scenario":
        return cls()

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Scenario":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        risk = RiskConfig(**(raw.pop("risk", {}) or {}))
        known = {
            "name", "symbols", "source", "initial_cash", "commission", "slippage_bps",
            "periods", "seed", "drift", "volatility", "regimes", "symbol_overrides",
            "csv_paths", "timeframe", "start", "end", "cache_dir",
        }
        kwargs = {k: v for k, v in raw.items() if k in known}
        return cls(risk=risk, **kwargs)

    def build_frames(self, fetcher=None) -> dict[str, pd.DataFrame]:
        """Materialise the OHLCV frames all contestants will trade.

        ``fetcher`` is only used by the 'alpaca' source; when omitted a default
        Alpaca-backed fetcher is built from environment credentials. Already-cached
        data is served without any fetch, so cached rounds run fully offline.
        """
        if self.source == "synthetic":
            if self.regimes:
                return {
                    sym: synthetic_regime_ohlcv(self.regimes, seed=self.seed + i)
                    for i, sym in enumerate(self.symbols)
                }
            frames = {}
            for i, sym in enumerate(self.symbols):
                ov = self.symbol_overrides.get(sym, {})
                frames[sym] = synthetic_ohlcv(
                    periods=self.periods, seed=self.seed + i,
                    drift=float(ov.get("drift", self.drift)),
                    volatility=float(ov.get("volatility", self.volatility)),
                )
            return frames
        if self.source == "csv":
            missing = [s for s in self.symbols if s not in self.csv_paths]
            if missing:
                raise ValueError(f"csv_paths missing entries for: {missing}")
            return {sym: load_csv(self.csv_paths[sym]) for sym in self.symbols}
        if self.source == "alpaca":
            from ..data.cache import BarCache, build_default_fetcher

            cache = BarCache(self.cache_dir)
            fetch = fetcher or build_default_fetcher()
            return {
                sym: cache.get(sym, self.timeframe, self.start, self.end, fetch)
                for sym in self.symbols
            }
        raise ValueError(f"Unknown scenario source: {self.source!r}")
