"""The advisor: proposals computed without trading, and their storage."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from tradebot.advisor import Proposal, ProposalLine, explain, propose
from tradebot.allocation import EqualWeight
from tradebot.broker import DryRunBroker
from tradebot.config import Settings
from tradebot.data import ReplayData
from tradebot.data.synthetic import synthetic_ohlcv
from tradebot.engine import Engine
from tradebot.models import Order, Side
from tradebot.risk import RiskConfig, RiskManager
from tradebot.selection import MomentumSelector
from tradebot.storage import Storage
from tradebot.strategies import build_strategy


def _line(symbol="SPY", action="buy", order_qty=10.0, **kw) -> ProposalLine:
    base = dict(symbol=symbol, action=action, target=1, current_qty=0.0,
                desired_qty=order_qty, order_qty=order_qty, price=100.0,
                notional=abs(order_qty) * 100.0, weight=0.5,
                reason="sma_crossover signals long; buy.")
    base.update(kw)
    return ProposalLine(**base)


def dummy_proposal(**kw) -> Proposal:
    base = dict(created_at=datetime(2025, 10, 15, 14, 30, tzinfo=timezone.utc),
                equity=10_000.0, cash=4_000.0,
                lines=[_line(), _line("QQQ", "hold", 0.0, weight=None)],
                provenance={"source": "cache", "account": "log",
                            "bars": {"SPY": 60, "QQQ": 60}, "end": "2026-10-14T04:00:00+00:00"})
    base.update(kw)
    return Proposal(**base)


# --- storage -------------------------------------------------------------------

def test_latest_proposal_round_trips_through_storage(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        assert st.latest_proposal("paper") is None
        st.record_proposal(dummy_proposal(equity=1.0), "paper")
        batch = st.record_proposal(dummy_proposal(), "paper")
        st.record_proposal(dummy_proposal(equity=2.0), "dry_run")

        got = st.latest_proposal("paper")
        assert got["id"] == batch
        assert got["equity"] == 10_000.0 and got["cash"] == 4_000.0
        assert got["provenance"]["bars"] == {"SPY": 60, "QQQ": 60}
        assert [ln["symbol"] for ln in got["lines"]] == ["SPY", "QQQ"]
        assert got["lines"][0]["order_qty"] == 10.0
        assert got["lines"][1]["weight"] is None
        assert {ln["status"] for ln in got["lines"]} == {"suggested"}
        assert st.latest_proposal()["mode"] == "dry_run"     # newest overall


def test_an_empty_proposal_is_still_a_dated_answer(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        st.record_proposal(dummy_proposal(lines=[]), "paper")
        got = st.latest_proposal("paper")
        assert got is not None and got["lines"] == []


def test_pending_lines_and_status_updates(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        st.record_proposal(dummy_proposal(), "paper", status="pending")
        pending = st.pending_lines("paper")
        assert len(pending) == 2
        st.set_line_status([pending[0]["id"]], "approved")
        assert [ln["symbol"] for ln in st.pending_lines("paper")] == ["QQQ"]


# --- propose: one code path with the engine ------------------------------------

POOL = ("A", "B", "C", "D")


def _pool_frames(periods=160):
    return {s: synthetic_ohlcv(periods=periods, drift=d, volatility=0.01, seed=i)
            for i, (s, d) in enumerate(zip(POOL, (0.002, 0.001, -0.001, 0.0005)))}


def _stack():
    risk = RiskManager(RiskConfig(max_position_pct=0.4, max_gross_exposure=0.9,
                                  rebalance_band_pct=0.02))
    return dict(strategy=build_strategy("sma_crossover", {"fast": 5, "slow": 20}),
                risk=risk, selector=MomentumSelector(lookback=30, skip=2, top_k=2),
                allocator=EqualWeight())


def _inputs(data, broker, symbols):
    frames = {s: data.history(s) for s in symbols}
    acct = broker.account()
    positions = {s: broker.position(s).qty for s in symbols}
    return frames, acct, positions


def test_propose_matches_engine_rebalance_deltas():
    """Lockstep: on the same inputs, the engine submits exactly the advisor's
    deltas, every pass, as the book trades in and out."""
    stack = _stack()
    data = ReplayData(_pool_frames(), warmup=40)
    broker = DryRunBroker(data, initial_cash=10_000, slippage_bps=0)
    settings = Settings(mode="paper", symbols=list(POOL), risk=stack["risk"].config)
    engine = Engine(settings, broker, data, mode_label="dry_run", enforce_live_ack=False,
                    **stack)
    traded = 0
    while True:
        frames, acct, positions = _inputs(data, broker, POOL)
        expected = propose(symbols=list(POOL), frames=frames, equity=acct.equity,
                           positions=positions, **stack)
        actions = engine.rebalance()
        assert {a.symbol: a.order_qty for a in actions} == {
            ln.symbol: ln.order_qty for ln in expected.lines if not ln.skipped}
        traded += sum(1 for a in actions if a.order_qty)
        if not data.has_next():
            break
        data.advance()
    assert traded > 5          # the comparison covered real trading, not just holds


class _Explodes:
    def __getattr__(self, name):
        raise AssertionError(f"propose touched {name!r}")


def test_propose_never_calls_a_broker_or_storage(monkeypatch):
    for cls, names in ((DryRunBroker, ("submit", "account", "position", "positions")),
                       (Storage, ("record_order", "record_weights", "record_proposal",
                                  "record_bars", "record_equity", "load_bars"))):
        for name in names:
            monkeypatch.setattr(cls, name, _Explodes.__getattr__)
    frames = {s: f.iloc[:120] for s, f in _pool_frames().items()}
    proposal = propose(symbols=list(POOL), frames=frames, equity=10_000.0,
                       positions={"A": 5.0}, provenance={"source": "test"}, **_stack())
    assert [ln.symbol for ln in proposal.lines] == list(POOL)
    assert proposal.provenance == {"source": "test"}
    assert proposal.lines[0].current_qty == 5.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -3.0])
def test_bad_prices_are_skipped_with_a_reason_and_never_traded(bad):
    good = synthetic_ohlcv(periods=60, seed=1)
    broken = good.copy()
    broken.iloc[-1, broken.columns.get_loc("close")] = bad
    proposal = propose(symbols=["OK", "BAD", "GONE"], frames={"OK": good, "BAD": broken},
                       equity=10_000.0, positions={"BAD": 3.0},
                       strategy=build_strategy("buy_and_hold"),
                       risk=RiskManager(RiskConfig()))
    lines = {ln.symbol: ln for ln in proposal.lines}
    assert not lines["OK"].skipped and lines["OK"].action == "buy"
    for sym in ("BAD", "GONE"):
        assert lines[sym].skipped and lines[sym].order_qty == 0
        assert lines[sym].action == "hold"
        assert lines[sym].reason.startswith("Skipped")
    assert "no valid price" in lines["BAD"].reason and lines["BAD"].current_qty == 3.0
    assert "no bars" in lines["GONE"].reason


def test_the_engine_skips_a_bad_price_symbol_like_the_advisor():
    good = synthetic_ohlcv(periods=60, seed=1)
    broken = good.copy()
    broken["close"] = math.nan
    data = ReplayData({"OK": good, "BAD": broken}, warmup=30)
    broker = DryRunBroker(data, initial_cash=10_000, slippage_bps=0)
    engine = Engine(Settings(mode="paper", symbols=["OK", "BAD"]), broker, data,
                    build_strategy("buy_and_hold"), RiskManager(RiskConfig()),
                    mode_label="dry_run", enforce_live_ack=False)
    actions = engine.rebalance()
    assert [a.symbol for a in actions] == ["OK"]
    assert broker.position("BAD").is_flat


def test_a_failing_signal_skips_only_that_symbol():
    class Fussy:
        name = "fussy"
        required_history = 1

        def latest_target(self, bars):
            if float(bars["close"].iloc[-1]) > 1_000:
                raise RuntimeError("boom")
            return 1

    cheap = pd.DataFrame({"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0,
                          "volume": 1.0}, index=pd.date_range("2024-01-01", periods=3))
    pricey = cheap * 1_000
    proposal = propose(symbols=["CHEAP", "PRICEY"], frames={"CHEAP": cheap,
                       "PRICEY": pricey}, equity=10_000.0, positions={},
                       strategy=Fussy(), risk=RiskManager(RiskConfig()))
    by = {ln.symbol: ln for ln in proposal.lines}
    assert by["CHEAP"].action == "buy" and by["CHEAP"].order_qty == 100.0
    assert by["PRICEY"].skipped and "RuntimeError" in by["PRICEY"].reason


# --- reasons -------------------------------------------------------------------


def test_explain_names_every_part():
    text = explain(strategy="sma_crossover", signal=1, action="buy", selected=True,
                   rank=(2, 5), weight=0.234, capped=True)
    assert text == ("sma_crossover signals long; rank 2 of 5, weight 23%, "
                    "capped by the risk limit; buy.")


def test_explain_without_a_selector_or_allocator_is_just_signal_and_action():
    assert explain(strategy="rsi_reversion", signal=0, action="sell") == (
        "rsi_reversion signals flat; sell.")


def test_explain_says_not_selected_and_within_band():
    assert explain(strategy="s", signal=1, action="sell", selected=False,
                   rank=(4, 5), weight=0.5) == "s signals long; not selected (rank 4 of 5); sell."
    assert explain(strategy="s", signal=-1, action="hold", banded=True) == (
        "s signals short; within band, hold.")


def _linear(start, step, periods=60):
    vals = [start + step * i for i in range(periods)]
    idx = pd.date_range("2024-01-01", periods=periods, freq="1D", tz="UTC")
    return pd.DataFrame({"open": vals, "high": vals, "low": vals, "close": vals,
                         "volume": 1000.0}, index=idx)


def test_propose_marks_non_members_as_sell_with_a_selector_reason():
    frames = {"UP": _linear(100, 1.0), "DOWN": _linear(200, -0.9)}
    proposal = propose(symbols=["UP", "DOWN"], frames=frames, equity=10_000.0,
                       positions={"DOWN": 7.0}, strategy=build_strategy("buy_and_hold"),
                       risk=RiskManager(RiskConfig(max_position_pct=0.5)),
                       selector=MomentumSelector(lookback=20, skip=2, top_k=1),
                       allocator=EqualWeight())
    by = {ln.symbol: ln for ln in proposal.lines}
    assert by["DOWN"].action == "sell" and by["DOWN"].order_qty == -7.0
    assert by["DOWN"].target == 0
    assert "not selected (rank 2 of 2)" in by["DOWN"].reason
    assert by["UP"].action == "buy" and "rank 1 of 2" in by["UP"].reason


def test_propose_reason_names_the_strategy_signal_and_the_cap():
    frames = {"A": _linear(100, 0.5), "B": _linear(50, 0.2)}
    proposal = propose(symbols=["A", "B"], frames=frames, equity=10_000.0, positions={},
                       strategy=build_strategy("buy_and_hold"),
                       risk=RiskManager(RiskConfig(max_position_pct=0.3)),
                       allocator=EqualWeight())
    for line in proposal.lines:
        assert line.reason.startswith("buy_and_hold signals long")
        assert "weight 50%" in line.reason                # what the allocator asked
        assert "capped by the risk limit" in line.reason  # what risk allowed
        assert line.notional == pytest.approx(line.order_qty * line.price)
        assert line.notional <= 0.3 * 10_000


def test_propose_reason_says_within_band_when_the_drift_is_small():
    frames = {"A": _linear(100, 0.0)}                     # price stays at 100
    proposal = propose(symbols=["A"], frames=frames, equity=10_000.0, positions={"A": 9.0},
                       strategy=build_strategy("buy_and_hold"),
                       risk=RiskManager(RiskConfig(max_position_pct=0.1,
                                                   rebalance_band_pct=0.05)))
    (line,) = proposal.lines
    assert line.desired_qty == 10.0 and line.order_qty == 0
    assert line.action == "hold" and line.reason.endswith("within the 5% no-trade band, hold.")


# --- the list is the mandate: held names off the list are closed -----------------

def _bh(symbols=("SPY",), **kw):
    frames = {s: _linear(100, 0.0) for s in symbols}
    return propose(symbols=list(symbols), frames=frames, equity=10_000.0,
                   strategy=build_strategy("buy_and_hold"),
                   risk=RiskManager(RiskConfig()), **kw)


def test_an_unlisted_long_gets_a_sell_to_flat_line_after_the_list():
    proposal = _bh(("SPY", "QQQ"), positions={"IWM": 5.0},
                   unlisted={"IWM": (5.0, 210.0)})
    assert [ln.symbol for ln in proposal.lines] == ["SPY", "QQQ", "IWM"]
    iwm = proposal.lines[-1]
    assert (iwm.action, iwm.target, iwm.desired_qty, iwm.order_qty) == ("sell", 0, 0.0, -5.0)
    assert iwm.price == 210.0 and iwm.notional == 1050.0 and not iwm.skipped
    assert iwm.reason == "not on your list: sell to flat"


def test_an_unlisted_short_gets_a_buy_to_flat_line():
    (_, line) = _bh(positions={}, unlisted={"TSLA": (-3.0, 50.0)}).lines
    assert (line.action, line.order_qty, line.desired_qty) == ("buy", 3.0, 0.0)
    assert line.reason == "not on your list: buy to flat"


def test_an_unlisted_holding_without_a_price_is_skipped_never_guessed():
    (_, line) = _bh(positions={}, unlisted={"IWM": (5.0, None)}).lines
    assert line.skipped and line.order_qty == 0 and line.action == "hold"
    assert line.current_qty == 5.0 and line.reason == "not on your list; no price to size it"


def test_unlisted_none_or_on_the_list_changes_nothing():
    plain = _bh(("SPY",), positions={"SPY": 2.0})
    same = _bh(("SPY",), positions={"SPY": 2.0}, unlisted={"SPY": (2.0, 100.0),
                                                           "FLAT": (0.0, 9.0)})
    assert [ln.to_dict() for ln in plain.lines] == [ln.to_dict() for ln in same.lines]


def test_a_one_share_drift_within_a_one_percent_band_holds_and_says_so():
    frames = {"SPY": _linear(500, 0.0)}
    risk = RiskManager(RiskConfig(max_position_pct=0.5, rebalance_band_pct=0.01))
    (line,) = propose(symbols=["SPY"], frames=frames, equity=100_000.0,
                      positions={"SPY": 101.0}, strategy=build_strategy("buy_and_hold"),
                      risk=risk).lines
    assert line.desired_qty == 100.0 and line.order_qty == 0 and line.action == "hold"
    assert "within the 1% no-trade band" in line.reason


def _held_iwm_engine(tmp_path):
    frames = {s: synthetic_ohlcv(periods=60, seed=i) for i, s in enumerate(("SPY", "QQQ", "IWM"))}
    data = ReplayData(frames, warmup=40)
    broker = DryRunBroker(data, initial_cash=10_000, slippage_bps=0)
    broker.submit(Order(symbol="IWM", qty=5, side=Side.BUY))
    engine = Engine(Settings(mode="paper", symbols=["SPY", "QQQ"]), broker, data,
                    build_strategy("buy_and_hold"), RiskManager(RiskConfig()),
                    storage=Storage(tmp_path / "t.db"), mode_label="dry_run",
                    enforce_live_ack=False)
    return engine, broker


def test_the_engine_sells_a_held_name_off_the_list(tmp_path):
    engine, broker = _held_iwm_engine(tmp_path)
    actions = {a.symbol: a for a in engine.rebalance()}
    assert actions["IWM"].order_qty == -5.0 and actions["IWM"].submitted_id
    assert broker.position("IWM").is_flat


def test_approve_mode_parks_the_off_list_sell_as_pending(tmp_path):
    engine, broker = _held_iwm_engine(tmp_path)
    outcome = engine.step(submit=False)
    assert outcome.batch_id is not None and broker.position("IWM").qty == 5
    pending = {ln["symbol"]: ln for ln in engine.storage.pending_lines("dry_run")}
    assert pending["IWM"]["order_qty"] == -5.0
    assert pending["IWM"]["reason"] == "not on your list: sell to flat"
