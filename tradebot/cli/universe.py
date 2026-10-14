"""`tradebot universe` — preview the screened candidate pool."""

from __future__ import annotations

import argparse
import sys


def register(sub: argparse._SubParsersAction) -> None:
    u = sub.add_parser("universe",
                       help="resolve & print the screened candidate universe "
                            "(needs Alpaca creds)")
    u.add_argument("--config", required=True)
    u.set_defaults(func=cmd_universe)


def cmd_universe(args: argparse.Namespace) -> int:
    """Resolve and print the screened candidate universe (needs Alpaca creds)."""
    from ..config import Settings

    settings = Settings.from_yaml(args.config)
    uni = settings.build_universe()
    if uni is None:
        print("No `universe:` block in the config — the static `symbols` list "
              "is the candidate pool. See config.example.yaml.", file=sys.stderr)
        return 2
    try:
        details = uni.resolve_details()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not details:
        print("Universe screen returned no symbols; loosen the thresholds.",
              file=sys.stderr)
        return 1
    print(f"{'symbol':<8} {'price':>10} {'avg $ volume':>16}")
    print("-" * 38)
    for row in details:
        print(f"{row['symbol']:<8} {row['price']:>10.2f} {row['adv']:>16,.0f}")
    print(f"\n{len(details)} candidates pass the screen "
          "(note: IEX volume understates consolidated liquidity).")
    return 0
