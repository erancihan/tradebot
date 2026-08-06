# tradebot

A lean, **paper-trading-first** equities trading bot in Python, built on
[Alpaca](https://alpaca.markets/). It backtests, paper-trades, and (when you
explicitly opt in) live-trades US stocks & ETFs using pluggable strategies and
hard risk limits.

**Cost model:** free to build and run. Alpaca offers commission-free US equity
trading, a $0 minimum, free IEX market data, and a paper-trading sandbox that
mirrors the live API. The only money at risk is capital *you* choose to deploy
in live mode. Everything else — the SDK, the data, this code — is free and open.

> **Contributing / picking this up?** Read [`CLAUDE.md`](CLAUDE.md) for the
> architecture, invariants, gotchas, and dev workflow. Claude Code skills for
> common tasks live in [`.claude/skills/`](.claude/skills/).

> ⚠️ **Not financial advice.** Automated trading can lose money fast. The
> defaults here are conservative and the bot runs in **paper mode** unless you
> jump through deliberate hoops to enable live trading. Understand the code and
> backtest thoroughly before risking a cent.

---

## Why it's built this way

A trading bot is ~20% strategy and ~80% plumbing that stops you losing money by
accident. The design reflects that:

- **Paper by default.** Live trading needs `mode: live` *and* an environment
  latch (`TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND`). You can't risk real money by
  fat-fingering a config.
- **Risk lives in one place.** A `RiskManager` sizes every position (max % of
  equity per symbol), caps total gross exposure, and trips a daily-loss circuit
  breaker that flattens and halts. Strategies can't bypass it.
- **Backtest == live.** The backtester runs the *same* `Strategy` and
  `RiskManager` objects the live engine uses, so what you test is what you run.
- **No look-ahead.** Signals decided on bar *t*'s close are executed on bar
  *t+1*, with configurable slippage and commission.
- **Auditable.** Every order and periodic equity snapshot is written to SQLite.
- **Offline-friendly.** The strategy/backtest core depends only on
  pandas + numpy; the Alpaca SDK is imported lazily, so you can develop, test,
  and backtest with no credentials and no network.

## Architecture

```
                 ┌──────────────┐
   market data → │   Strategy   │ → target ∈ {-1, 0, +1}   (pure, per-symbol)
                 └──────────────┘
                        │
                        ▼
                 ┌──────────────┐   cross-sectional gate: momentum top-K
                 │   Selector   │ → which symbols may be held   (optional)
                 └──────────────┘
                        │
                        ▼
                 ┌──────────────┐   equal / inverse-vol / explicit weights
                 │  Allocator   │ → target weight per symbol   (optional)
                 └──────────────┘
                        │
                        ▼
                 ┌──────────────┐   joint sizing + caps + no-trade band
                 │ RiskManager  │ → signed share quantities (whole book)
                 └──────────────┘
                        │
          ┌─────────────┴──────────────┐
          ▼                            ▼
   ┌─────────────┐              ┌─────────────┐
   │  Backtester │              │   Engine    │ → Broker (Alpaca paper/live)
   │ (simulated) │              │ (paper/live)│ → Storage (SQLite audit log)
   └─────────────┘              └─────────────┘
```

