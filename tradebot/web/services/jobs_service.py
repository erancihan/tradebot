"""Background job runner for browser-triggered backtests and dry-runs.

Jobs run on a small thread pool so the HTTP request returns immediately with a
job id; the client polls for completion. Each job produces a metrics summary,
an equity curve (for the chart), and a provenance record saying what data it
ran on — so a synthetic result can never masquerade as a real one.

Two data sources. ``synthetic`` invents a seeded price path on an artificial
calendar (dates are labels, not the future). ``real`` replays bars from the
local cache **only** — the dashboard never fetches, so it stays credential-free
and read-only; an uncovered range is answered with the exact ``tradebot data
pull`` command instead of a network call.

State is in-process (a single dict guarded by a lock) — fine for a local,
single-user dashboard; a multi-process deployment would swap this for a shared
queue, which is why the registry is the only thing routes touch.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

# Guard rails so a form submission can't ask for something absurd.
MAX_PERIODS = 5000
MIN_REAL_BARS = 30                       # below this a "result" is pure noise
VALID_KINDS = ("backtest", "dryrun")
VALID_SOURCES = ("synthetic", "real")


def strategy_catalog() -> list[dict]:
    """The strategy registry as form specs: name + simple constructor params.

    Only int/float/bool/str defaults become form fields — anything richer (a
    meta strategy's roster, a derived ``None``) keeps its default and stays a
    config-file affair. ``bool`` is checked before ``int`` because it *is* an
    ``int`` in Python and would otherwise render as a number box.
    """
    import inspect

    from ...strategies import STRATEGIES

    specs: list[dict] = []
    for name in sorted(STRATEGIES):
        params: list[dict] = []
        for pname, p in inspect.signature(STRATEGIES[name].__init__).parameters.items():
            if pname == "self" or p.default is inspect.Parameter.empty:
                continue
            if isinstance(p.default, bool):
                kind = "bool"
            elif isinstance(p.default, int):
                kind = "int"
            elif isinstance(p.default, float):
                kind = "float"
            elif isinstance(p.default, str):
                kind = "str"
            else:
                continue
            params.append({"name": pname, "type": kind, "default": p.default})
        specs.append({"name": name, "params": params})
    return specs


@dataclass
class Job:
    id: str
    kind: str
    state: str = "pending"          # pending -> running -> done | error
    summary: dict | None = None
    equity: dict | None = None      # {"index": [...], "equity": [...]}
    provenance: dict | None = None  # what data this ran on — travels with the result
    error: str | None = None


class JobRegistry:
    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def submit(self, kind: str, params: dict) -> str:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job.id, kind, params)
        return job.id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)

    def _run(self, job_id: str, kind: str, params: dict) -> None:
        self._update(job_id, state="running")
        try:
            if kind == "backtest":
                summary, equity, provenance = _run_backtest(params)
            elif kind == "dryrun":
                summary, equity, provenance = _run_dryrun(params)
            else:
                raise ValueError(f"Unknown job kind: {kind!r}")
            self._update(job_id, state="done", summary=summary, equity=equity,
                         provenance=provenance)
        except Exception as exc:  # noqa: BLE001 - surface failures to the client
            self._update(job_id, state="error", error=f"{type(exc).__name__}: {exc}")


# --- job implementations (reuse the existing engine pieces) -------------------

def _periods(params: dict) -> int:
    return max(30, min(int(params.get("periods", 500)), MAX_PERIODS))


def _equity_payload(index, values) -> dict:
    return {
        "index": [ts.isoformat() for ts in index],
        "equity": [float(v) for v in values],
    }


def _pull_hint(symbol: str, timeframe: str, start, end) -> str:
    parts = [f"tradebot data pull --symbols {symbol}", f"--timeframe {timeframe}"]
    if start:
        parts.append(f"--start {start}")
    if end:
        parts.append(f"--end {end}")
    return " ".join(parts)


def _resolve_frame(params: dict) -> tuple:
    """The job's bars + the provenance record that must travel with them.

    ``real`` reads the local cache with ``fetcher=None`` — never the network.
    The refusal message carries the exact pull command because the fix belongs
    in the operator's terminal, not in the dashboard.
    """
    source = str(params.get("source") or "synthetic")
    if source == "synthetic":
        from ...data.synthetic import synthetic_ohlcv

        seed = int(params.get("seed", 42))
        df = synthetic_ohlcv(periods=_periods(params), seed=seed)
        return df, "DEMO", {
            "source": "synthetic", "symbol": "DEMO", "seed": seed,
            "bars": int(len(df)),
            "start": df.index.min().isoformat(), "end": df.index.max().isoformat(),
            "note": "invented prices on an artificial calendar — dates are labels, not the future",
        }

    from ...data.cache import BarCache

    symbol = str(params.get("symbol") or "").upper()
    timeframe = str(params.get("timeframe") or "1day")
    start, end = params.get("start") or None, params.get("end") or None
    cache = BarCache(params.get("cache_dir") or "data/cache")
    try:
        df = cache.get(symbol, timeframe, start=start, end=end, fetcher=None)
    except RuntimeError:
        raise RuntimeError(
            f"no cached bars for {symbol} ({timeframe}) covering that range — the "
            f"dashboard never fetches. Pull once with: "
            f"{_pull_hint(symbol, timeframe, start, end)}"
        ) from None
    if len(df) < MIN_REAL_BARS:
        raise RuntimeError(
            f"only {len(df)} cached bars in that range — fewer than {MIN_REAL_BARS} "
            "is noise, not a result. Widen the range."
        )
    if len(df) > MAX_PERIODS:
        raise RuntimeError(
            f"{len(df)} bars in that range exceeds the {MAX_PERIODS}-bar job limit — "
            "narrow the range (silent truncation would misrepresent the window)."
        )
    return df, symbol, {
        "source": "real", "symbol": symbol, "timeframe": timeframe,
        "bars": int(len(df)),
        "start": df.index.min().isoformat(), "end": df.index.max().isoformat(),
        "note": "cached Alpaca bars — raw/unadjusted prices, simulated fills and costs",
    }


def _run_backtest(params: dict) -> tuple[dict, dict, dict]:
    from ...backtest import Backtester
    from ...risk import RiskConfig, RiskManager
    from ...strategies import build_strategy

    strategy = build_strategy(params["strategy"], params.get("params") or {})
    df, symbol, provenance = _resolve_frame(params)
    bt = Backtester(strategy, RiskManager(RiskConfig(max_position_pct=0.95)),
                    initial_cash=float(params.get("initial_cash", 10_000)))
    result = bt.run(df, symbol=symbol)
    return (result.summary(),
            _equity_payload(result.equity_curve.index, result.equity_curve.to_numpy()),
            provenance)


def _run_dryrun(params: dict) -> tuple[dict, dict, dict]:
    from ...broker.dryrun import DryRunBroker
    from ...config import Settings
    from ...data.replay import ReplayData
    from ...engine import Engine
    from ...risk import RiskConfig, RiskManager
    from ...strategies import build_strategy

    cash = float(params.get("initial_cash", 10_000))
    df, symbol, provenance = _resolve_frame(params)
    settings = Settings(
        mode="paper", symbols=[symbol], initial_cash=cash, timeframe="1day",
        strategy_name=params["strategy"], strategy_params=params.get("params") or {},
        risk=RiskConfig(max_position_pct=0.95),
    )
    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    risk = RiskManager(settings.risk)
    data = ReplayData.from_single(df, symbol, warmup=strategy.required_history + 2)
    broker = DryRunBroker(data, timeframe="1day", initial_cash=cash, slippage_bps=1.0)
    engine = Engine(settings, broker, data, strategy, risk,
                    mode_label="dry_run", enforce_live_ack=False)

    index, equity = [], []
    while True:
        engine.rebalance()
        index.append(data.history(symbol).index[-1])
        equity.append(broker.account().equity)
        if not data.has_next():
            break
        data.advance()

    return broker.summary(), _equity_payload(index, equity), provenance
