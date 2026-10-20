"""Persisted price history: the bars the dashboard and the selector read back."""

from __future__ import annotations


def _ts_iso(ts) -> str:
    """Normalise a bar timestamp (pandas Timestamp / datetime / str) to ISO text."""
    iso = getattr(ts, "isoformat", None)
    return iso() if callable(iso) else str(ts)


class BarsMixin:
    """Bar upserts and reads over ``self._conn``."""

    def record_bars(self, symbol: str, timeframe: str, bars, mode: str) -> None:
        """Persist OHLCV bars (idempotent — a re-written timestamp is updated).

        Deliberately an upsert rather than ``INSERT OR IGNORE``: the engine polls
        intraday, so the newest bar it persists is usually *still forming*. Under
        first-write-wins that partial bar would be frozen permanently and could
        never be replaced by the settled one — and the stored history is what the
        selector reads back, so the contamination would land squarely on the
        decision path.
        """
        rows = [
            (symbol, timeframe, _ts_iso(ts), float(r["open"]), float(r["high"]),
             float(r["low"]), float(r["close"]), float(r["volume"]), mode)
            for ts, r in bars.iterrows()
        ]
        if not rows:
            return
        self._conn.executemany(
            "INSERT INTO bars"
            " (symbol, timeframe, ts, open, high, low, close, volume, mode)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(symbol, timeframe, ts, mode) DO UPDATE SET"
            " open=excluded.open, high=excluded.high, low=excluded.low,"
            " close=excluded.close, volume=excluded.volume",
            rows,
        )
        self._conn.commit()

    def load_bars(self, symbol: str, timeframe: str, mode: str | None = None,
                  limit: int | None = None):
        """Full stored history for one symbol, oldest first, in BAR_COLUMNS shape.

        The live engine feeds this to the selector. A `RankedSelector` walk is
        path-dependent (its `held` set starts empty), so prefix-stability
        licenses recomputing a *prefix* — it says nothing about truncating the
        *head*. Handing the selector a rolling window would make the live
        holdings depend on when the process happened to start; the accumulated
        bars are the source of truth, exactly as in `season.py`.

        ``limit`` keeps only the newest ``limit`` bars (still oldest first).
        pandas is imported lazily to keep this module stdlib-only on import.
        """
        import pandas as pd

        sql = ("SELECT ts, open, high, low, close, volume FROM bars"
               " WHERE symbol = ? AND timeframe = ?")
        params: list[object] = [symbol, timeframe]
        if mode is not None:
            sql += " AND mode = ?"
            params.append(mode)
        if limit is None:
            sql += " ORDER BY ts"
        else:
            sql += " ORDER BY ts DESC LIMIT ?"
            params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        if limit is not None:
            rows.reverse()
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        idx = pd.to_datetime([r[0] for r in rows], utc=True)
        return pd.DataFrame(
            [{"open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
             for r in rows],
            index=idx,
        )
