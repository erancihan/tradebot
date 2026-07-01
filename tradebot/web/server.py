"""``tradebot-web`` entrypoint: serve the dashboard with uvicorn."""

from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradebot-web", description="tradebot dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--trading-db", default=os.getenv("TRADEBOT_DB", "tradebot.db"))
    parser.add_argument("--arena-db", default=os.getenv("TRADEBOT_ARENA_DB", "arena.db"))
    parser.add_argument("--season-db", default=os.getenv("TRADEBOT_SEASON_DB", "season.db"))
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    import uvicorn

    from .app import create_app

    app = create_app(trading_db=args.trading_db, arena_db=args.arena_db,
                     season_db=args.season_db)
    print(f"Dashboard: http://{args.host}:{args.port}  "
          f"(trading={args.trading_db}, arena={args.arena_db}, season={args.season_db})")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