| Module | Responsibility |
|---|---|
| `tradebot/indicators.py` | SMA, EMA, RSI, MACD, Bollinger, crossover helpers (pure pandas) |
| `tradebot/strategies/` | `Strategy` interface + crossover, RSI, Donchian, MACD, Bollinger, buy-and-hold |
| `tradebot/risk.py` | Position sizing, joint book allocation, exposure cap, no-trade band, daily-loss breaker |
| `tradebot/allocation.py` | Portfolio weighting: equal / inverse-vol / explicit |
| `tradebot/selection.py` | Cross-sectional selection: momentum/reversal + low-vol top-K with hysteresis |
| `tradebot/universe.py` | Candidate discovery: Alpaca most-actives + liquidity screen |
| `tradebot/overlays.py` | Risk overlays: vol-targeting dial, sector caps (reduce-only) |
| `tradebot/walkforward.py` | Walk-forward evaluation: per-fold out-of-sample metrics |
| `tradebot/portfolio.py` | Cost-basis & realised-P&L accounting (backtest) |
| `tradebot/backtest.py` | Event-driven backtester + performance metrics |
| `tradebot/broker/` | `Broker` interface + Alpaca adapter (lazy SDK import), bracket exits |
| `tradebot/data/` | Alpaca history, synthetic generator, CSV loader, websocket stream |
| `tradebot/engine.py` | Live/paper rebalance loop |
| `tradebot/notify.py` | Fill / circuit-breaker notifications (log + optional webhook) |
| `tradebot/consortium.py` | Blend many algorithms into one book, weighted by voice |
| `tradebot/storage.py` | SQLite persistence of orders + equity |
| `tradebot/config.py` | YAML config + env secrets + live-trading gate |
| `tradebot/cli.py` | `demo` / `backtest` / `run` / `status` commands |

## Quickstart

### 1. Try it with zero setup (offline)

```bash
make install          # venv + core deps (pandas, numpy, pytest)
make test             # run the suite
make demo             # backtest both strategies on synthetic data
```

`demo` needs no API keys and no network — it generates synthetic price data and
backtests `SmaCrossover` and `RsiReversion` against it.

### 2. Backtest a real symbol

Backtest from a local CSV (columns: `timestamp,open,high,low,close,volume`):

```bash
cp config.example.yaml config.yaml
make install
.venv/bin/python -m tradebot.cli backtest --config config.yaml --csv data/SPY.csv --symbol SPY
```

…or pull history straight from Alpaca (needs free keys, see below):

```bash
make install-live
.venv/bin/python -m tradebot.cli backtest --config config.yaml --out equity.csv
```

### 3. Dry-run forward-test

A **dry-run** runs the *exact* real-time trading loop — data → strategy → risk →
order — but fills orders against a **local virtual account** (seeded from
`initial_cash`) instead of sending them anywhere. No money, no broker account,
no order ever leaves the process. Positions and P&L evolve over time, so it's a
true forward-test: the dress rehearsal between backtesting and paper trading.

Fully offline (replays synthetic data — **no credentials, no network**):

```bash
make install
.venv/bin/python -m tradebot.cli run --config config.yaml --replay --replay-periods 300
# or replay your own history:
.venv/bin/python -m tradebot.cli run --config config.yaml --replay-csv data/SPY.csv
```

Against **live** market data (needs a free Alpaca *data* key — still no trading
account is used):

```bash
make install-live
.venv/bin/python -m tradebot.cli run --config config.yaml --dry-run
```

`--dry-run` overlays whatever `mode` your config has (even `mode: live`) and
simply suppresses real submits, so it never trips the live-money gate. On exit it
prints a forward-test summary, and every simulated order + equity snapshot is
written to the SQLite log tagged `dry_run`.

> **What it does *not* model:** real fills (it uses last price ± fixed slippage,
> instant and full), order rejects/partials, buying-power/PDT/settlement rules.
> For realistic execution, graduate to `mode: paper`. The realism ladder is:
> **backtest → dry-run → paper → live**.

### 4. Paper trade

1. Create a free Alpaca account, open **Paper Trading**, and generate API keys.
2. `cp .env.example .env` and paste your **paper** key/secret.
3. Set `mode: paper` in `config.yaml` (the default).

```bash
make install-live
.venv/bin/python -m tradebot.cli status --config config.yaml   # sanity-check connection
.venv/bin/python -m tradebot.cli run --config config.yaml --once   # one rebalance pass
.venv/bin/python -m tradebot.cli run --config config.yaml           # continuous loop
```

### 5. Go live (only when you're sure)

Live trading is intentionally awkward to enable:

1. Set `mode: live` in `config.yaml`.
2. Put **live** (not paper) API keys in `.env`.
3. Export the safety latch: `export TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND`.

Without all three the bot refuses to place live orders.

## Configuration

