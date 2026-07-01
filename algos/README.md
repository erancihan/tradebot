# Writing an arena contestant

Drop a `.py` file in this folder (or anywhere — point `--algos` at it) and
decorate one or more classes with `@register`. The tournament imports the file,
discovers your contestants, runs each over the same data, and ranks them.

> ⚠️ The default runner imports and runs algorithms **in-process** — only run
> code you trust. (A sandboxed subprocess runner is a planned drop-in.)

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
