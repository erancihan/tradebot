"""Target weights and universe snapshots: the point-in-time portfolio trail."""

from __future__ import annotations

from ..models import utcnow


class WeightsMixin:
    """Weight/universe records over ``self._conn``."""

    def record_weights(self, weights: dict[str, float], mode: str) -> None:
        """Persist the allocator's target weights for one rebalance pass."""
        if not weights:
            return
        ts = utcnow().isoformat()
        self._conn.executemany(
            "INSERT INTO target_weights (ts, symbol, weight, mode) VALUES (?, ?, ?, ?)",
            [(ts, sym, float(w), mode) for sym, w in weights.items()],
        )
        self._conn.commit()

    def latest_weights(self, mode: str | None = None) -> dict[str, float]:
        """The most recent rebalance's target weights (optionally per mode)."""
        where = "WHERE mode = ?" if mode else ""
        args = (mode,) if mode else ()
        row = self._conn.execute(
            f"SELECT ts FROM target_weights {where} ORDER BY ts DESC, id DESC LIMIT 1",
            args,
        ).fetchone()
        if row is None:
            return {}
        rows = self._conn.execute(
            f"SELECT symbol, weight FROM target_weights {where}"
            f"{' AND' if mode else ' WHERE'} ts = ?",
            args + (row["ts"],),
        ).fetchall()
        return {r["symbol"]: r["weight"] for r in rows}

    def record_universe(self, symbols: list[str], mode: str) -> None:
        """Persist a resolved candidate universe (point-in-time paper trail)."""
        import json

        if not symbols:
            return
        self._conn.execute(
            "INSERT INTO universe_snapshots (ts, symbols, mode) VALUES (?, ?, ?)",
            (utcnow().isoformat(), json.dumps(list(symbols)), mode),
        )
        self._conn.commit()

    def latest_universe(self, mode: str | None = None) -> list[str]:
        """The most recently resolved universe (optionally per mode)."""
        import json

        where = "WHERE mode = ?" if mode else ""
        args = (mode,) if mode else ()
        row = self._conn.execute(
            f"SELECT symbols FROM universe_snapshots {where} ORDER BY id DESC LIMIT 1",
            args,
        ).fetchone()
        return json.loads(row["symbols"]) if row else []
