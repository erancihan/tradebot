---
name: add-strategy
description: Use when adding a new trading strategy to the tradebot project (a pluggable signal generator used by the backtester, live engine, and dry-run). Covers the Strategy interface, registration, and the offline test it needs.
---

# Add a tradebot strategy

A strategy is a **pure function of price data**: given a bar DataFrame it returns
a target-position `Series` in `{-1, 0, +1}` (short / flat / long). It holds no
account state and never sizes positions or sends orders — the `RiskManager` and
engine do that. This makes strategies trivially testable and reusable across
backtest, live, and the arena.

## Steps

1. **Create the module** in `tradebot/strategies/<name>.py`:
   ```python
   from __future__ import annotations
   import pandas as pd
   from .. import indicators
   from .base import Strategy

   class MyStrategy(Strategy):
       name = "my_strategy"

       def __init__(self, fast: int = 10, slow: int = 30) -> None:
           if fast >= slow:
               raise ValueError(f"fast ({fast}) must be < slow ({slow})")
           self.fast, self.slow = fast, slow

       @property
       def required_history(self) -> int:
           return self.slow + 5

       def target_positions(self, bars: pd.DataFrame) -> pd.Series:
           self._validate(bars)                      # checks OHLCV columns
           close = bars["close"]
           target = pd.Series(0, index=bars.index, dtype="int64")
           target[indicators.sma(close, self.fast) > indicators.sma(close, self.slow)] = 1
           return target
   ```
   Rules: values must be in `{-1, 0, +1}`; only use **past+present** data (no
   look-ahead); default to `0` (flat) during indicator warm-up. Reuse helpers in
   `tradebot/indicators.py`.

2. **Register it** in `tradebot/strategies/registry.py` by adding the class to the
   `STRATEGIES` dict so `build_strategy("my_strategy", {...})` and the CLI/config
   can find it. Export it from `tradebot/strategies/__init__.py` if useful.

3. **Add tests** in `tests/test_strategies.py` (offline, deterministic). Use
   `tradebot.data.synthetic.synthetic_ohlcv(...)`. Assert: targets ⊆ `{-1,0,1}`,
   correct behaviour on a known trend, and constructor validation. See existing
   `SmaCrossover`/`RsiReversion` tests for the pattern.

4. **Verify**: `make test`. Optionally `tradebot demo --strategy my_strategy`
   isn't wired automatically, but you can backtest via a `config.yaml` with
   `strategy: { name: my_strategy, params: {...} }` and `tradebot backtest`.

## Notes
- For a *stateful regime* (hold until exit), compute signals then `ffill` (see
  `rsi_reversion.py`).
- Strategies are also valid arena contestants — add `@register` to enter one
  (see the `add-arena-algo` skill).
- Update `CLAUDE.md`/`README.md` if you're adding a notable capability.
