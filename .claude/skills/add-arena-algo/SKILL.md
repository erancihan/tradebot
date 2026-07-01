---
name: add-arena-algo
description: Use when writing or registering a contestant for the tradebot algorithm arena (the competition system), or when extending the arena itself (loader, scoring, scenarios, runner). Covers both contestant interfaces and the @register decorator.
---

# Add an arena contestant (or extend the arena)

The arena loads algorithms dynamically from annotated `.py` files and ranks them
over identical data. See `tradebot/arena/` and `algos/README.md`.

## Writing a contestant

Drop a file in `algos/` (or anywhere; pass `--algos <path>`). Decorate a class
with `@register`. Two interfaces — both run through the same stepped sim core and
are directly comparable:

**Event-driven** (`Algo`) — look-ahead-safe; sees only the current bar + past data:
```python
from tradebot.arena import register, Algo, Action

@register(name="my_algo", author="you", tags=("event",))
class MyAlgo(Algo):
    def on_bar(self, bar, ctx) -> Action:
        if ctx.rsi(14) < 30:
            return Action.long()     # go/stay long
        if ctx.rsi(14) > 55:
            return Action.flat()     # go/stay flat
        return Action.hold()         # keep current target
```
`ctx` exposes `position`, `equity`, the past `bars` window, and `sma/ema/rsi(n)`.
`Action.{long,short,flat,hold}()`. A fresh instance is created per round — keep
per-round state on `self`.

**Vectorized** (`Strategy`) — reuse the trading `Strategy` interface:
```python
from tradebot.arena import register
from tradebot.strategies import Strategy

@register(name="my_vec")
class MyVec(Strategy):
    def target_positions(self, bars):
        ...   # pandas Series in {-1, 0, +1}
```

Rules: contestant **names must be unique**; the factory is called with no args
(set defaults in `__init__`); crashes are isolated (an exception DQs only that
contestant). Position **sizing** is applied by the arena's shared `RiskManager`.

Validate and run:
```bash
tradebot arena validate algos/my_algo.py
tradebot arena run --algos ./algos --score sharpe --save
tradebot arena league --algos ./algos --snapshots 10   # standings over a season
tradebot arena season create --name s1 --symbols SPY --algos ./algos  # durable resumable league
tradebot arena history && tradebot arena show
```

## Extending the arena itself

- **New score metric:** add to `SCORERS` in `tradebot/arena/scoring.py`.
- **New data source / scenario field:** `tradebot/arena/scenario.py`
  (`build_frames`); real data flows Alpaca → `data/cache.py BarCache` → frames.
- **Isolation:** `runner.py` has two runners behind the `Runner` protocol,
  chosen by `default_runner` via `--isolation`: `process` (default, hard
  kill-on-timeout + CPU/memory `rlimit`s — **raises** if fork is unavailable,
  never silently downgrades), `thread` (portable **soft** runner), `auto`
  (process if possible, else warned soft fallback). Each contestant is
  **sandboxed by default** (process isolation) via `sandbox.py` — no disk writes
  + network-namespace isolation; `--no-harden` opts out. For *fully adversarial*
  code go further (seccomp syscall filtering / containers) — don't touch
  `tournament.py`/`scoring.py`.
- **Persistence:** `tradebot/arena/store.py` (SQLite `arena_runs`/`arena_results`,
  equity curves as JSON). The web dashboard reads these.

## Critical invariant
The stepped `tradebot/arena/simulation.simulate` must stay numerically consistent
with `tradebot/backtest.Backtester` for vectorized strategies — guarded by
`tests/test_arena_simulation.py::test_simulate_matches_backtester_for_vectorized_strategy`.
If you change either execution loop, keep that test green.

Add offline tests under `tests/test_arena_*.py`, and update `CLAUDE.md` if you
change an invariant or finish a roadmap item.
