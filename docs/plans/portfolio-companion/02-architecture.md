# Architecture: portfolio companion

## Fit
Every feature reuses the existing pipeline: universe, selector, allocator,
overlays, then `RiskManager.allocate`. The three features are three consumers
of one new core concept, the proposal. A proposal is the set of signed share
deltas the engine submits on a pass, computed without submitting.

- `tradebot/advisor.py` (new, core). `propose(settings, account, frames)`
  returns a `Proposal`. It is pure: it takes bars and account state and
  returns, per symbol, the target, the quantity delta, the notional and a
  reason string built from the strategy, selector and allocator outputs.
  `Engine.rebalance` calls the same function and then submits the deltas.
  Suggestions and executions therefore cannot disagree. This is the same
  rule as backtest == live.
- `tradebot/autopilot.py` (new, core). A supervised runner around `Engine`
  with the modes `off`, `approve` and `auto`. State and a command inbox live
  in SQLite. In `approve` mode a pass stores the proposal as pending and
  submits only the deltas the user approved. It runs as a thread inside the
  web server process, because the app is single-user and one process is
  easier to supervise. `tradebot run --autopilot` starts the same runner
  without the web server.
- `tradebot/whatif.py` (new, core). Wraps `Backtester` with a contribution
  schedule (monthly cash injections) and a benchmark run (equal-weight buy
  and hold with the same contributions). Returns both curves and a
  comparison.
- `tradebot/market/` (new). The calendar and the holiday table move out of
  `arena/market.py` behind a `MarketCalendar` protocol with a `us_equities`
  implementation. A BIST calendar can be added later without changes to the
  season daemon or the autopilot.
- Web. Three new pages with their JSON endpoints, a mobile-first layout in
  `base.html` with a bottom tab bar, and a PWA manifest so a phone can pin
  the app.
- Data freshness. The web layer stays read-only for trading and never sends
  credentials to the browser. "Refresh" on the Today page runs the advisor on
  the server through `BarCache`. The server reaches the network only when
  credentials exist in its environment. Without credentials it uses cached
  bars and says so. This replaces the earlier rule "the dashboard never
  fetches". The decision is recorded in `docs/adr/0001-server-side-refresh.md`.

## Endpoints
- `GET /today`: page.
- `GET /api/proposal`: latest stored proposal with provenance and age.
- `POST /api/proposal/refresh`: compute a fresh proposal as a polled job.
- `GET /autopilot`: page.
- `GET /api/autopilot`: state (mode, running, last pass, next pass, pending).
- `POST /api/autopilot`: `{mode}` to start, stop or switch mode. `{approve:
  [ids]}` or `{reject: [ids]}` for pending trades.
- `GET /whatif`: page.
- `POST /api/whatif`: run a what-if as a job, polled through `/api/jobs/{id}`.
- `GET /api/whatif/presets`: named presets for the form.
- `GET /manifest.webmanifest`: PWA manifest (static).

## Data
SQLite, `tradebot.db`, through the same `Storage` class.
- `proposals(id, created_at, mode, symbol, target, current_qty, desired_qty,
  order_qty, price, notional, reason, status)`. The status is one of
  `suggested`, `pending`, `approved`, `rejected`, `submitted`. Queries: the
  latest batch by `created_at`, and the pending rows for the approval list.
- `autopilot_state(key, value)`: mode, started_at, last_pass_at, last_error.
- Orders, equity, bars and weights use the existing tables. The same engine
  writes them.

## Flow
Today page, refresh. The route submits a `proposal` job. The job calls
`advisor.propose()` with frames from `BarCache` (a fetcher is attached only
when credentials exist) and with account state from the paper broker, or from
the SQLite log when offline. The job writes rows to `proposals`. The page
polls `/api/proposal`.

Autopilot pass. The thread timer calls `Engine.rebalance()`, which calls
`advisor.propose()`. In `auto` mode the engine submits all deltas. In
`approve` mode the engine writes pending rows, sends a notification and
returns. When the user taps approve, `POST /api/autopilot {approve}` makes the
engine submit those rows only and mark them submitted.

What-if. The form posts to `POST /api/whatif`. The job calls `whatif.run()`,
which runs `Backtester` on cached real bars (or synthetic bars) with
contributions, then runs the benchmark. The result and the benchmark feed the
chart.

## External
- Alpaca (existing). Environment variables `ALPACA_API_KEY`,
  `ALPACA_API_SECRET`, `ALPACA_DATA_FEED`. The live gate is unchanged:
  `TRADEBOT_LIVE_CONFIRM`.
- Phone alerts. The existing `notify.webhook_url` points at an ntfy topic.
  This is documented and adds no dependency.
