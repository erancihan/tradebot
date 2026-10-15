"""Read-only access to the trading DB (equity, orders, bars, weights)."""

from __future__ import annotations

import json

from . import history as _history
from . import proposals as _proposals
from ._db import _read


class TradingRepository:
    """Equity snapshots + orders written by the engine / dry-run / arena."""

    def __init__(self, db_path: str = "tradebot.db") -> None:
        self.db_path = db_path

    def equity_series(self, mode: str | None = None, limit: int = 2000) -> list[dict]:
        where = "WHERE mode = ?" if mode else ""
        params = (mode, limit) if mode else (limit,)
        rows = _read(
            self.db_path,
            f"SELECT ts, equity, cash, mode FROM equity_snapshots {where} "
            "ORDER BY id DESC LIMIT ?",
            params,
        )
        rows.reverse()  # chronological for charting
        return rows

    def recent_orders(self, limit: int = 50, mode: str | None = None) -> list[dict]:
        """Newest orders; ``status`` is the broker's last word, None until asked
        (``SELECT *``: an unmigrated log lacks the column, this reader never adds it)."""
        where = "WHERE mode = ?" if mode else ""
        params = (mode, limit) if mode else (limit,)
        rows = _read(self.db_path, f"SELECT * FROM orders {where} ORDER BY id DESC LIMIT ?",
                     params)
        for row in rows:
            row.setdefault("status", None)
        return rows

    def modes(self) -> list[str]:
        rows = _read(self.db_path, "SELECT DISTINCT mode FROM equity_snapshots ORDER BY mode")
        return [r["mode"] for r in rows]

    def symbols(self) -> list[str]:
        rows = _read(self.db_path, "SELECT DISTINCT symbol FROM bars ORDER BY symbol")
        return [r["symbol"] for r in rows]

    def bars(self, symbol: str, limit: int = 500,
             timeframe: str | None = None, mode: str | None = None) -> list[dict]:
        """Candles for one symbol, oldest first.

        `timeframe` is part of the bars primary key and `mode` partitions the
        table, so without both filters the same timestamp comes back once per
        (timeframe, mode) partition and the chart draws overlapping duplicate
        candles across half the requested window.
        """
        clauses, params = ["symbol = ?"], [symbol]
        if timeframe:
            clauses.append("timeframe = ?")
            params.append(timeframe)
        if mode:
            clauses.append("mode = ?")
            params.append(mode)
        params.append(limit)
        rows = _read(
            self.db_path,
            "SELECT ts, open, high, low, close, volume FROM bars WHERE "
            + " AND ".join(clauses)
            + " ORDER BY ts DESC LIMIT ?",
            tuple(params),
        )
        rows.reverse()
        return rows

    def timeframes(self) -> list[str]:
        """Distinct timeframes present, newest activity first."""
        rows = _read(self.db_path,
                     "SELECT DISTINCT timeframe FROM bars ORDER BY timeframe")
        return [r["timeframe"] for r in rows]

    def default_mode(self) -> str | None:
        """The mode of the newest snapshot — what the dashboard should show.

        Stats must be scoped to ONE account. Concatenating a $100k paper run
        with a $10k dry-run produced a continuous-looking curve and a
        catastrophic drawdown that never happened.
        """
        row = self.latest_equity()
        return row["mode"] if row else None

    def latest_equity(self) -> dict | None:
        rows = _read(
            self.db_path,
            "SELECT ts, equity, cash, mode FROM equity_snapshots ORDER BY id DESC LIMIT 1",
        )
        return rows[0] if rows else None

    def latest_weights(self, mode: str | None = None) -> dict:
        """The most recent rebalance's target weights, largest first."""
        where = "WHERE mode = ?" if mode else ""
        params = (mode,) if mode else ()
        head = _read(
            self.db_path,
            f"SELECT ts, mode FROM target_weights {where} ORDER BY ts DESC, id DESC LIMIT 1",
            params,
        )
        if not head:
            return {"ts": None, "mode": None, "weights": []}
        ts = head[0]["ts"]
        rows = _read(
            self.db_path,
            f"SELECT symbol, weight FROM target_weights {where}"
            f"{' AND' if mode else ' WHERE'} ts = ? ORDER BY weight DESC, symbol",
            params + (ts,),
        )
        return {"ts": ts, "mode": head[0]["mode"], "weights": rows}

    def latest_universe(self, mode: str | None = None) -> dict:
        """The most recently resolved candidate universe (if any)."""
        where = "WHERE mode = ?" if mode else ""
        params = (mode,) if mode else ()
        rows = _read(
            self.db_path,
            f"SELECT ts, symbols, mode FROM universe_snapshots {where} "
            "ORDER BY id DESC LIMIT 1",
            params,
        )
        if not rows:
            return {"ts": None, "mode": None, "symbols": []}
        try:
            symbols = json.loads(rows[0]["symbols"])
        except (json.JSONDecodeError, TypeError):
            symbols = []
        return {"ts": rows[0]["ts"], "mode": rows[0]["mode"], "symbols": symbols}

    def latest_proposal(self, mode: str | None = None) -> dict | None:
        """The advisor's newest stored proposal (see ``storage/proposals.py``)."""
        return _proposals.latest_proposal(self.db_path, mode)

    def positions_from_orders(self, mode: str) -> dict[str, float]:
        return _proposals.positions_from_orders(self.db_path, mode)

    def latest_equity_for(self, mode: str) -> dict | None:
        return _proposals.latest_equity(self.db_path, mode)

    def orders_page(self, mode: str, before: tuple[str, int] | None = None,
                    limit: int = 20) -> list[dict]:
        """One page of the order log for History (``repository/history.py``),
        keyed on the last shown ``(ts, id)``."""
        return _history.orders_page(self.db_path, mode, before, limit)

    def proposal_batches_page(self, mode: str, before: tuple[str, int] | None = None,
                              limit: int = 20) -> list[dict]:
        return _history.proposal_batches_page(self.db_path, mode, before, limit)

    def filled_orders(self, mode: str) -> list[dict]:
        """Orders of ``mode`` with a known fill, oldest fill first (History's trades)."""
        return _history.filled_orders(self.db_path, mode)

    def watchlist(self) -> list[str]:
        """The Today page's watchlist (``storage/watchlist.py``), oldest first."""
        rows = _read(self.db_path, "SELECT symbol FROM watchlist ORDER BY rowid")
        return [r["symbol"] for r in rows]

    def latest_discover_run(self) -> dict | None:
        """The newest Discover ranking (``storage/discover.py``), or None."""
        from ...storage.discover import decode_run

        rows = _read(self.db_path, "SELECT * FROM discover_runs ORDER BY id DESC LIMIT 1")
        return decode_run(rows[0]) if rows else None
