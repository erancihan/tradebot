"""Helpers shared by more than one command group."""

from __future__ import annotations

import logging
import sys


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S%z",   # orders carry UTC; the log says its offset
    )


def _print_summary(summary: dict) -> None:
    print("\n=== Backtest summary ===")
    for k, v in summary.items():
        print(f"  {k:>14}: {v}")
    print()


def _resolve_universe(settings) -> bool:
    """Swap the static symbol list for the screened candidate universe.

    Returns False (after printing why) when a configured universe can't be
    resolved — never fall back silently to the static list.
    """
    uni = settings.build_universe()
    if uni is None:
        return True
    try:
        symbols = uni.resolve()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return False
    if not symbols:
        print("Universe screen returned no symbols; loosen the thresholds "
              "(min_price / min_dollar_volume) or raise `candidates`.",
              file=sys.stderr)
        return False
    print(f"Universe ({settings.universe_name}): {len(symbols)} candidates: "
          f"{', '.join(symbols)}")
    settings.symbols = symbols
    return True


def _balance(row) -> str:
    """'10,000 -> 12,458 (+24.6%)' from a journal row; '-' when not recorded."""
    if not row or row.get("start_balance") is None or row.get("final_balance") is None:
        return "-"
    start, final = row["start_balance"], row["final_balance"]
    pct = f" ({final / start - 1.0:+.1%})" if start else ""
    return f"{start:,.0f} -> {final:,.0f}{pct}"


def _period(row) -> str:
    """'2023-01-02 -> 2024-05-15': the simulated data window; '-' when unknown."""
    if not row or not row.get("start_date") or not row.get("end_date"):
        return "-"
    return f"{row['start_date'][:10]} -> {row['end_date'][:10]}"


def _format_standings(snap) -> str:
    parts = "  ".join(
        f"{s.rank}.{s.name}({s.total_return:+.1%})" for s in snap.standings
    )
    return f"[{snap.step:>2}/{snap.total_steps} {snap.timestamp[:10]}] {parts}"


def _load_settings(args, command: str, *, active_list: bool = False):
    """The command's settings, resolved as ``tradebot-web`` does; with
    ``active_list`` its symbols are the active list (``_active_list``)."""
    return _load_settings_from(args, command, active_list=active_list)[0]


def _load_settings_from(args, command: str, *, active_list: bool = False):
    """``(settings, source)``, and one line on stderr naming the file, the
    trading db when the command takes ``--trading-db`` and, for a trading
    command, the list (stdout stays the command's own output, so ``tradebot
    universe`` pipes cleanly). ``db_path`` is resolved as the web resolves it."""
    from dataclasses import replace

    from ..config import resolve_settings, trading_db_path

    settings, source = resolve_settings(getattr(args, "config", None))
    settings = replace(settings, db_path=trading_db_path(
        settings, getattr(args, "trading_db", None)))
    line = f"tradebot {command}: config={source or 'defaults'}"
    if hasattr(args, "trading_db"):
        line += f" db={settings.db_path}"
    if active_list:
        settings, label = _active_list(settings)
        line += f" symbols={label}"
    print(line, file=sys.stderr)
    return settings, source


def _active_list(settings):
    """``(settings, label)``: the list the web trades, as of now. The engine
    re-reads it every pass (``engine.active``), so only the universe screen is
    settled here: a non-empty watchlist replaces it, and the config symbols
    stay the fallback for when the watchlist is emptied."""
    from dataclasses import replace
    from pathlib import Path

    from ..storage import Storage
    from ..storage.watchlist import resolve_active

    if Path(settings.db_path).exists():
        with Storage(settings.db_path) as store:
            active = resolve_active(settings, store)
        if active["source"] == "watchlist":
            settings = replace(settings, universe_name=None)
            return settings, f"watchlist({len(active['symbols'])})"
    return settings, f"config({len(settings.symbols)})"


def add_trading_db(parser) -> None:
    """``--trading-db``, as ``tradebot-web`` has it."""
    parser.add_argument("--trading-db", dest="trading_db", default=None,
                        help="trading database (default: $TRADEBOT_DB, else the "
                             "config's db_path; the file tradebot-web uses)")
