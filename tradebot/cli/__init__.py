"""Command-line entrypoint.

    tradebot backtest [--out out.csv]
    tradebot demo                         # offline backtest on synthetic data
    tradebot run                          # paper/live loop (needs Alpaca creds)
    tradebot status                       # account snapshot from the broker

``--config PATH`` defaults to ./config.yaml when present, else SPY/QQQ defaults,
exactly as ``tradebot-web`` resolves it (``config.resolve_settings``).

Live trading additionally requires TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND (see config).

Each command group lives in its own module and attaches itself through
``register(sub)``; this module only assembles the parser and dispatches.
"""

from __future__ import annotations

import argparse

from .. import __version__
from . import arena, backtest, data, demo, run, status, universe
from .common import _setup_logging

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tradebot", description="Lean Alpaca trading bot.")
    p.add_argument("--version", action="version", version=f"tradebot {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)
    # Registration order is the order `tradebot --help` lists the commands.
    for group in (demo, backtest, run, status, arena, universe, data):
        group.register(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    return args.func(args)