Strategy and risk knobs live in `config.yaml` (safe to commit — no secrets).
Secrets live in `.env` / environment only. See `config.example.yaml` for the
full annotated set. Key risk controls:

```yaml
risk:
  max_position_pct: 0.10     # ≤10% of equity per symbol
  max_gross_exposure: 1.0    # ≤100% of equity deployed at once
  max_daily_loss_pct: 0.03   # flatten + halt after a 3% daily drawdown
```

### Bracket exits (stop-loss / take-profit)

Two optional risk knobs attach exit legs to every order that *adds* exposure —
opening or adding to a position, or flipping its direction. Reductions and exits
never carry them:

```yaml
risk:
  stop_loss_pct: 0.05        # exit 5% below the entry price
  take_profit_pct: 0.15      # exit 15% above it   (either may be set alone)
```

Live, these become a real Alpaca bracket order (`oto` when only one leg is set),
so the broker holds the legs even if the bot is offline. In a dry-run they are
simulated from each bar's high/low, pessimistically: on a bar that touches both
levels the **stop** wins, a gap through the stop fills at the **open** (a stop is
a trigger, not a guaranteed price), and a target never fills better than its
limit.

Two things to be clear about:

- **Backtests do not model brackets.** Neither the backtester nor the arena
  simulates resting orders, so a backtest of a bracketed config shows the
  un-bracketed result. Never quote a backtest as evidence about a stop.
- **A bracket protects between rebalances, not against your own signal.** If the
  strategy still says long after a stop fires, the next pass buys back in. If you
  want it to stay out, that belongs in the strategy.

### Notifications

Order fills, bracket exits and circuit-breaker halts are always logged. Point
them at a webhook to get them as JSON too (stdlib `urllib` — no new dependency):

```yaml
notify:
  webhook_url: https://hooks.example.com/tradebot
```

Delivery failures are logged and swallowed. An unreachable endpoint slows a pass
by at most the 5s timeout; it never halts trading.

## Portfolio: selection + allocation

By default every symbol gets the same fixed `max_position_pct` slug of equity.
An optional `portfolio:` block turns the symbol list into a managed portfolio
with two independent layers — *which* symbols to hold, and *how much* of each:

```yaml
strategy:
  name: buy_and_hold           # selector-only portfolio (momentum top-K)
portfolio:
  selector:
    name: momentum
    params: {lookback: 252, skip: 21, top_k: 5}   # 12-1 momentum, hold 5
  allocation: inverse_vol      # equal | inverse_vol | explicit
  params: {window: 63}
risk:
  rebalance_band_pct: 0.02     # skip drift trades < 2% of equity
```

**Selection (which):** the `momentum` selector ranks the pool each bar by
trailing `lookback`-bar return skipping the most recent `skip` bars (the
classic "12-1" construction), and holds the top `top_k`. Hysteresis keeps a
holding until it slips below `exit_rank` (default 1.5×K), so borderline names
don't churn. `reverse: true` flips the ranking into short-term reversal (hold
the biggest recent losers — use a short lookback). The `low_vol` selector
holds the `top_k` *calmest* names by rolling realized volatility instead.
Membership *gates* the per-symbol strategy: with `buy_and_hold` the selector
is the sole signal; with e.g. `sma_crossover` a symbol must be selected *and*
trending to be held. Symbols without a full lookback of history are never
selected.

**Allocation (how much):**
- **`equal`** — 1/N over the held symbols. The classic hard-to-beat baseline.
- **`inverse_vol`** — weight by 1/volatility (rolling stdev of daily returns
  over `window` bars), so risk rather than dollars is spread evenly. Symbols
  without enough history to measure get nothing.
- **`explicit`** — fixed per-symbol weights you choose; unlisted symbols get 0.

**Overlays (optional risk transforms):** applied to the weights in configured
order, and reduce-only by design — they can de-risk the book but never add
exposure:
- **`sector_cap`** — cap any one sector's total weight so a screen can't
  become a single factor bet (unmapped symbols share one conservative
  "other" bucket; map via inline `sectors:` or a `sectors_file:` CSV).
