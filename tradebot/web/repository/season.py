"""Read-only access to a live-league season DB."""

from __future__ import annotations

import json

from ._db import _read


class SeasonRepository:
    """Read-only access to a live-league season DB (season.db)."""

    def __init__(self, db_path: str = "season.db") -> None:
        self.db_path = db_path

    def list_seasons(self) -> list[dict]:
        return _read(
            self.db_path,
            "SELECT id, name, symbols, timeframe, metric, status, updated_at "
            "FROM seasons ORDER BY id DESC",
        )

    def get_season(self, season_id: int) -> dict | None:
        # `seeded_through` is read defensively: this repository is read-only and
        # must not migrate the writer's schema, so a season DB written before
        # seeding existed simply reports None.
        rows = _read(
            self.db_path,
            "SELECT id, name, symbols, timeframe, metric, status, updated_at "
            "FROM seasons WHERE id = ?", (season_id,),
        )
        if not rows:
            return None
        season = rows[0]
        try:
            extra = _read(self.db_path,
                          "SELECT seeded_through FROM seasons WHERE id = ?", (season_id,))
            season["seeded_through"] = extra[0]["seeded_through"] if extra else None
        except Exception:
            season["seeded_through"] = None
        return season

    def latest_standings(self, season_id: int) -> list[dict]:
        rows = _read(
            self.db_path,
            "SELECT standings_json FROM season_standings WHERE season_id = ? "
            "ORDER BY step DESC LIMIT 1", (season_id,),
        )
        return json.loads(rows[0]["standings_json"]) if rows else []

    def standings_history(self, season_id: int) -> list[dict]:
        rows = _read(
            self.db_path,
            "SELECT step, ts, standings_json FROM season_standings "
            "WHERE season_id = ? ORDER BY step", (season_id,),
        )
        return [
            {"step": r["step"], "ts": r["ts"], "standings": json.loads(r["standings_json"])}
            for r in rows
        ]
