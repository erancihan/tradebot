"""tradebot — a lean, paper-trading-first equities trading bot built on Alpaca.

Design goals:
- Paper trading by default; live trading requires an explicit opt-in.
- Hard risk limits enforced before any order is sized or sent.
- A pluggable Strategy interface so trading logic is swappable and testable.
- A backtester that shares the *same* Strategy and RiskManager code paths as
  live trading, so what you test is what you run.

The strategy/indicator/backtest core depends only on pandas + numpy. The broker
and market-data adapters lazily import the Alpaca SDK, so you can develop and
backtest without credentials or even the SDK installed.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