- **`vol_target`** — scale the whole book down when its realized volatility
  runs above `target_vol` (annualized); calm regimes are *never* levered up.
  Keep it last in the chain so it measures the book it actually scales.

The whole book is sized in one order-independent pass: weights are capped
per-name, scaled down proportionally if their total exceeds
`max_gross_exposure`, and only then turned into share quantities. A
`rebalance_band_pct` no-trade band suppresses tiny drift trades (full exits
always execute) — in the offline demo it cuts trade count ~10×. Selection and
weights obey the same one-bar shift as signals in backtests (decided on bar
*t*, filled on *t+1*), and each rebalance's (post-overlay) target weights are
persisted to the SQLite log.

**Walk-forward evaluation:** don't trust one backtest number. `tradebot
backtest --walk-forward N` splits the history into N contiguous folds after
the pipeline's warmup and evaluates each independently, printing per-fold
return/Sharpe/drawdown plus the mean/worst spread — dispersion across folds
(one great fold carrying the rest) is the tell for regime-dependence or luck.

Try it offline, no credentials:

```bash
.venv/bin/python -m tradebot.cli demo --portfolio
```

**Universe (which symbols even qualify):** instead of hand-typing `symbols`,
an optional `universe:` block discovers the candidate pool from Alpaca at
startup — today's most-active names, filtered to active + tradable assets,
screened by minimum price (default $5) and rolling average dollar volume, and
capped to the most liquid `max_symbols`. The resolved list replaces `symbols`
for the session, is printed at startup, and is snapshotted to SQLite as a
point-in-time paper trail. Preview it any time:

```bash
.venv/bin/python -m tradebot.cli universe --config config.yaml
```

Two honest caveats: Alpaca's free IEX feed reports only ~2% of consolidated
volume (set ADV floors conservatively), and a universe screened *today* is
survivorship-biased for historical backtests — use it live-forward (paper),
not as evidence about the past.

The full portfolio pipeline is then: **universe** (which symbols qualify) →
**selector** (which to hold now) → **allocator** (how much of each) →
**RiskManager** (final quantities under caps).

## Strategies

- **`sma_crossover`** — trend-following. Long when the fast MA is above the slow
  MA, flat (or short) otherwise. SMA or EMA selectable.
- **`rsi_reversion`** — mean-reversion. Long when RSI is oversold, exit when it
  normalises; optional short side.
- **`donchian_breakout`** — turtle-style trend entry. Long on a break above the
  prior `entry`-bar high, exit on a break below the prior `exit`-bar low.
- **`macd_trend`** — long while the MACD line (fast EMA − slow EMA) is above its
  signal line; optional short side.
- **`bollinger_reversion`** — buy a close below the lower Bollinger band, exit
  when price reverts to the middle band; optional short side above the upper.
- **`buy_and_hold`** — always long; the benchmark every idea has to beat, and
  the signal to use when a portfolio selector should be the only decision-maker.
- **`follow_leader`** — meta: each bar, trade whatever sub-strategy earned the
  most over the trailing `window` (a greedy bandit over a mixed roster).
- **`ensemble_vote`** — meta: long/short only when at least `min_agree`
  sub-strategies agree; disagreement means flat.

Add your own by subclassing `Strategy` and implementing
`target_positions(bars) -> Series` (values in `{-1, 0, +1}`), then register it in
`tradebot/strategies/registry.py`. Because strategies are pure functions of
price data, they're trivial to unit-test (see `tests/test_strategies.py`).

## Algorithm arena (competitions)

Load multiple algorithms dynamically and rank them head-to-head over identical
data — like a coding competition for trading strategies. Drop a decorated `.py`
file in `algos/` (or point `--algos` at any path) and it's discovered, run, and
scored automatically.

```bash
tradebot arena list  --algos ./algos                       # discover contestants
tradebot arena run   --algos ./algos --score sharpe        # rank them
tradebot arena run   --algos ./algos --save                # ...and persist the run
tradebot arena league --algos ./algos --snapshots 10       # standings evolve over a season
tradebot arena season create --name s1 --symbols SPY --algos ./algos  # durable, resumable real-time league
tradebot arena season run 1 --replay                       # advance it offline (or live with Alpaca creds)
tradebot arena season run 1 --simulate                     # dry-run the live daemon offline (market clock + replay)
tradebot arena history                                     # list past tournaments
tradebot arena show  [run_id]                              # reprint a saved leaderboard
tradebot arena journal                                     # attempts per algo family (data-snooping ledger)
tradebot arena validate algos/my_algo.py                   # smoke-test one file
```

Saved runs (metadata, per-contestant results, and equity curves as JSON) go to a
local SQLite DB (`arena.db`), ready for the dashboard to chart later.

A contestant is a class with the `@register` decorator, in **either** interface:

```python
# event-driven (look-ahead-safe: only sees the current bar + past via ctx)
from tradebot.arena import register, Algo, Action

