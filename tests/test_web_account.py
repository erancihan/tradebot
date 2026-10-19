"""The dashboard's account: a broker that fails says so, once in the log and
on the page, and falls back to the paper account's snapshot, never another's."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tradebot.storage import Storage
from tradebot.web.repository import TradingRepository
from tradebot.web.services import account_service


class Down:
    def account(self):
        raise ConnectionError("broker unreachable")


@pytest.fixture
def broken_broker(monkeypatch):
    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env",
                        lambda: SimpleNamespace(api_key="k", api_secret="s"))
    monkeypatch.setattr("tradebot.broker.get_broker", lambda *a, **kw: Down())
    monkeypatch.setattr(account_service, "_WARNED", False)


def test_a_failing_broker_shows_the_paper_snapshot_with_a_note(tmp_path, broken_broker,
                                                               caplog):
    db = str(tmp_path / "t.db")
    with Storage(db) as st:
        st.record_equity(100_000, 50_000, "paper")
        st.record_equity(10_000, 10_000, "dry_run")      # newer, another account
    with caplog.at_level("WARNING", logger="tradebot.web"):
        snap = account_service.snapshot(TradingRepository(db))
        account_service.snapshot(TradingRepository(db))
    assert snap["equity"] == 100_000 and snap["mode"] == "paper"
    assert snap["source"] == "local"
    assert snap["note"] == "broker unavailable, showing the last recorded snapshot"
    warned = [r for r in caplog.records if "broker unreachable" in r.getMessage()]
    assert len(warned) == 1                              # once per process


def test_a_failing_broker_without_a_paper_snapshot_shows_none(tmp_path, broken_broker):
    db = str(tmp_path / "t.db")
    with Storage(db) as st:
        st.record_equity(10_000, 10_000, "dry_run")
    snap = account_service.snapshot(TradingRepository(db))
    assert snap["source"] == "none" and snap["equity"] is None
    assert snap["note"]


def test_without_credentials_the_newest_snapshot_shows_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr("tradebot.config.AlpacaCredentials.from_env", lambda: None)
    db = str(tmp_path / "t.db")
    with Storage(db) as st:
        st.record_equity(100_000, 50_000, "paper")
        st.record_equity(10_000, 10_000, "dry_run")
    snap = account_service.snapshot(TradingRepository(db))
    assert snap["mode"] == "dry_run" and not snap.get("note")
