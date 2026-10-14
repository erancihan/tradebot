"""`tradebot arena journal` — the multiple-testing ledger."""

from __future__ import annotations

import argparse

from .common import _balance, _period


def register(asub: argparse._SubParsersAction) -> None:
    aj = asub.add_parser("journal",
                         help="attempts-per-family ledger (multiple-testing honesty)")
    aj.add_argument("--family", help="list every attempt for one family")
    aj.add_argument("--export", metavar="PATH",
                    help="write the whole ledger to CSV so it can be committed "
                         "(the DB is gitignored, so counts are otherwise "
                         "unauditable)")
    aj.add_argument("--db", default="arena.db", help="arena results DB (default arena.db)")
    aj.set_defaults(func=cmd_arena_journal)


def cmd_arena_journal(args: argparse.Namespace) -> int:
    """The multiple-testing ledger: how many attempts each algo family has burned."""
    from ..arena.store import ArenaStore

    with ArenaStore(args.db) as store:
        if args.export:
            return _export(store, args)
        if args.family:
            return _print_family(store, args)
        return _print_families(store, args)


def _export(store, args: argparse.Namespace) -> int:
    # The DB is gitignored and every session runs in a fresh container,
    # so the ledger is ephemeral by construction — which is why the
    # attempt counts quoted in past write-ups could never be checked
    # against anything. Exporting to CSV makes the record committable,
    # and therefore auditable.
    import csv

    rows = store.journal_rows()
    if not rows:
        print(f"No attempts journaled yet in {args.db}; nothing to export.")
        return 0
    with open(args.export, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Exported {len(rows)} attempt(s) to {args.export}. "
          "Commit it: an ephemeral ledger proves nothing.")
    return 0


def _print_family(store, args: argparse.Namespace) -> int:
    rows = store.journal_entries(args.family)
    if not rows:
        print(f"No attempts recorded for family {args.family!r} in {args.db}.")
        return 0
    print(f"\nExperiment journal — family {args.family!r}, "
          f"{len(rows)} attempt(s), newest first")
    header = (f"{'#':>4}  {'when (UTC)':<19} {'name':<20} {'scenario':<16} "
              f"{'metric':<12} {'score':>10}  {'balance':<26} "
              f"{'simulated period':<26} status")
    print(header)
    print("-" * len(header))
    for r in rows:
        score = f"{r['score']:.3f}" if r["score"] is not None else "-"
        print(f"{r['id']:>4}  {r['ts'][:19]:<19} {r['name']:<20} "
              f"{r['scenario']:<16} {r['metric']:<12} {score:>10}  "
              f"{_balance(r):<26} {_period(r):<26} {r['status']}")
    return 0


def _print_families(store, args: argparse.Namespace) -> int:
    rows = store.journal_summary()
    if not rows:
        print(f"No attempts journaled yet in {args.db}. "
              "`tradebot arena run` journals automatically.")
        return 0
    print("\nExperiment journal — attempts per algorithm family")
    header = (f"{'family':<20} {'attempts':>8} {'variants':>8} {'scenarios':>9}  "
              f"{'best score (metric @ scenario)':<38} {'balance':<26} "
              f"{'simulated period':<26} last tried")
    print(header)
    print("-" * len(header))
    for r in rows:
        best = r["best"]
        best_s = (f"{best['score']:.3f} ({best['metric']} @ {best['scenario']})"
                  if best else "-")
        print(f"{r['family']:<20} {r['attempts']:>8} {r['variants']:>8} "
              f"{r['scenarios']:>9}  {best_s:<38} {_balance(best):<26} "
              f"{_period(best):<26} {r['last_ts'][:10]}")
    if any(r["attempts"] > 1 for r in rows):
        print("\nA best-of-N result overstates skill: the more attempts a family has,")
        print("the stricter the bar its winner must clear (survive the regime gauntlet")
        print("and a walk-forward, not one lucky leaderboard).")
    return 0
