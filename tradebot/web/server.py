"""``tradebot-web`` entrypoint: serve the dashboard with uvicorn."""

from __future__ import annotations

import argparse
import os


def allowed_hosts(flags: list[str], env: str | None = None) -> list[str]:
    """Defaults, then ``TRADEBOT_ALLOWED_HOSTS``, then ``--allow-host``: each extends."""
    # Lazy, like the uvicorn import below: `--help` must not need FastAPI.
    from .app import DEFAULT_ALLOWED_HOSTS

    env = os.getenv("TRADEBOT_ALLOWED_HOSTS", "") if env is None else env
    extra = [h.strip() for h in env.split(",") if h.strip()] + list(flags)
    return DEFAULT_ALLOWED_HOSTS + [h for h in extra if h not in DEFAULT_ALLOWED_HOSTS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradebot-web", description="tradebot dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--trading-db", default=os.getenv("TRADEBOT_DB", "tradebot.db"))
    parser.add_argument("--arena-db", default=os.getenv("TRADEBOT_ARENA_DB", "arena.db"))
    parser.add_argument("--season-db", default=os.getenv("TRADEBOT_SEASON_DB", "season.db"))
    parser.add_argument("--config", default=os.getenv("TRADEBOT_CONFIG"),
                        help="settings YAML for the Today page "
                             "(default: ./config.yaml if present, else SPY/QQQ defaults)")
    parser.add_argument("--allow-host", action="append", default=[], metavar="HOST",
                        help="extra Host header to serve, e.g. your LAN IP or hostname "
                             "(repeatable; '*' disables the check). Also read from "
                             "TRADEBOT_ALLOWED_HOSTS, comma separated")
    parser.add_argument("--token", default=os.getenv("TRADEBOT_WEB_TOKEN"),
                        help="require this access token (default: $TRADEBOT_WEB_TOKEN; "
                             "unset = open, for local use). Sign a browser in once "
                             "at /login")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    import uvicorn

    from .app import create_app

    app = create_app(trading_db=args.trading_db, arena_db=args.arena_db,
                     season_db=args.season_db, settings_path=args.config,
                     allowed_hosts=allowed_hosts(args.allow_host),
                     access_token=args.token or None)
    print(f"Dashboard: http://{args.host}:{args.port}  "
          f"(trading={args.trading_db}, arena={args.arena_db}, season={args.season_db}, "
          f"config={app.state.settings_path or 'defaults'}, "
          f"token={'required' if args.token else 'off'})")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
