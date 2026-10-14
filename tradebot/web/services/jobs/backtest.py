"""Browser-triggered backtest job."""

from __future__ import annotations

from .frames import _equity_payload, _resolve_frame


def _run_backtest(params: dict) -> tuple[dict, dict, dict]:
    from ....backtest import Backtester
    from ....risk import RiskConfig, RiskManager
    from ....strategies import build_strategy

    strategy = build_strategy(params["strategy"], params.get("params") or {})
    df, symbol, provenance = _resolve_frame(params)
    bt = Backtester(strategy, RiskManager(RiskConfig(max_position_pct=0.95)),
                    initial_cash=float(params.get("initial_cash", 10_000)))
    result = bt.run(df, symbol=symbol)
    return (result.summary(),
            _equity_payload(result.equity_curve.index, result.equity_curve.to_numpy()),
            provenance)
