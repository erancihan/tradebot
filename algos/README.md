# Writing an arena contestant

Drop a `.py` file in this folder (or anywhere — point `--algos` at it) and
decorate one or more classes with `@register`. The tournament imports the file,
discovers your contestants, runs each over the same data, and ranks them.

> The default runner executes each contestant in a **sandboxed subprocess**
> (hard timeout, no disk writes, no network; `--no-harden` to opt out,
> `--seccomp` for the adversarial tier). Still: review code before running it.

## Two interfaces

**Event-driven** (`Algo`) — look-ahead-safe; you only see the current bar and
past data via `ctx`:

```python
from tradebot.arena import register, Algo, Action

@register(name="my_algo", author="you", tags=("event",))
class MyAlgo(Algo):
    def on_bar(self, bar, ctx) -> Action:
        if ctx.rsi(14) < 30:
            return Action.long()    # go/stay long
        if ctx.rsi(14) > 55:
            return Action.flat()    # go/stay flat
        return Action.hold()        # keep current position
```

`ctx` exposes `position`, `equity`, the past `bars` window, and helpers
`sma(n)`, `ema(n)`, `rsi(n)`. Return `Action.long() / short() / flat() / hold()`.

**Vectorized** (`Strategy`) — return a target-position series over a bar frame:

```python
from tradebot.arena import register
from tradebot.strategies import Strategy

@register(name="my_strategy", author="you")
class MyStrategy(Strategy):
    def target_positions(self, bars):
        ...  # pandas Series in {-1, 0, +1}, indexed like bars
```

## Rules of the game

- A **fresh instance** is created per round — keep per-round state on `self`.
- Contestant **names must be unique** across the field.
- Crashes are isolated: an exception disqualifies *that* contestant only.
- Targets are `+1` long / `0` flat / `-1` short; position **sizing** and risk
  caps are applied by the arena, identically for everyone.

## Run it

```bash
tradebot arena list --algos ./algos
tradebot arena run  --algos ./algos --score sharpe
```

## Prove it's robust, not lucky

One leaderboard on one dataset proves nothing. The `scenarios/` folder ships a
regime library (`bull_trend`, `sideways_chop`, `crash_recovery`, `vol_spike`) —
run your contestant across all of them, and rank with a robustness metric:

```bash
tradebot arena run --algos ./algos --scenario scenarios/crash_recovery.yaml --score worst_fold
tradebot arena run --algos ./algos --scenario scenarios/sideways_chop.yaml  --score consistency
```

`worst_fold` scores the *worst* quarter of the run (a crash fold can't hide
behind a recovery rally); `consistency` penalises lumpy, regime-dependent
earnings.

**Every attempt is counted.** Each `arena run` journals one attempt per
contestant into the arena DB (opt out with `--no-journal`). Variants of one
idea should share a `family` so they count against it together:

```python
@register(name="donchian_55_20", family="donchian")   # variant #2 of the idea
```

```bash
tradebot arena journal                     # attempts per family
tradebot arena journal --family donchian   # every attempt for one family
```

Twenty attempts make one "winner" meaningless — the journal is what keeps a
best-of-20 from being sold as skill.
