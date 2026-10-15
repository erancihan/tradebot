# tradebot

[![CI](https://github.com/erancihan/tradebot/actions/workflows/ci.yml/badge.svg)](https://github.com/erancihan/tradebot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

A paper-trading-first portfolio companion for US stocks and ETFs, built on
[Alpaca](https://alpaca.markets/). Open it on your phone. It tells you what to
buy or sell today and why. It can run the portfolio for you, with or without
your approval per trade. It replays past plans with monthly contributions, so
you see the money a plan makes. Behind the app sits a full trading core
(backtester, risk manager, paper/live engine) and a research arena that ranks
algorithms. Alpaca is commission-free with a $0 minimum, free IEX data and a
free paper account, so running it costs nothing.

> ⚠️ **Not financial advice.** Automated trading can lose money fast. The
> defaults are conservative and the bot runs in **paper mode** unless you take
> deliberate steps to enable live trading. Understand the code and test in
> paper mode before you risk a cent.

## Use it from your phone

This is the main path. Everything here runs without API keys. Keys add live
market data and a real paper account.

### 1. Install and start

```bash
make install-all      # venv + every Python extra + npm install
make web              # build the frontend, then serve at http://127.0.0.1:8000
```

`make web` listens on loopback only. To open it from a phone, see
[Reach it over the network](#8-reach-it-over-the-network). For the terminal
commands in this README, activate the venv with `source .venv/bin/activate`.

### 2. Settings: pick symbols and a strategy

Open **Settings** (`/settings`, under **More** on a phone). Pick your symbols
and bar size, a strategy, and optionally a selector (hold the best N) and an
allocator (how to split money). Parameters show as typed fields. Risk limits
are typed as percentages. The same page sets the autopilot cadence, the
morning brief, alert destinations and the exchange calendar.

Tap **Save**. The server builds every component you named, so a typo comes
back as one readable sentence. Then it writes `config.yaml` atomically and
reloads. A running autopilot stops on save so it never trades on old settings.
Start it again from Autopilot.

Settings never shows or accepts a broker key. It only says whether `.env` has
them. It never changes `mode` (paper or live). Alert destinations show masked.
Leave a masked value as it is to keep it. A saved file has no comments.
[`config.example.yaml`](config.example.yaml) documents every key. Overlays and
a `universe:` block survive a save but are edited in the file.

### 3. Add Alpaca paper keys (optional)

Without keys the app works from cached bars (What-if also offers synthetic
ones) and the account is simulated. With keys it fetches missing bars and
reads your paper account.

1. Create a free Alpaca account, open **Paper Trading** and generate API keys.
2. Run `cp .env.example .env` and paste your **paper** key and secret. The
   app reads the `.env` in the working directory (where you run it) and
   nowhere else, only the keys `.env.example` lists; variables already set win.
3. Restart `make web`. `make install-all` already installed the Alpaca SDK;
   after `make install-web` alone, run `make install-live` first.

Until config, keys and cached bars are all in place, Today shows a
**Finish setting up** card with the fix for each one.

### 4. Today: what to trade now

**Today** (`/today`) is the first tab. Tap **Refresh** to compute a proposal on
the server. Each row shows the symbol, a BUY, SELL or HOLD badge, the share
quantity, the dollar amount and a one-line reason built from each layer:

```
sma_crossover signals long; rank 2 of 5, weight 23%, capped by the risk limit; buy.
```

A row can also say `not selected (rank 4 of 5)` or `within band, hold`.

- **Account strip:** equity, cash and their source, `paper (Alpaca)`,
  `paper (from log)` or `paper (starting cash)`.
- **Holdings:** quantity, last cached price, value and weight per position.
- **Watchlist:** type a symbol and tap **Add**, tap the cross on a chip to
  remove it. While it has symbols, Refresh and the autopilot scan those
  instead of the config's `symbols`. An edit stops a running autopilot.

Refresh reads bars through the local cache. It fetches missing bars only with
server-side Alpaca keys. Without them, an uncached symbol gets the exact
`tradebot data pull` command. The proposal comes from `advisor.propose`, the
same function the engine runs before it submits. A suggestion is exactly what
a paper pass trades. Nothing on Today places an order.

**Discover** answers "what else could I buy?". Tap **Find candidates** and the
server ranks names you neither watch nor hold by 6-month momentum skipping the
last month (the `momentum` selector's score) and lists the top 10 with the last
close and a reason, for example `Up 34% over 6 months to last month; $42M a day
traded.` With server-side Alpaca keys the pool is Alpaca's most-active
shortlist after the liquidity screen (at most 20 names, whose bars land in the
cache); without keys it is every symbol with cached daily bars, through the same
screen. The card says which, with the as-of date and the bar window. **Add**
puts a name on your watchlist next to your current symbols: an empty watchlist
is first filled with the symbols in use, so the config list never drops out.
Like any watchlist edit, it stops a running autopilot. The last run survives a restart. Discover never places an order.

### 5. Autopilot: let it trade

**Autopilot** (`/autopilot`) is the second tab. Pick a mode:

- **Off.** Nothing runs.
- **Approve first.** Every `poll_seconds` inside market hours the bot computes
  the Today proposal and lists its trades under **Waiting for approval**. Tap
  **Approve** or **Reject** per trade, or **Approve all**. While the passes
  keep proposing the same trades, the batch stays: each pass re-sizes it at its
  own prices, and a rejected trade stays rejected. A pass that proposes
  different trades replaces it. An approval more than one poll interval after
  the last pass expires the batch. It never executes late. The phone gets one
  push per batch, then a reminder every 2 x `poll_seconds` (at least 30 minutes),
  or sooner when a re-sized line grows more than 10% past what the push said.
- **Automatic.** Every pass submits its trades.

The status card shows the mode, the loop, the account, the last and next pass,
the pending count and the last error. If the daily-loss limit
(`risk.max_daily_loss_pct`) trips, the engine closes every open position,
and the autopilot switches itself **off**, shows `daily loss halt` and
notifies you. The limit is measured per exchange session day, so a plain
`tradebot run` trades again at the next session.

With keys the autopilot trades the **paper** account. Without them it runs a
dry-run (simulated fills) over cached bars and labels the account `dry_run`.
It never reaches a live account. The loop is a thread inside the web server.
It resumes after a restart in a non-off mode and stops with the server.

### 6. What-if: replay a plan

**What-if** (`/whatif`) is the third tab. Pick a preset or type symbols, a
start and end date, starting cash and a monthly contribution. **Advanced**
adds a strategy, a selector and an allocator. Tap **Run what-if**.

The server replays the plan with the same `Backtester` as everything else and
adds the monthly cash on the first trading day of each month. The benchmark is
equal-weight buy and hold over the same symbols with the same cash. The result
leads with the money gain (final value minus everything put in), then the
comparison. Yearly growth and worst drop leave contributions out.

Presets come from the cache, familiar index funds first. With an empty cache
the presets are synthetic and labelled so. The date pickers are bounded by
cache coverage. An uncached range shows the exact `tradebot data pull` command.

**Compare strategies**, next to Run, answers "which decision rule would have
done best for this plan?" It replays the same plan once per strategy, each on
its default settings, with your symbols, dates, cash, selector and allocator
unchanged. A plan with its own strategy settings also gets a row of its own,
"(your settings)". The result is a table ranked by final value (your plan
highlighted, buy and hold in its place) and a chart of the best five plus buy
and hold. Meta strategies need a roster from the config file and are listed
as not run. A strategy that fails is listed with its error; the rest still run.

### 7. Phone alerts with ntfy

[ntfy](https://ntfy.sh) pushes alerts to your phone as plain text, with no
account:

1. Install the ntfy app (Android or iOS).
2. Pick a long, hard-to-guess topic name and subscribe to it in the app. A
   topic on ntfy.sh is public to anyone who knows its name.
3. Enter the topic on **Settings** and Save, or set `notify.ntfy_topic` in
   `config.yaml` (plus `notify.ntfy_server` for a self-hosted server).

Tap **Send test alert** on Autopilot. The page says which channels accepted
it. You then get an alert for each approval batch, order, bracket exit,
daily-loss halt and morning brief.

**Morning brief.** Set `autopilot.brief_minutes_before_open: 30` and the
autopilot sends the day's proposal that many minutes before each open:

```
BUY 35 SPY (buy_and_hold signals long; buy.)
BUY 38 QQQ (buy_and_hold signals long; buy.)
```

The brief is a preview. It stores, parks and submits nothing. It fires once
per session in any mode while the loop runs.

**Approve from the notification.** In autopilot mode **Approve first**, set
**Public URL** on Settings (`notify.public_url`) to the address your phone
opens the app at, for example `http://192.168.1.20:8000`. The push for each
pending batch then carries three buttons: **Approve all** submits that
batch's pending trades, **Skip** rejects them, **Open** opens Autopilot. The
server must be reachable from the phone: the same setup as
[Reach it over the network](#8-reach-it-over-the-network), including
`--allow-host` for that host. Approve and Skip are signed links, each good for
one batch and one action, for twice the poll interval (at least 30 minutes).
They work without the login cookie. The signing key comes from
`TRADEBOT_WEB_TOKEN`; without a token it is random per server process, so a
restart kills old links (the next reminder push brings fresh ones). Each link
works once per server process: a second tap is refused (409); after a restart
a used link can act again until it expires, on lines still pending. A tap after
a pass replaced the batch with different trades does nothing. A link is signed for one account
and only the **paper** account's push carries Approve and Skip: a dry-run,
replay or live push carries just Open. A hand-edited `public_url` that is not a
plain http(s) address gives a push without buttons and a warning in the log.

**With `public_url` set, the ntfy topic itself grants approval** of the bot's
own pending paper trades: anyone who can read the topic sees the links. Use a
self-hosted ntfy server or ntfy access control (an access token on the topic),
and a long random topic name. Links from
`tradebot run --autopilot` on paper are served by `tradebot-web` on the same database
and need the same `TRADEBOT_WEB_TOKEN` in both processes.

### 8. Reach it over the network

By default the server listens on loopback and needs no login. For a phone on
the same network, set a token and list the host the phone uses:

```bash
make web-build
export TRADEBOT_WEB_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
tradebot-web --host 0.0.0.0 --allow-host 192.168.1.20   # your LAN IP or hostname
```

Open `http://192.168.1.20:8000/login` **once** on the phone and paste the
token. It sets a long-lived HttpOnly cookie (an HMAC of the token, not the
token). Then use **Add to Home Screen**. The app ships a web manifest, so it
opens full screen with the bottom tab bar (Today, Autopilot, What-if, More).

Two guards are always on. Requests for an unlisted `Host` are refused
(`--allow-host` or a comma-separated `TRADEBOT_ALLOWED_HOSTS` extend the
loopback default, and `'*'` disables the check with a warning). Every
state-changing request needs `X-Requested-With: tradebot`, which the frontend
sends and a cross-site form cannot (the login form is exempt). The token is
posted from a form, never put in a URL. Scripts send
`Authorization: Bearer <token>`. Prefer the env var to `--token`, because
other users see command-line arguments in `ps`. The connection is plain HTTP.
Keep it on a network you trust, or put HTTPS in front (the cookie is then
marked `Secure`). `--config other.yaml` serves a different settings file.

### 9. Keep it running

The autopilot is a thread inside `tradebot-web`, so it trades only while the
server is up. [`deploy/`](deploy/README.md) has a systemd unit (Linux) and a
launchd agent (macOS) that start the server at boot or login and restart it
after a crash. Run `tradebot-web --check` with the same flags first: it
validates the config, opens the database, prints the startup line and exits 0
(1 says what is wrong). The service logs that line at every start: the config
file, the database, the allowed hosts, and whether the token and the Alpaca
keys are set (never their values), plus the autopilot's stored mode. Secrets
come from the service's environment, or from the `.env` in its working
directory (launchd: the plist's `WorkingDirectory`).

A restart keeps the config, the databases, the watchlist and the autopilot
mode. A loop left on **Approve first** or **Automatic** resumes by itself at
start, so a crash or reboot does not quietly stop the bot. Set it to **Off**
before a restart you want to look at first. Trades waiting for approval wait
on: the first pass after the restart re-sizes them if it proposes the same
trades, and replaces them if not.
A dry-run's virtual account starts over, while the paper account lives at
Alpaca. Approve links in phone alerts outlive a restart only with
`TRADEBOT_WEB_TOKEN` set (they are signed with it).

### More pages (under More on a phone)

- **History** (`/history`): what the bot has done and decided, newest first,
  for the account the dashboard shows. A card compares equity now with the
  first of the last 2000 snapshots, beside a small equity chart. Below it one timeline mixes the
  orders the bot sent (symbol, side, shares, and the amount at the price the
  trade was sized at) with each proposal batch (its trades by status: suggested,
  pending, approved, rejected, submitted or expired). Tap a batch for each
  line's reason. **Show more** loads older entries. Today links here too.
- **Dashboard** (`/`): equity curve, account stats, orders, positions and the
  target allocations of the latest rebalance.
- **Run** (`/run`): a backtest or dry-run on synthetic or cached real bars.
  Every result wears a **provenance badge** naming its data.
- **Chart** (`/chart`): candlesticks with order pins. The account header and
  equity curve update live over one SSE stream, with a pause toggle.
- **Arena**, **Seasons**, **Consortium**: the [research views](#research-tooling).

Run and What-if read only the local cache. Today's Refresh and Discover's Find
candidates are the only page actions that fetch bars, and only with server-side keys. Empty pages say
which command fills them.

## How it decides

Every flow, from the Today page to a backtest, runs one pipeline:

```
                 ┌──────────────┐
   market data → │   Strategy   │ → target ∈ {-1, 0, +1}   (pure, per-symbol)
                 └──────────────┘
                        │
                        ▼
                 ┌──────────────┐   cross-sectional gate: momentum top-K
                 │   Selector   │ → which symbols can be held   (optional)
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

- **Universe → selector → allocator → risk.** An optional universe screen
  picks which symbols qualify. The selector picks which to hold now. The
  allocator sets how much of each. The `RiskManager` turns weights into share
  quantities under per-name and gross caps. Strategies only emit targets in
  `{-1, 0, +1}` and never size positions.
- **Paper by default.** Live trading needs `mode: live` in the config **and**
  `TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND` in the environment. The web app cannot
  switch either one.
- **No look-ahead.** A decision made on bar *t*'s close fills on bar *t+1*.
  Selection, weights and sizing obey the same shift.
- **Backtest equals live.** The backtester, the engine, the Today page and the
  arena share the same `Strategy` and `RiskManager` code.
- **Provenance on every result.** Proposals, What-if runs and Run jobs record
  their data source, window and age. A synthetic curve never passes for a real
  one.
- **Auditable and offline-first.** Every order, equity snapshot and target
  weight goes to SQLite. The core needs only pandas and numpy, and the Alpaca
  SDK loads lazily, so every page and test runs with no keys and no network.

[`CLAUDE.md`](CLAUDE.md) holds the module map, invariants and gotchas, and
[`.claude/skills/`](.claude/skills/) holds Claude Code skills for common tasks.

## Terminal reference

Install with `make install` (core), `make install-live` (adds Alpaca),
`make install-web` (adds the web app) or `make install-all` (everything).
`tradebot <command> --help` lists every flag. `--config PATH` defaults to
`./config.yaml` when present, else SPY/QQQ defaults, for `tradebot` and
`tradebot-web` alike; each command prints the file it used.

### Commands

The realism ladder runs backtest → dry-run → paper → live:

```bash
tradebot demo [--strategy NAME] [--portfolio]              # offline, synthetic data
tradebot backtest --csv data/SPY.csv --symbol SPY
tradebot backtest --walk-forward 4    # Alpaca history, per-fold metrics
tradebot run --replay                 # offline forward-test
tradebot run --replay-csv data/SPY.csv  # replay your own CSV
tradebot run --dry-run                # live data, simulated fills
tradebot run --once                   # one paper pass
tradebot run                          # continuous paper loop
tradebot status                       # broker account snapshot
tradebot universe                     # screened universe (needs keys)
tradebot data pull --symbols SPY QQQ --start 2024-01-01 --end 2025-01-01
tradebot-web [--host H] [--port P] [--config F] [--allow-host H] [--token T] [--trading-db F] [--check]
```

Always pass explicit `--start` and `--end` to `data pull`. The cache records
the window you asked for. `tradebot arena` is under
[Research tooling](#research-tooling).

A **dry-run** runs the real-time loop but fills orders against a local virtual
account seeded from `initial_cash`. `--dry-run` overrides any `mode`, even
`mode: live`, so it never trips the live gate. Orders land in SQLite tagged
`dry_run`. It does not model real fills (last price plus fixed slippage,
instant and full), rejects, partials, buying power, PDT or settlement.

**Walk-forward** splits the history into N folds after the warmup and prints
per-fold return, Sharpe and drawdown. One great fold carrying the rest points
to luck or one regime.

**Headless autopilot.** These build the engine exactly as `tradebot run` does,
so `--dry-run`, `--replay` and the live gate all apply:

```bash
tradebot run --autopilot --mode auto       # paper, market hours
tradebot run --autopilot --mode approve    # park trades for the web page
tradebot run --autopilot --mode off        # morning brief only
tradebot run --replay --autopilot --mode auto --iterations 50   # offline
```

Parked trades wait on the Autopilot page of a server with the same database.

**Go live (only when you are sure).** Set `mode: live`, put **live** keys in
`.env` and `export TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND`. Without all three the
bot refuses to place live orders.

**Run it for free** on an always-on machine you own, such as a Raspberry Pi.
Use the service files in [`deploy/`](deploy/README.md), `tmux`, or `run --once`
from `cron`. Paper trading and IEX data stay inside Alpaca's free tier.

### Configuration

Settings live in `config.yaml` (safe to commit, no secrets). Secrets live in
`.env` only. [`config.example.yaml`](config.example.yaml) annotates every key.
The blocks people copy most:

```yaml
risk:
  max_position_pct: 0.10      # at most 10% of equity per symbol
  max_gross_exposure: 1.0     # at most 100% of equity deployed
  max_daily_loss_pct: 0.03    # flatten + halt after a 3% daily drawdown
  rebalance_band_pct: 0.02    # skip drift trades under 2% of equity (exits always run)
portfolio:
  selector:
    name: momentum
    params: {lookback: 252, skip: 21, top_k: 5}   # 12-1 momentum, hold 5
  allocation: inverse_vol     # equal | inverse_vol | explicit
  params: {window: 63}
  overlays:                   # reduce-only, applied in order
    - name: vol_target
      params: {target_vol: 0.15, window: 20}
notify:
  webhook_url: https://hooks.example.com/tradebot
  ntfy_topic: tradebot-pick-a-long-random-name
  public_url: http://192.168.1.20:8000   # Approve/Skip buttons on the push
autopilot:
  brief_minutes_before_open: 30
market: us_equities           # or bist
```

**Selectors.** `momentum` ranks the pool by trailing `lookback` return,
skipping the last `skip` bars, and holds the top `top_k`. Hysteresis keeps a
holding until it slips below `exit_rank` (default 1.5×K). `reverse: true`
holds the biggest recent losers. `low_vol` holds the `top_k` calmest names.
With `strategy: buy_and_hold` the selector is the only signal. With any other
strategy a symbol must be selected **and** signal long.

**Allocators.** `equal` (1/N), `inverse_vol` (1/volatility over `window`
bars) or `explicit` (fixed weights, unlisted symbols get 0). **Overlays.**
`sector_cap` caps one sector's total weight. `vol_target` scales the book down
when realized volatility runs above target and never levers up. Keep it last.

**Universe.** A `universe:` block replaces `symbols` at startup with today's
most-active, tradable names screened by price and average dollar volume.
Preview it with `tradebot universe`. Free IEX data reports about 2% of
consolidated volume, so set volume floors low. A universe screened today is
survivorship-biased for backtests. Use it live-forward.

**Market calendars.** `us_equities` (default) is 09:30-16:00 New York with
NYSE holidays. `bist` is Borsa Istanbul, 10:00-18:00 Istanbul time with
Turkish holidays through 2027. Alpaca is the only broker, so `bist` changes
when the loop wakes. Orders still go to the US paper account.

### Strategies

| Name | Idea |
|---|---|
| `sma_crossover` | Long when the fast MA is above the slow MA (SMA or EMA) |
| `rsi_reversion` | Long when RSI is oversold, exit when it normalises |
| `donchian_breakout` | Long on a break above the prior high, exit below the prior low |
| `macd_trend` | Long while MACD is above its signal line |
| `bollinger_reversion` | Buy below the lower band, exit at the middle band |
| `momentum` | Long when the `lookback` rate of change beats `threshold`, optional trend filter |
| `supertrend` | ATR bands that only tighten toward price, long in an up trend |
| `buy_and_hold` | Always long. The benchmark, and the signal for a selector-only book |
| `follow_leader` | Meta: trade the sub-strategy with the best trailing P&L |
| `ensemble_vote` | Meta: long or short only when `min_agree` sub-strategies agree |

Most take `allow_short`. To add one, subclass `Strategy`, implement
`target_positions(bars)` returning values in `{-1, 0, +1}`, and register it in
`tradebot/strategies/registry.py`. The `add-strategy` skill walks through it.

### Bracket exits

Two optional risk keys attach exit legs to every order that **adds** exposure.
Reductions and exits never carry them:

```yaml
risk:
  stop_loss_pct: 0.05        # exit 5% below the entry price
  take_profit_pct: 0.15      # exit 15% above it (either one alone works)
```

Live, these become an Alpaca bracket order (`oto` with one leg), so the broker
holds the legs while the bot is offline. A dry-run simulates them from each
bar's high and low, pessimistically. On a bar that touches both levels the
stop wins. A gap through the stop fills at the open. A target never fills
better than its limit.

**Backtests do not model brackets.** Never quote a backtest as evidence about
a stop. **A bracket protects between passes, not against your own signal.**
After a stop fires, the next pass buys back in on a long signal.

### Notifications

Order fills, bracket exits, daily-loss halts, approval batches and the morning
brief always go to the log. Add `notify.webhook_url` to get them as JSON, or
an ntfy topic to get them on your phone (see
[Phone alerts with ntfy](#7-phone-alerts-with-ntfy)). Both use stdlib
`urllib`. A failed delivery is logged and swallowed. An unreachable endpoint
slows a pass by at most the 5s timeout and never halts trading.

## Research tooling

The arena ranks algorithms head-to-head over identical data. It is how an idea
earns its way to paper trading. Verdicts, numbers and caveats live in
[`docs/research-record.md`](docs/research-record.md). No contestant passes the
promotion gate yet.

### Arena

Drop a decorated `.py` file in `algos/` (or point `--algos` anywhere) and it
is discovered, run and scored:

```bash
tradebot arena list     --algos ./algos                  # discover contestants
tradebot arena validate algos/my_algo.py                 # smoke-test one file
tradebot arena run      --algos ./algos --score sharpe   # rank them (--save persists the run)
tradebot arena league   --algos ./algos --snapshots 10   # standings over a replayed season
tradebot arena history                                   # past saved tournaments
tradebot arena show     [run_id]                         # reprint a saved leaderboard
```

A contestant is an event-driven `Algo`, a vectorized `Strategy` subclass or a
whole-book `PortfolioAlgo`:

```python
from tradebot.arena import register, Algo, Action, PortfolioAlgo
from tradebot.allocation import InverseVolatility
from tradebot.selection import MomentumSelector
from tradebot.strategies import BuyAndHold

@register(name="rsi_dip", author="you")
class RsiDip(Algo):                      # sees only the current bar and the past
    def on_bar(self, bar, ctx) -> Action:
        if ctx.rsi(14) < 30: return Action.long()
        if ctx.rsi(14) > 55: return Action.flat()
        return Action.hold()

@register(name="momo_book", tags=("portfolio",))
class MomoBook(PortfolioAlgo):           # a whole portfolio competes as ONE entry
    def __init__(self):
        super().__init__(strategy=BuyAndHold(),
                         selector=MomentumSelector(lookback=60, skip=5, top_k=2),
                         allocator=InverseVolatility(window=30))
```

Every contestant runs the `Backtester`'s simulation core, fed bar by bar so the
future is invisible. A winning `PortfolioAlgo` is directly promotable. Scores
are `sharpe`, `total_return`, `cagr`, `calmar`, `worst_fold` and `consistency`.
The last two score the worst fold or the mean minus the dispersion. The
contestant guide is [`algos/README.md`](algos/README.md).

Contestants run in forked processes with a hard timeout and optional
`--cpu-seconds` and `--memory-mb` limits. They are sandboxed by default (no
disk writes, no network). `--no-harden` opts out. `--seccomp` also denies
`execve` and `ptrace`. `--require-sandbox` fails a contestant, instead of
warning, when the kernel refuses a mechanism.

### Scenarios

Scenarios are reproducible YAML files in [`scenarios/`](scenarios/). The
regime library (`bull_trend`, `sideways_chop`, `crash_recovery`, `vol_spike`)
is single-symbol. The factor library (seven `xs_*` files) shares one 8-name
pool and one market factor, so it exercises cross-sectional selection, in
rewarding and punishing pairs. The real pack (`real_xs_2021` to
`real_xs_2023`, sector SPDRs plus TLT, GLD and SHY) ends with the sealed
holdout `real_xs_2024_2025h1`. Run the holdout once, last.

```bash
tradebot arena run --algos ./algos --scenario scenarios/crash_recovery.yaml --score worst_fold
tradebot data pull --symbols SPY QQQ --start 2023-01-01 --end 2024-01-01
tradebot arena run --algos ./algos --scenario scenarios/alpaca_spy.yaml
```

Real bars are pulled once into `data/cache` (needs the `[live]` extra and
keys). Every later run is offline.

### Gate and journal

The gate judges a candidate against `buy_and_hold` over a gauntlet. The exit
code is the verdict (0 pass, 1 fail):

```bash
tradebot arena gate --algos ./algos --candidate my_algo \
  --scenarios scenarios/xs_*.yaml --seeds 5
```

It checks five things. The candidate completes every scenario and beats the
baseline's mean CAGR net of costs. Its `worst_fold` matches or beats the
baseline in most scenarios. Its drawdown stays inside `--max-drawdown` (35%),
and where the baseline breaches that bound, the candidate is no worse. `--seeds N` re-draws the gauntlet and flags
`UNSTABLE` when the verdict flips.

Every `arena run` and `arena gate` journals one attempt per contestant into
`arena.db` (`--no-journal` opts out). Variants share a family
(`@register(name="donchian_55_20", family="donchian")`), so attempts count
against the idea. `tradebot arena journal` prints the ledger with balance
change and simulated period, and `--export PATH` writes it to CSV. A gate
passed on the 20th try means much less than one passed on the 2nd.

**Promotion runbook:** validate, gate, `backtest --walk-forward` on the config
you plan to trade, `run --replay`, then paper with `run` or a season.

### Consortium

A consortium runs a panel of algorithms and blends the books of its members. A
losing member keeps its seat but its **voice** shrinks, and it can earn it
back. A split panel takes a small position. The **Consortium** page shows each
member's book, its voice and the blended consensus. It places no orders.

It lives in `algos/consortium/` because it costs the sum of its members:

```bash
tradebot arena gate --algos ./algos ./algos/consortium --candidate consortium \
  --scenarios scenarios/xs_*.yaml --time-budget 120
```

The shipped members are mostly trend and mean-reversion variants over one
equity-beta pool. A panel over them is close to one strategy wearing many
hats. Member diversity is what makes a consortium worth having.

### Seasons

A season ranks the field over wall-clock time. It stores only bars, so it
survives restarts. Seed it first, because a daily season from zero spends a
quarter warming up:

```bash
tradebot data pull --symbols XLK XLE XLV XLF XLY XLP XLI XLB XLU TLT GLD SHY \
    --timeframe 1day --start 2025-01-02 --end 2026-08-01
tradebot arena season create --name paper1 \
    --symbols XLK XLE XLV XLF XLY XLP XLI XLB XLU TLT GLD SHY \
    --algos ./algos --score sharpe --isolation process --time-budget 30 --db season.db
tradebot arena season seed 1 --start 2025-01-02 --end 2026-08-01 --db season.db
tradebot arena season run 1 --db season.db               # market-hours daemon
tradebot arena season run 1 --simulate --db season.db    # dry-run the daemon offline
tradebot arena season standings 1 --db season.db
```

Seeded standings are backfilled, not live-earned. `season standings` and the
**Seasons** page show the seed boundary. Read the live portion as the result.

Use `--isolation process` for anything long-running. The default `thread`
runner cannot kill an over-budget contestant, so a slow one leaks a thread
every tick. A restart heals up to 30 missed bars. Re-run `season seed` for a
longer gap. To run a season as a service, adapt
`deploy/systemd/tradebot-web.service`: swap its `ExecStart` for
`tradebot arena season run 1 --db /var/lib/tradebot/season.db`.

## Testing

```bash
make test                          # pytest, fully offline, no credentials
cd frontend && npm run typecheck   # strict tsc (needs make install-web)
cd frontend && npm test            # behaviour tests (tests/*.test.ts) in Node, fetch stubbed
cd frontend && npm run watch:js    # rebuild the bundle on change (also watch:css)
```

Built assets in `tradebot/web/static/` are gitignored. `npm run build`
reproduces them. The web stack is Jinja templates, TypeScript bundled by
esbuild, Alpine.js, Apache ECharts and Tailwind, with no inline JavaScript.

## Design decisions

- [`docs/adr/0001-server-side-refresh.md`](docs/adr/0001-server-side-refresh.md):
  why the server computes suggestions and can fetch bars.
- [`docs/adr/0002-portfolio-companion.md`](docs/adr/0002-portfolio-companion.md):
  the companion flows (Today, Autopilot, What-if), Settings, market calendars
  and what was left out on purpose.
- [`docs/research-record.md`](docs/research-record.md): research results, gate
  verdicts and standing decisions.

## Disclaimer

This software is for educational purposes and provided "as is", without
warranty of any kind. Trading involves substantial risk of loss. You are
solely responsible for any orders it places and any money you lose. Test in
paper mode first, and never deploy capital you cannot afford to lose.

## License

Released under the [MIT License](LICENSE). © 2026 erancihan.
