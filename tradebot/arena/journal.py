"""The experiment journal: one row per contestant attempt (the snooping ledger).

Mixed into :class:`~tradebot.arena.store.ArenaStore`, which owns the connection
and the schema; this module owns what an attempt *means* — its engine version,
its scenario-library fingerprint and how attempts are grouped by family.
"""

from __future__ import annotations

from math import isfinite
from pathlib import Path

from ..models import utcnow

#: Identifies the *instrument* that produced a journalled number, so results
#: from before and after a correctness fix are never silently compared. Bump it
#: whenever a change alters what the execution loops compute. History:
#:   e1  original loops
#:   e2  2026-07-25 — sizing marked at the fill bar's open, not its close
#:                    (`backtest._sizing_marks`); targets computed after
#:                    alignment; `exit_rank` no longer freezes on small pools.
ENGINE_VERSION = "e2"


def library_fingerprint(paths) -> str:
    """Short content hash of a scenario set — the gauntlet's identity.

    Pre-registration only means something if edits are visible. Hashing the
    YAML contents (not their names) means quietly softening a scenario a
    candidate keeps failing produces a new fingerprint, so the journal reads
    "library v2, attempt 1" instead of silently continuing the old tally.
    """
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(str(p) for p in paths):
        try:
            digest.update(Path(path).read_bytes())
        except OSError:
            digest.update(path.encode())
    return digest.hexdigest()[:12]


def _clean(value: float) -> float | None:
    """NaN/inf -> NULL so the DB stores clean numbers."""
    return value if value is not None and isfinite(value) else None


class JournalMixin:
    """Experiment-ledger queries over ``self._conn`` (an ``sqlite3`` connection)."""

    def record_attempts(self, scenario, metric: str, outcome, run_id: int | None = None,
                        only_families: set[str] | None = None,
                        library: str | None = None) -> int:
        """Journal one experiment row per contestant (the data-snooping ledger).

        Every evaluation counts as an attempt — including failures. Attempts are
        grouped by the contestant's ``family`` (default: its name), so trying
        ten variants of one idea shows up as ten attempts against that idea.

        ``only_families`` restricts journaling to the ideas actually under
        development. The pass gate needs it: it runs the *whole* field against
        every gauntlet scenario merely to obtain a baseline, so journaling
        everyone charged +1 attempt per scenario to all twelve families. That is
        how `buy_and_hold` — never iterated on once — came to carry the same
        attempt count as a candidate under active development, and it made the
        multiple-testing statistic measure gate invocations rather than
        iterations of an idea.

        ``library`` is a content hash of the scenario set the attempt was run
        against (see :func:`library_fingerprint`). Editing a scenario after
        seeing a result then shows up as a *different* library rather than
        vanishing into a re-run — which is the specific dishonest move
        pre-registration exists to make visible.
        """
        ts = utcnow().isoformat()
        entries = outcome.leaderboard.entries
        if only_families is not None:
            entries = [r for r in entries
                       if (getattr(r.contestant, "family", "") or r.name) in only_families]
        for r in entries:
            family = getattr(r.contestant, "family", "") or r.name
            start = final = first = last = None
            if r.result is not None:
                start = float(r.result.initial_cash)
                final = float(r.result.final_equity)
                curve = r.result.equity_curve
                if len(curve):
                    first = str(curve.index[0])
                    last = str(curve.index[-1])
            self._conn.execute(
                "INSERT INTO experiments (ts, family, name, scenario, metric,"
                " score, status, start_balance, final_balance, start_date,"
                " end_date, run_id, engine, library)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, family, r.name, scenario.name, metric, _clean(r.score),
                 r.status, _clean(start), _clean(final), first, last, run_id,
                 ENGINE_VERSION, library),
            )
        self._conn.commit()
        return len(entries)

    def journal_rows(self) -> list[dict]:
        """Every journalled attempt, oldest first — the raw ledger for export."""
        rows = self._conn.execute(
            "SELECT ts, family, name, scenario, metric, score, status,"
            " start_balance, final_balance, start_date, end_date, engine, library"
            " FROM experiments ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    def journal_summary(self) -> list[dict]:
        """Attempts per family, most-tried first, with each family's best score."""
        rows = self._conn.execute(
            "SELECT family, COUNT(*) AS attempts, COUNT(DISTINCT name) AS variants,"
            " COUNT(DISTINCT scenario) AS scenarios, MAX(ts) AS last_ts"
            " FROM experiments GROUP BY family ORDER BY attempts DESC, family"
        ).fetchall()
        out = []
        for row in rows:
            best = self._conn.execute(
                "SELECT name, scenario, metric, score, start_balance,"
                " final_balance, start_date, end_date"
                " FROM experiments WHERE family = ? AND score IS NOT NULL"
                " ORDER BY score DESC LIMIT 1",
                (row["family"],),
            ).fetchone()
            d = dict(row)
            d["best"] = dict(best) if best else None
            out.append(d)
        return out

    def journal_entries(self, family: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM experiments WHERE family = ? ORDER BY id DESC",
            (family,),
        ).fetchall()
        return [dict(r) for r in rows]
