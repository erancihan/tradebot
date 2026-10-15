"""Discover runs persist in SQLite: the newest one wins, and it survives a reopen."""

from __future__ import annotations

from tradebot.storage import Storage
from tradebot.web.repository import TradingRepository

ROWS = [{"symbol": "AAA", "score": 0.34, "price": 12.5, "adv": 4.2e7,
         "reason": "Up 34% over 6 months to last month; $42M a day traded."}]


def test_a_run_round_trips_and_the_newest_wins(tmp_path):
    db = tmp_path / "t.db"
    with Storage(db) as st:
        assert st.latest_discover_run() is None
        first = st.record_discover_run(source="cache", as_of="2025-10-14",
                                       provenance={"source": "cache", "bars": 300},
                                       rows=ROWS)
        second = st.record_discover_run(source="alpaca", as_of="2025-10-15",
                                        provenance={"source": "alpaca"}, rows=[])
        assert second > first
    with Storage(db) as st:                      # a restart reads the same run
        run = st.latest_discover_run()
    assert run["id"] == second and run["source"] == "alpaca"
    assert run["as_of"] == "2025-10-15" and run["rows"] == []
    assert run["provenance"] == {"source": "alpaca"}


def test_the_read_only_repository_sees_the_same_run(tmp_path):
    db = str(tmp_path / "t.db")
    repo = TradingRepository(db)
    assert repo.latest_discover_run() is None    # no database yet
    with Storage(db) as st:
        st.record_discover_run(source="cache", as_of=None,
                               provenance={"source": "cache"}, rows=ROWS)
    run = repo.latest_discover_run()
    assert run["rows"] == ROWS and run["as_of"] is None
    assert run["created_at"]
