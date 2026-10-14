import pytest

from tradebot.backtest import Backtester
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.risk import RiskConfig, RiskManager
from tradebot.strategies import SmaCrossover
from tradebot.walkforward import required_warmup, walk_forward


def _bt(**kw):
    return Backtester(SmaCrossover(10, 30),
                      RiskManager(RiskConfig(max_position_pct=0.95)),
                      initial_cash=10_000, slippage_bps=0.0, **kw)


def test_walk_forward_produces_contiguous_independent_folds():
    df = synthetic_ohlcv(periods=400, seed=7)
    wf = walk_forward(_bt(), df, folds=4)
    assert len(wf.folds) == 4
    assert sum(f.bars for f in wf.folds) == 400 - required_warmup(_bt())
    for prev, nxt in zip(wf.folds, wf.folds[1:]):
        assert prev.end < nxt.start                     # ordered, no overlap
    for f in wf.folds:
        assert -1.0 <= f.max_drawdown <= 0.0
    assert wf.worst_return <= wf.mean_return


def test_walk_forward_warmup_covers_the_whole_pipeline():
    from tradebot.allocation import InverseVolatility
    from tradebot.overlays import VolTargetOverlay
    from tradebot.selection import MomentumSelector

    bt = _bt(allocator=InverseVolatility(window=40),
             selector=MomentumSelector(lookback=60, skip=5, top_k=1),
             overlays=[VolTargetOverlay(target_vol=0.15, window=30)])
    # Selector needs the most history: 60 + 1 (+2 shift/fill).
    assert required_warmup(bt) == 63


def test_walk_forward_rejects_too_little_history():
    df = synthetic_ohlcv(periods=80, seed=1)
    with pytest.raises(ValueError, match="Not enough history"):
        walk_forward(_bt(), df, folds=10)
    with pytest.raises(ValueError, match="folds"):
        walk_forward(_bt(), df, folds=1)


def test_walk_forward_multi_symbol_with_portfolio_stack():
    from tradebot.allocation import EqualWeight
    from tradebot.selection import MomentumSelector

    data = {"A": synthetic_ohlcv(periods=300, seed=1),
            "B": synthetic_ohlcv(periods=300, seed=2)}
    bt = _bt(allocator=EqualWeight(),
             selector=MomentumSelector(lookback=40, skip=5, top_k=1))
    wf = walk_forward(bt, data, folds=3)
    assert len(wf.folds) == 3
    assert "fold" in wf.table() and "mean / worst" in wf.table()


def test_cli_backtest_walk_forward_offline(tmp_path, capsys):
    from tradebot.cli import main

    csv = tmp_path / "x.csv"
    synthetic_ohlcv(periods=300, seed=3).rename_axis("timestamp").to_csv(csv)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "mode: backtest\n"
        "symbols: [X]\n"
        "strategy: {name: sma_crossover, params: {fast: 10, slow: 30}}\n"
    )
    rc = main(["backtest", "--config", str(cfg), "--csv", str(csv),
               "--walk-forward", "3"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Walk-forward (3 folds" in out
    assert "folds > 0" in out
