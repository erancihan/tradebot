"""Account starts: where a simulated account's history begins.

A dry-run broker is a fresh virtual account at ``initial_cash`` each time one
is built (a web autopilot build, a ``tradebot run --dry-run``), yet every row
it writes carries the same ``dry_run`` label. A start marks the newest id of
the order, snapshot and batch tables at that moment, so History reads the
run's rows by id: a replay stamps its orders with bar times, which can lie
before the wall-clock start. Paper and live never record one.
"""

from __future__ import annotations

from ..models import utcnow


class AccountsMixin:
    """Account-start writes over ``self._conn``."""

    def record_account_start(self, mode: str) -> None:
        def newest(table: str) -> int:
            return int(self._conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}")
                       .fetchone()[0])

        self._conn.execute(
            "INSERT INTO account_starts (mode, ts, after_order, after_snapshot, after_batch)"
            " VALUES (?, ?, ?, ?, ?)",
            (mode, utcnow().isoformat(), newest("orders"), newest("equity_snapshots"),
             newest("proposal_batches")))
        self._conn.commit()
