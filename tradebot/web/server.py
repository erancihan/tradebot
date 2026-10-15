"""``tradebot-web`` entrypoint: serve the dashboard with uvicorn."""

from __future__ import annotations

import argparse
import logging
import os
import sys


def allowed_hosts(flags: list[str], env: str | None = None) -> list[str]:
    """Defaults, then ``TRADEBOT_ALLOWED_HOSTS``, then ``--allow-host``: each extends."""
    # Lazy, like the uvicorn import below: `--help` must not need FastAPI.
    from .app import DEFAULT_ALLOWED_HOSTS

    env = os.getenv("TRADEBOT_ALLOWED_HOSTS", "") if env is None else env
    extra = [h.strip() for h in env.split(",") if h.strip()] + list(flags)
    return DEFAULT_ALLOWED_HOSTS + [h for h in extra if h not in DEFAULT_ALLOWED_HOSTS]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tradebot-web", description="tradebot dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--trading-db", default=os.getenv("TRADEBOT_DB", "tradebot.db"))
    parser.add_argument("--arena-db", default=os.getenv("TRADEBOT_ARENA_DB", "arena.db"))
    parser.add_argument("--season-db", default=os.getenv("TRADEBOT_SEASON_DB", "season.db"))
    # No env default here: ``config.resolve_settings`` reads TRADEBOT_CONFIG,
    # so `tradebot` and `tradebot-web` resolve the file by one rule.
    parser.add_argument("--config", default=None,
                        help="settings YAML (default: $TRADEBOT_CONFIG, else "
                             "./config.yaml if present, else SPY/QQQ defaults)")
    parser.add_argument("--allow-host", action="append", default=[], metavar="HOST",
                        help="extra Host header to serve, e.g. your LAN IP or hostname "
                             "(repeatable; '*' disables the check). Also read from "
                             "TRADEBOT_ALLOWED_HOSTS, comma separated")
    parser.add_argument("--token", default=os.getenv("TRADEBOT_WEB_TOKEN"),
                        help="require this access token (default: $TRADEBOT_WEB_TOKEN; "
                             "unset = open, for local use). Sign a browser in once "
                             "at /login")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="load the config, open the database, print the startup "
                             "line and exit (0 = ready to serve); run it before "
                             "enabling a service")
    return parser


def _build_app(args):
    from .app import create_app

    return create_app(trading_db=args.trading_db, arena_db=args.arena_db,
                      season_db=args.season_db, settings_path=args.config,
                      allowed_hosts=allowed_hosts(args.allow_host),
                      access_token=args.token or None)


def _check(args) -> int:
    from .startup import check_config, startup_line

    try:
        app = _build_app(args)
        check_config(app.state.settings_path)
        print(startup_line(app))
    except Exception as exc:        # any reason it would not serve, said plainly
        print(f"tradebot-web --check failed: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    # Before the parser reads its env defaults: launchd has no EnvironmentFile,
    # so a service there gets TRADEBOT_WEB_TOKEN from the `.env` in its
    # WorkingDirectory (only there, never searched for), as the Alpaca keys
    # do. Variables already set win.
    from ..credentials import _maybe_load_dotenv

    _maybe_load_dotenv()
    args = _parser().parse_args(argv)
    if args.check:
        return _check(args)

    import uvicorn

    app = _build_app(args)
    # uvicorn configures only its own loggers; without this the startup line
    # and the autopilot's warnings never reach a service manager's journal.
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(f"Dashboard: http://{args.host}:{args.port}  "
          f"(trading={args.trading_db}, arena={args.arena_db}, season={args.season_db}, "
          f"config={app.state.settings_path or 'defaults'}, "
          f"token={'required' if args.token else 'off'})")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
