"""Background job runner for browser-triggered backtests and dry-runs.

Jobs run on a small thread pool so the HTTP request returns immediately with a
job id; the client polls for completion. Each job produces a metrics summary and
an equity curve (for the chart). Everything runs offline on synthetic data, so
the dashboard needs no credentials to let you experiment.

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
VALID_KINDS = ("backtest", "dryrun")


@dataclass
class Job:
    id: str
    kind: str
    state: str = "pending"          # pending -> running -> done | error
    summary: dict | None = None
    equity: dict | None = None      # {"index": [...], "equity": [...]}
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
                summary, equity = _run_backtest(params)
            elif kind == "dryrun":
                summary, equity = _run_dryrun(params)
            else:
                raise ValueError(f"Unknown job kind: {kind!r}")
            self._update(job_id, state="done", summary=summary, equity=equity)
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


def _run_backtest(params: dict) -> tuple[dict, dict]:
    from ...backtest import Backtester
    from ...data.synthetic import synthetic_ohlcv
    from ...risk import RiskConfig, RiskManager
    from ...strategies import build_strategy

    strategy = build_strategy(params["strategy"], params.get("params") or {})
    df = synthetic_ohlcv(periods=_periods(params), seed=int(params.get("seed", 42)))
    bt = Backtester(strategy, RiskManager(RiskConfig(max_position_pct=0.95)),
                    initial_cash=float(params.get("initial_cash", 10_000)))
    result = bt.run(df, symbol="DEMO")
    return result.summary(), _equity_payload(result.equity_curve.index,
                                              result.equity_curve.to_numpy())


def _run_dryrun(params: dict) -> tuple[dict, dict]:
    from ...broker.dryrun import DryRunBroker
    from ...config import Settings
    from ...data.replay import ReplayData
    from ...data.synthetic import synthetic_ohlcv
    from ...engine import Engine
    from ...risk import RiskConfig, RiskManager
    from ...strategies import build_strategy

    cash = float(params.get("initial_cash", 10_000))
    settings = Settings(
        mode="paper", symbols=["DEMO"], initial_cash=cash, timeframe="1day",
        strategy_name=params["strategy"], strategy_params=params.get("params") or {},
        risk=RiskConfig(max_position_pct=0.95),
    )
    strategy = build_strategy(settings.strategy_name, settings.strategy_params)
    risk = RiskManager(settings.risk)
    df = synthetic_ohlcv(periods=_periods(params), seed=int(params.get("seed", 42)))
    data = ReplayData.from_single(df, "DEMO", warmup=strategy.required_history + 2)
    broker = DryRunBroker(data, timeframe="1day", initial_cash=cash, slippage_bps=1.0)
    engine = Engine(settings, broker, data, strategy, risk,
                    mode_label="dry_run", enforce_live_ack=False)

    index, equity = [], []
    while True:
        engine.rebalance()
        index.append(data.history("DEMO").index[-1])
        equity.append(broker.account().equity)
        if not data.has_next():
            break
        data.advance()

    return broker.summary(), _equity_payload(index, equity)