@register(name="rsi_dip", author="you")
class RsiDip(Algo):
    def on_bar(self, bar, ctx) -> Action:
        if ctx.rsi(14) < 30: return Action.long()
        if ctx.rsi(14) > 55: return Action.flat()
        return Action.hold()
```

```python
# vectorized (reuse the Strategy interface)
from tradebot.arena import register
from tradebot.strategies import Strategy

@register(name="my_trend")
class MyTrend(Strategy):
    def target_positions(self, bars): ...   # Series in {-1,0,+1}
```

```python
# cross-sectional: a whole portfolio competes as ONE entry
from tradebot.arena import PortfolioAlgo, register
from tradebot.allocation import InverseVolatility
from tradebot.selection import MomentumSelector
from tradebot.strategies import BuyAndHold

@register(name="momo_book", tags=("portfolio",))
class MomoBook(PortfolioAlgo):
    def __init__(self):
        super().__init__(strategy=BuyAndHold(),                       # selector-only book
                         selector=MomentumSelector(lookback=60, skip=5, top_k=2),
                         allocator=InverseVolatility(window=30))
```

A `PortfolioAlgo` composes the *same* strategy/selector/allocator/overlay stack
the backtester and live engine run (a test keeps them in lockstep), so a
portfolio entry that wins the arena is directly promotable to paper trading.
The `scenarios/cross_sectional.yaml` scenario gives the pool a persistent
leader/laggard spread — the environment where selection skill shows up.

Every contestant runs through the **same simulation core** (which a test proves
matches the `Backtester`), over an identical `Scenario` — same data, capital, and
cost/risk model — fed bar-by-bar so the future is never visible. Crashes and
timeouts are isolated (one bad algo can't sink the field), and the leaderboard is
ranked by a configurable metric (`sharpe` | `total_return` | `cagr` | `calmar` |
`worst_fold` | `consistency`). The last two are **robustness** metrics: they
split the realized equity curve into contiguous folds and score the worst fold
(a crash can't hide behind a recovery) or the mean minus the dispersion
(regime-dependence penalty). Scenarios are reproducible YAML; synthetic and CSV
sources work fully offline. See [`algos/README.md`](algos/README.md) for the
contestant guide.

**The experiment journal.** Trying twenty variants and reporting the best one
is how backtests lie. Every `arena run` automatically journals one *attempt*
per contestant (status and score included — failures count) into the arena DB;
`--no-journal` opts out. Variants declare a shared family
(`@register(name="donchian_55_20", family="donchian")`) so attempts accumulate
against the *idea*, not each name. `tradebot arena journal` shows the ledger —
each attempt records its **balance change** (`10,000 -> 12,261 (+22.6%)`) and
the **simulated period** (`2023-01-02 -> 2024-12-30`) alongside the ranking
score — a score ranks, but dollars-over-what-window tells the story — and the
more attempts a family has burned, the stricter the bar its winner must clear.

**The promotion runbook (arena → paper).** An algorithm *earns* its way to
real (paper) trading; nothing is promoted off one leaderboard:

```bash
# 1. write it, smoke-test it
tradebot arena validate algos/my_algo.py

