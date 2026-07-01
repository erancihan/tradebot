"""tradebot.web — a FastAPI dashboard over the bot's SQLite logs and arena results.

Read-only in Phase 1: it visualises the equity curve, recent orders, account
snapshot, and tournament leaderboards. The web layer is import-isolated — nothing
in the trading core imports FastAPI, and these modules are only imported when the
``web`` extra is installed.
"""
