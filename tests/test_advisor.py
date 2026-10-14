"""The advisor: proposals computed without trading, and their storage."""

from __future__ import annotations

from datetime import datetime, timezone

from tradebot.advisor import Proposal, ProposalLine
from tradebot.storage import Storage


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