# 2. the gauntlet: candidate vs buy_and_hold across the regime library.
#    Exit code is the verdict (0 pass / 1 fail); every run is journaled.
tradebot arena gate --algos ./algos --candidate my_algo \
  --scenarios scenarios/bull_trend.yaml scenarios/sideways_chop.yaml \
              scenarios/crash_recovery.yaml scenarios/vol_spike.yaml \
              scenarios/cross_sectional.yaml

# 3. out-of-sample folds on the config you'd actually trade
tradebot backtest --config my.yaml --walk-forward 4

# 4. offline forward-test of that exact config (live loop, simulated fills)
tradebot run --config my.yaml --replay

# 5. paper: the real-time loop and/or a live paper season
tradebot run --config my.yaml
tradebot arena season create --name paper1 --symbols ... --algos ./algos \
    --isolation process --time-budget 10
```

For a season you intend to leave running, prefer `--isolation process`. The
default `thread` runner is faster but its time budget is **soft** — it can flag
an over-budget contestant but cannot kill it, so a slow algo leaks a busy thread
every tick until the season crawls. Process isolation makes the budget a hard
kill (and sandboxes each contestant).

The gate checks five things: the candidate completes every scenario, beats
the baseline's mean return net of costs, is at least as robust (`worst_fold`)
in a majority of regimes, never breaches the absolute drawdown bound, and — in
any scenario where the *baseline itself* breaches that bound — is no worse than
the baseline. The last two are separate on purpose: an absolute bound answers
"is this catastrophic", a relative one answers "is this worse than just
holding", and in a crash regime only the second is measuring the candidate. The
verdict
prints alongside the family's journal attempt count — a gate passed on the
20th try means much less than one passed on the 2nd.

**Regime scenario library.** `scenarios/` ships stress environments built from
piecewise synthetic regimes (the price path is continuous across segment
boundaries): `bull_trend`, `sideways_chop`, `crash_recovery` (calm bull → sharp
crash → volatile recovery), and `vol_spike`. An algorithm that only ever met the
default scenario has been tested on one market; the library is the gauntlet:

```bash
tradebot arena run --algos ./algos --scenario scenarios/crash_recovery.yaml --score worst_fold
tradebot arena run --algos ./algos --scenario scenarios/sideways_chop.yaml  --score consistency
```

**Real data, pulled once and cached.** A scenario can compete over real Alpaca
history. You pull it once into a local cache, then every run is offline and
reproducible (the bars are fed bar-by-bar, "as if real time"):

```bash
tradebot data pull --symbols SPY QQQ --start 2023-01-01 --end 2024-01-01
tradebot arena run --algos ./algos --scenario scenarios/alpaca_spy.yaml
```

The `BarCache` (`tradebot/data/cache.py`) downloads any missing range, merges it
into the on-disk cache, and serves everything else from disk — so a given
(symbol, timeframe, range) is fetched at most once. Beside each CSV it writes a
`*.coverage.json` manifest recording which windows were actually pulled, so a
request is served offline even when no bar sits on its boundaries — real
calendars put the first daily bar at the session open and have nothing at all on
a weekend end-date. Pulling needs the `[live]` extra (`pip install -e ".[live]"`)
and paper credentials; replaying afterwards needs neither.

> Contestants run in isolated subprocesses with a hard timeout + CPU/memory
> limits, and are **sandboxed by default** — **no disk writes, no network**
> (`--no-harden` to opt out). For fully adversarial code, add `--seccomp` to also
> install a syscall filter denying `execve`/`execveat`/`ptrace` (blocks
> `subprocess`/`os.system`). The next tier up is OS-level container/gVisor
> containment; see `CLAUDE.md`.

## Consortium (many algorithms, one book)

Rather than betting on a single algorithm, run a panel of them and blend what
each *would* hold. A member that loses money is not thrown out — its **voice**
shrinks, and it can earn it back. Membership is permanent; influence is earned.

```bash
tradebot-web                       # then open /consortium
```

The page shows every member's current book side by side, its voice, and the
blended consensus. It is **advisory** — it places no orders.

Two things make the blend behave sensibly:

- **Agreement is conviction.** The consensus is the voice-weighted average of
  the member books, so a unanimous panel takes a full position, a split panel
  takes a small one, and an evenly divided panel stands aside. Disagreement
  shrinks the trade instead of flipping a coin.
- **Nobody is silenced permanently.** The `hedge` voice weights members by their
  own realised P&L, with a floor, so a member that comes good again recovers.

It also competes as an ordinary contestant, with no exemption from the gauntlet:

```bash
tradebot arena gate --algos ./algos ./algos/consortium     --candidate consortium --scenarios scenarios/xs_*.yaml --time-budget 120
```

It lives in `algos/consortium/` rather than `algos/` because it costs the *sum
of its members* to run — keep it out of ordinary tournaments and give it a
larger time budget.

> **Read any consortium result with this caveat.** The shipped members are
> mostly trend and mean-reversion variants over one equity-beta pool. Averaging
> correlated members reduces the noise in the estimate, not the systematic
> exposure — this panel is closer to one strategy wearing many hats than to a
> diversified committee. What makes a consortium worth having is member
> *diversity*, which is a roster problem rather than a combiner problem.

**What it actually scored.** Over the balanced 7-scenario factor library the
consortium **fails the gate**, and it fails the opposite way to everything
before it: mean CAGR 3.37% vs `buy_and_hold`'s 9.17%, but a better worst fold in
5 of 7 scenarios (at every fold count tried) and a shallower drawdown than the
baseline in both crashes (−33.64% vs −45.93%, −40.56% vs −49.11%). It is the
textbook diversification trade — smoother, safer, and it gives up return in
roughly the proportion it takes out risk. That is exactly the signature the
caveat above predicts, which is the point: it was written before the run.

The `hedge` voice scores 3.68% against equal voice's 3.37% over the same seven
scenarios — +0.31pp, same verdict, same pattern. Weighting members by their
trailing P&L mostly reallocates noise, which is why equal weight is the default.

## Dashboard (web UI)

A FastAPI dashboard visualises everything the bot records: the equity curve,
account stats, recent orders and positions (from the SQLite log, with a live
Alpaca overlay when credentials are present), the **target allocations** of the
latest rebalance (weight bars + the resolved candidate universe, refreshed
live), plus the **arena leaderboards** with each contestant's equity curve. The **Run** page launches a backtest or dry-run
forward-test from the browser (a background job → polled → summary + equity
chart), all on synthetic data with no credentials. The **Chart** page shows a
candlestick of the bars the bot acted on, with buy/sell order pins overlaid. A
live account header (equity/cash/buying-power/market status) and the equity curve
update live over a single **SSE** stream while a session runs, with a one-click
pause.
The **Seasons** page shows each live-league season's standings and a
return-over-the-season chart.

```bash
make install-web      # python web extra + npm install
make web              # build the frontend, then serve at http://127.0.0.1:8000
```

Stack: server-side Jinja templates, **TypeScript** bundled with esbuild (no inline
JS — everything is an imported, type-checked module), **Alpine.js** for reactivity,
**Apache ECharts** for charts, **Tailwind** for styling. The layering is strict —
`routes → services → repository`, with HTML *partials* reused for both first paint
and Alpine's polling, and JSON endpoints feeding the charts. Nothing in the
trading core imports FastAPI; the web layer is purely additive.

Frontend dev loop:

```bash
cd frontend
npm run typecheck     # strict tsc
npm run watch:js      # rebuild bundle on change (also: watch:css)
```

> Built assets (`tradebot/web/static/`) are gitignored and reproduced by
> `npm run build`. The dashboard is read-only — it never places orders.

## Running a long paper season

A season ranks the whole field over wall-clock time, persisting only the bars —
so it survives restarts, and resuming is just reloading and stepping again.

**Seed it first.** A daily season started from zero measures nothing for
months: `MomentumSelector(lookback=60)` is flat for its first 61 bars, so a
fresh season spends a quarter with nobody deployed. Backfilling real history
fixes that, and it is sound — bars are the source of truth and every contestant
is causal, so replaying real history is exactly what running live over that
period would have produced.

```bash
# 1. pull the history once (needs the [live] extra + free data keys)
tradebot data pull --symbols XLK XLE XLV XLF XLY XLP XLI XLB XLU TLT GLD SHY \
    --timeframe 1day --start 2025-01-02 --end 2026-08-01

