"""Helpers shared by more than one command group."""

from __future__ import annotations

import logging
import sys


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
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


def _load_settings(args, command: str):
    """The command's settings, resolved as ``tradebot-web`` does, and one line naming the file."""
    from ..config import resolve_settings

    settings, source = resolve_settings(getattr(args, "config", None))
    print(f"tradebot {command}: config={source or 'defaults'}")
    return settings
