"""Autopilot state: a small key/value table per account scope.

Key/value rather than columns because the state grows by a field at a time
(mode, last pass, next pass, last error) and an additive key never needs a
migration. The scope is the engine's mode label ("paper", "dry_run"), so a
paper autopilot and an offline dry-run one sharing a database never read each
other's mode.
"""

from __future__ import annotations


class AutopilotMixin:
    """Autopilot state reads and writes over ``self._conn``."""

    def autopilot_values(self, scope: str) -> dict[str, str | None]:
        rows = self._conn.execute(
            "SELECT key, value FROM autopilot_state WHERE scope = ?", (scope,),
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    def set_autopilot_values(self, scope: str, values: dict[str, str | None]) -> None:
        """Upsert each key; a ``None`` value is stored as NULL (cleared)."""
        self._conn.executemany(
            "INSERT INTO autopilot_state (scope, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(scope, key) DO UPDATE SET value = excluded.value",
            [(scope, k, v) for k, v in values.items()],
        )
        self._conn.commit()
