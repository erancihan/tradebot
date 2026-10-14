"""Browser-triggered dry-run job: the live engine over a replay feed."""

from __future__ import annotations

from .frames import _equity_payload, _resolve_frame


def _run_dryrun(params: dict) -> tuple[dict, dict, dict]:
    from ....broker.dryrun import DryRunBroker
    from ....config import Settings
    from ....data.replay import ReplayData
    from ....engine import Engine
    from ....risk import RiskConfig, RiskManager
    from ....strategies import build_strategy

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