# 2. create the season — process isolation for anything long-running
tradebot arena season create --name paper1 \
    --symbols XLK XLE XLV XLF XLY XLP XLI XLB XLU TLT GLD SHY \
    --algos ./algos --score sharpe \
    --isolation process --time-budget 30 --db season.db

# 3. backfill, so the field starts warmed up
tradebot arena season seed 1 --start 2025-01-02 --end 2026-08-01 --db season.db

# 4. run the daemon (market-hours gated; --simulate dry-runs it offline)
tradebot arena season run 1 --db season.db
```

Standings built on seeded bars are **backfilled, not live-earned** — the window
was chosen after the fact and everything in it was knowable when the field was
written. `season seed` records the boundary and `season standings` prints it, so
the two claims stay separable. Read the live portion as the result.

Watch it at `/seasons` in the dashboard.

### Keeping it alive

The daemon is a normal long-running process: supervise it however you already
supervise things. It sleeps through closed markets and holidays on its own, and
because bars are the only state, a hard kill loses at most the tick in flight.

```ini
# /etc/systemd/system/tradebot-season.service
[Service]
ExecStart=/path/to/.venv/bin/tradebot arena season run 1 --db /var/lib/tradebot/season.db
WorkingDirectory=/path/to/tradebot
EnvironmentFile=/etc/tradebot.env      # ALPACA_API_KEY / ALPACA_API_SECRET
Restart=always
RestartSec=60
```

Two things worth knowing before you leave it running:

- **Use `--isolation process`.** The default `thread` runner is faster but its
  time budget is soft — it can flag an over-budget contestant but not kill it,
  so a slow algo leaks a busy thread every tick until the season crawls. Process
  isolation makes the budget a hard kill.
- **Recompute is O(history) per tick.** That is fine at daily cadence for years,
  but a minute-bar season over a large field will not keep up.

## Running it for free, continuously

For a $0 deployment, run the loop on any always-on machine you already have
(a Raspberry Pi, a home server) under `cron`/`systemd`/`tmux`, or schedule
`run --once` with `cron`. Paper trading and IEX data stay within Alpaca's free
tier.

## Testing

```bash
make test     # 383 tests, fully offline
```

## Roadmap / ideas

**The backlog is empty as of 2026-08-05.** Everything once listed here has
shipped: the FastAPI dashboard (see "Web dashboard"), and the three
live-execution items below.

- ✅ Bracket / stop-loss / take-profit order types — `risk.stop_loss_pct` /
  `take_profit_pct`; see "Bracket exits" above.
- ✅ Notifications on fills and circuit-breaker trips — the `notify:` block.
- ✅ Streaming data via Alpaca websockets — `tradebot/data/stream.py`, consumed
  by the arena season.

One item is deferred on purpose: **container/gVisor isolation** for arena
contestants. Contestant code is human-reviewed before it runs, so the existing
`--harden` (no disk writes + network namespace) and `--seccomp` tiers match the
threat model. Rationale and the implementation seam are in `CLAUDE.md`.

> **Note (2026-07-25, resolved):** a full audit found a look-ahead in the sizing
> path of both backtest loops, plus 15 other defects. The engine is fixed and
> the research record re-derived — the corrected record is in `CLAUDE.md`, and
> it still shows **no contestant passing the promotion gate**. Scope and staged
> plan: `docs/PLAN.md`.

## Disclaimer

This software is for educational purposes and provided "as is", without warranty
of any kind. Trading involves substantial risk of loss. You are solely
responsible for any orders it places and any money you lose. Test in paper mode
first, and never deploy capital you can't afford to lose.

## License

Released under the [MIT License](LICENSE). © 2026 erancihan.
