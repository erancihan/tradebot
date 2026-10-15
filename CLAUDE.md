# CLAUDE.md: tradebot

Read this first, then `README.md` for the user tour. This file states the
current, final state of the project. Update it in the same change as the code.

## What this is

A paper-trading-first equities bot in Python on Alpaca (free paper trading
and IEX data, no commission, $0 minimum). It has a trading core, a dry-run loop
with simulated fills, an arena that ranks algorithms, and a FastAPI dashboard.
The goal is a phone-first portfolio companion with three flows. **Suggestions**
say what to buy or sell today, with a reason. **Autopilot** runs the paper
account, with an approve-first mode. **What-if** replays a past plan against
buy and hold. Product: `docs/plans/portfolio-companion/01-product.md`.
Architecture: `02-architecture.md`. Status and roadmap: `00-status.md`.
Research results: `docs/research-record.md`.

## Agent skills

Project skills live in `.claude/skills/`. Keep them in sync with this file.
- **tradebot-dev**: orientation, the dev loop, the pre-commit checklist. Start here.
- **add-strategy**: add a pluggable trading strategy.
- **add-arena-algo**: write an arena contestant or extend the arena.

## Layout

Package layout. Every module stays under 200 lines (see Code rules).

```
tradebot/
  strategies/    Strategy ABC + registry: sma_crossover, rsi_reversion, buy_and_hold,
                 donchian_breakout, macd_trend, bollinger_reversion, momentum,
                 supertrend, meta.py (follow_leader, ensemble_vote)
  indicators.py  pure pandas indicators
  risk.py        RiskManager + RiskConfig (sizing, allocate, caps, band, daily loss, brackets)
  allocation.py  equal, inverse_vol, explicit      overlays.py  vol_target, sector_cap
  selection/     base, ranked (momentum, low_vol), regime (regime_switch), registry in __init__
  universe/      screen (LiquidityScreen), alpaca (AlpacaLiquidityUniverse)
  backtest/      result (BacktestResult), runner (Backtester), steps (shared per-bar
                 helpers used by BOTH the backtester and arena/simulation.py), flows
                 (cash flows + the flow-free growth index)
  whatif/        plan (WhatIfPlan, WhatIfResult, monthly_cash_flows), run (run_whatif,
                 plan_backtester, whatif_risk), compare (benchmark_plan, comparison)
  walkforward.py portfolio.py  models.py  config.py
  notify.py      Notifier: Log, Null, Webhook, Ntfy (phone push), Multi; build_notifier
  consortium/    voice, consensus, panel
  broker/        base (Broker ABC), alpaca (lazy SDK), dryrun + brackets (BracketsMixin)
  data/          synthetic + factor_panel, cache + coverage, replay, csv, alpaca_data, stream
  advisor/       propose (pure: bars + account -> Proposal of signed deltas), explain
                 (one-sentence reasons), types (Proposal, ProposalLine)
  engine/        core (Engine.step -> PassOutcome: halt, advisor.propose, submit or park
                 as pending; rebalance = step().actions; submit_lines), signals
                 (fetch_frames, selector_frames), orders (current_positions, submit_line),
                 pending (PassOutcome, record_pending, submit_stored)
  autopilot/     state (Mode off|approve|auto, AutopilotState, load/store), schedule
                 (next_pass, wait_seconds, session_day), runner (Autopilot: tick,
                 run_forever, start/stop thread; injected clock/sleep/is_open),
                 approvals (approve, reject, expiry, pending_trades notification)
  storage/       SQLite tradebot.db: schema, orders, bars, weights, proposals (batch header
                 + lines with a status), autopilot (autopilot_state scope/key/value)
                 (Storage = mixins; check_same_thread=False for the autopilot)
  cli/           __init__ (build_parser, main), common, demo, backtest, run, dryrun,
                 autopilot (run --autopilot, replay clock), status,
                 universe, data, arena, arena_history, arena_gate, arena_journal,
                 arena_league, season, season_run
  arena/         api, loader, interfaces, adapters, simulation, scenario, runner + isolation
                 (SubprocessRunner), sandbox, scoring, gate/ (measure, criteria, report,
                 evaluate), result, tournament, league, season/ (schema, config, store,
                 model, feeds, daemon), panel, market, contestant, store + journal
  web/           app (create_app + load_settings), server (--config), dependencies,
                 repository/ (trading, proposals, arena, season), services/ (account,
                 advisor (Today view + build_inputs), autopilot (one Autopilot per
                 process: view, set_mode, approve, reject, resume, shutdown),
                 autopilot_build (paper broker or dry-run over cached bars), cache,
                 consortium, whatif_presets, notify_service (test alert),
                 jobs/ {registry, frames, frames_many, backtest, dryrun, proposal, whatif,
                 catalog}), schemas/ (+ proposal, whatif), routes/ (pages incl. /today
                 /whatif and /autopilot, partials incl. /partials/proposal and
                 /partials/autopilot, sse, api/ {trading, arena, jobs, proposal, whatif,
                 autopilot, notify}), templates/ (pages/today.html, pages/whatif.html,
                 pages/autopilot.html, components/proposal_list.html,
                 components/autopilot_panel.html, components/pending_trades.html,
                 components/tabbar.html), app lifespan resumes/stops the autopilot,
                 static-src/ (PWA manifest + icons, committed), static/ (built, gitignored)
algos/           12 contestants + canaries/ and consortium/ (both opt-in)
scenarios/       regime library, factor library (xs_*), real_xs_* (+ sealed holdout), legacy real_*
frontend/        TypeScript, Tailwind, Alpine, ECharts, esbuild
tests/  docs/ (research-record.md, adr/, plans/)  data/cache/ (gitignored)
config.example.yaml  .env.example  pyproject.toml ([dev], [live], [web])  Makefile
```

A later epic adds `market/` (the `MarketCalendar` protocol).

## Invariants

- **Paper by default.** Live trading needs `mode: live` and the env var
  `TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND` (`Settings.require_live_ack`). Never
  weaken this gate or default anything to live.
- **No look-ahead.** Targets shift one bar: decide on `t`, fill on `t+1`. The
  arena feeds a growing window. The allocator at fill bar `t+1` sees bars
  `<= t` only. Selector membership is computed over the full frame and shifted
  one bar. The sizing mark uses the fill bar's open (previous close as
  fallback), never the close of the bar being filled. Both loops import the one
  `_sizing_marks` helper. This choice was pre-registered: open over previous
  close, because the open is the actual fill price.
- **Every shift has an absolute guard.** A lockstep test cannot catch an error
  made the same way in both loops. Each shift also has a single-engine test,
  for example `test_sizing_never_sees_the_fill_bars_close` and
  `test_selector_verdict_cannot_be_acted_on_the_bar_it_is_formed`. Each one
  fails with the shift deleted from both loops. A new shift gets a new guard.
- **Risk is centralised.** Strategies emit only `{-1, 0, +1}` and never size.
  Allocators propose weights. Selectors gate membership (non-members go flat)
  and never size or weight. `RiskManager.allocate` caps per name, scales the
  book to the gross cap order-independently, and is the only place weights
  become share quantities. The no-trade band is `RiskManager.material_delta`
  (full exits always execute). `RiskManager.bracket_prices` sets bracket
  levels. `models.opens_exposure` decides what counts as an entry, for both
  the engine and `DryRunBroker`.
- **Backtest == live.** `Backtester`, arena `simulate` and live `Engine` share
  `Strategy` and `RiskManager` and size the whole book in one `allocate` pass.
  `tests/test_arena_simulation.py` keeps the backtester and arena in lockstep.
  Change one loop, change the others. The one deliberate exception is bracket
  exits: the broker holds them, no simulation loop models them, and a backtest
  of a bracketed config shows the unbracketed result. Never quote a backtest as
  evidence about a stop. Do not add brackets to the backtester.
- **Import isolation.** The Alpaca SDK and `python-dotenv` load lazily inside
  functions. The trading core never imports `tradebot.web`.
- **Offline-first.** Everything except the literal Alpaca call runs and tests
  offline (synthetic data, fake fetchers). Every feature keeps a
  credential-free path and offline tests.
- **Credentials stay on the server.** The browser never receives them. The web
  layer fetches bars only through `BarCache` and only with credentials in the
  server environment. Without them it uses cached bars and says so. The old
  rule "the dashboard never fetches" is retired by
  `docs/adr/0001-server-side-refresh.md`.
- **Every result carries provenance.** Each simulation result states its
  source, symbols, window and bar count. Synthetic dates are axis labels, not
  forecasts.
- **No inline JS in templates.** All browser code is type-checked TypeScript
  bundled by esbuild. Templates only present data.

## Code rules

- Functions and methods: at most 60 lines. Modules under `tradebot/`: at most
  200 lines, aim for 150. `tests/test_code_shape.py` enforces both. Test
  modules have no module limit.
- Split along section comments, one concern per file. Keep package re-exports
  so imports in `tests/` and `algos/` stay unchanged.
- Type hints throughout, `from __future__ import annotations` in every module.
  Comments explain why, not what.

## Dev commands

```bash
make install | install-web | test | demo | dryrun | arena | web   # web serves :8000
cd frontend && npm run typecheck | build | watch:js                  # after install-web
```
CLI: `tradebot {backtest,run,status,demo,arena,data,universe}`, `tradebot-web
[--config PATH]` (default `./config.yaml` when present, else SPY/QQQ defaults).
`run --dry-run` and `run --replay` forward-test.
Arena: `arena {list,run,validate,history,show,league,season,gate,journal}`.
Season: `arena season {create,seed,list,standings,run}`.
CI (`.github/workflows/ci.yml`) runs offline pytest, `tsc --noEmit` and a
build on every push and PR, with no credentials.

## Conventions

- Core logic depends only on pandas and numpy. Adapters isolate Alpaca and
  FastAPI.
- Tests are offline and deterministic. Web tests use
  `pytest.importorskip("fastapi")`. `tests/conftest.py` fails any non-loopback
  socket and prints a simulated-balances ledger at the end.
- Web layering is strict: `routes -> services -> repository`. Partials serve
  first paint and Alpine polling. JSON endpoints feed charts.
- Never commit secrets, `*.db`, `data/cache/`, `node_modules/` or
  `tradebot/web/static/`.

## Gotchas

- **The forked contestant never sees broker secrets.** `sandbox.scrub_secrets` deletes `ALPACA_*` and `TRADEBOT_LIVE_CONFIRM` from the child's environment before contestant code runs. Hardening blocks writes and network, not reads of `os.environ`.

**Execution and data**
- **Engine and advisor share one code path; change `propose`, not
  `rebalance`.** `Engine.rebalance` fetches bars and positions, calls
  `advisor.propose` and submits the lines. Targets, the selector gate,
  weights, sizing, the band and rounding all live in `propose`, so a
  suggestion on the Today page is exactly what a pass would trade.
  `test_propose_matches_engine_rebalance_deltas` guards it.
- **Bad prices are flat.** NaN, inf or non-positive prices never reach sizing.
  `RiskManager` returns 0 for them and all three loops skip the symbol.
  `math.floor(NaN)` raises.
- **Allocator history.** Both loops pass the allocator `aligned.iloc[:i]` at
  fill bar `i`, over the same fillable symbols.
- **Selectors are prefix-stable.** The verdict at `t` depends only on bars
  `<= t` and earlier verdicts. Hysteresis state lives inside the membership
  walk, never in fills. The live engine keeps no selector state. It recomputes
  from the full stored history (`Engine._selector_frames`). A ranked walk
  starts from an empty set, so a truncated frame changes the verdict.
  `record_bars` is an upsert so a still-forming bar gets corrected.
- **Composite selectors mask their own warmup** (leading
  `required_history - 1` rows). A new composite needs the same guard.
- **`exit_rank`:** a held name stays droppable in any pool larger than `top_k`.
- **ReplayData cursor.** Advance it once per loop step, never inside
  `history()`. Keep warmups as integers.
- **Cache coverage is a manifest.** `BarCache` writes `*.coverage.json` next to
  each CSV. With a manifest, coverage comes from the manifest, gaps included.
  Without one, it falls back to observed bar timestamps. The manifest records
  the requested bounds, so give `tradebot data pull` an explicit `--start`
  and `--end`.
- **Cache ranges are half-open.** `_slice` excludes the end date's own
  session, because daily bars carry the 04:00/05:00 UTC open stamp. The
  shipped manifests depend on this. Changing it needs a manifest migration.
- **Cost model differs from production.** Cached bars are raw, not
  dividend-adjusted. `daily_loss_tripped` exists only in `engine.py`, not in
  the simulation loops. Scenarios use 1 bp slippage and no commission.
  `synthetic_ohlcv` sets `open(t) == close(t-1)`, so synthetic data hides
  signal-to-fill decay. Label this beside any quoted backtest.
- **Window selection is a bias.** The real windows were chosen knowing their
  history. The sealed holdout is the only mitigation. Run it once, last.
- **Offline positions come from the order log.** Without Alpaca credentials
  the dashboard positions card is empty, and the Today refresh derives
  positions by summing signed orders per symbol for the server's mode (every
  order is assumed filled in full, as in the dry-run broker). Equity and cash
  come from the newest equity snapshot for that mode, else `initial_cash`.
- **The Today refresh gives the selector the whole cached history** and the
  strategy only the last `required_history + 30` bars. A ranked selector's
  verdict depends on where its frame starts, so the engine (which reads its
  own stored bars) and the web refresh (which reads the bar cache) can pick
  differently when those histories start on different days.
- **Contributions are not returns.** `Backtester.run(..., cash_flows=...)` adds
  cash before a bar is sized. `BacktestResult` then reports `total_contributed`
  and `money_gain`, and computes return, CAGR, Sharpe and drawdown on the
  flow-free growth index (`backtest/flows.py`). With `cash_flows=None` every
  metric takes the old code path; the arena never passes flows. What-if
  contributions land on the first bar of each month after the first.
- **What-if books are fully investable:** `whatif_risk()` allows 100% in one
  name, fractional shares and a 0.5% no-trade band. The benchmark is
  equal-weight buy and hold with the same cash on the same bars, so a buy and
  hold plan ties it exactly.

**Arena**
- **Isolation modes.** `process` (default on POSIX) forks each contestant with
  a hard kill on timeout and optional `--cpu-seconds` / `--memory-mb`. It
  raises without fork and never downgrades. `thread` is the explicit soft
  mode: it marks `TIMEOUT` but cannot kill. `auto` prefers process and warns
  before it falls back. Never wrap a worker in a `ThreadPoolExecutor` context
  manager: its exit waits for the task and defeats the timeout.
- **Sandbox.** Process isolation hardens by default (no disk writes, empty
  network namespace). `--no-harden` opts out. `--seccomp` adds a libseccomp
  filter that denies `execve`, `execveat` and `ptrace`, applied last after
  `no_new_privs`. It leaves `clone`/`fork` open for the result queue thread.
- **An unenforceable sandbox tier is reported, not fatal.** CI runners,
  unprivileged containers and macOS refuse some mechanisms (macOS lacks
  `prctl` and `unshare`). The runner logs one warning per mechanism and
  continues. `--require-sandbox` restores the hard failure.
- **`arena run` journals by default** into `--db` (default `./arena.db`). Tests
  that call `main(["arena", "run", ...])` pass `--db <tmp_path>` or
  `--no-journal`. The library `run_tournament` has no side effects.
- **The `algos/` head-count (12) is in tests:** `test_web.py`,
  `test_arena_season.py`, `test_arena_tournament.py`, `test_arena_journal.py`.
  Adding or removing a contestant means updating them.
  `algos/canaries/` and `algos/consortium/` are subdirectories, so the
  non-recursive loader glob skips them.
- **Meta strategies are expensive.** `_TailBounded` caps each call to a
  `2 x required_history` tail. Multi-symbol scenarios need `--time-budget 20`.
  Never trim a roster to fit a budget.
- **Fold scorers are in-sample for the analyst.** Contestants are causal, so
  folds are out-of-sample for the algorithm. The researcher chose every
  parameter knowing these scenarios. `worst_fold` alone has a trivial optimum:
  all cash scores 0.0. Use it only next to a return check.
- **Check a scenario for degeneracy before you trust it.**
  `tests/test_scenario_library.py` asserts for every `xs_*` scenario:
  `top_k < pool size`, membership varies, and two selectors disagree on at
  least 20% of live bars. Single-symbol scenarios are 0% selector-active.
- **A gauntlet must be balanced.** Every rewarding scenario has a punishing
  mirror that differs by one parameter (`MIRROR_PAIRS`). An unbalanced set
  gives a wrong verdict, not a weak one.
- **One draw is a coin flip.** Momentum beats the random canary in half the
  draws. Use `arena gate --seeds N`. Fix the evaluation, never the data.
- **The factor pool is fixed and joint.** One market factor drives all names,
  the pool never changes per scenario, and the haven costs money to hold.

**Season**
- **Bars are the source of truth.** A season persists only bars and standings
  snapshots and re-ranks the field each tick. The `(season_id, symbol, ts)` key
  makes re-delivered bars idempotent, so a restart heals history.
- **The feed delivers every missed bar,** up to `catchup` (default 30). A
  longer outage needs a re-seed.
- **Seed a new season** with `arena season seed <id> --start .. --end ..`.
  `MomentumSelector(lookback=60)` is flat for 61 bars. Backfilled standings
  are not a live-forward claim. `seeded_through` records the boundary.
- **Over-budget contestants pile up threads** on the default `thread`
  isolation. For an expensive field, create the season with
  `--isolation process --time-budget N`, which makes the budget a hard kill.
  Hardening is derived from the isolation mode (`SeasonConfig.hardened`).

**Live execution**
- **A bracket protects between passes. It does not veto a signal.** After a
  stop fires and the strategy still says long, the next pass re-enters. A
  cooldown is a strategy decision. Brackets ride only on fills that add risk.
  `DryRunBroker` fills them pessimistically: stop before target on the same
  bar, gap-through fills at the open. `check_brackets` is duck-typed, not on
  the `Broker` ABC.
- **Streaming only speeds arrival.** `StreamSeasonFeed` buffers pushed bars into
  the pull-shaped feed. The `Engine` keeps polling on purpose.
- **A notifier never breaks a trade.** `Engine._notify` wraps every send and
  `WebhookNotifier` / `NtfyNotifier` swallow network errors. `build_notifier`
  always includes the log notifier (`notifier_channels` lists log, webhook,
  ntfy as configured). Both remote notifiers also have `deliver() -> bool`,
  used only by the test-alert button (`notify_service.send_test`), so a
  mistyped topic reads "not delivered" instead of a silent "sent".

**Consortium**
- **It obeys every decision-rule invariant.** `prepare()` sees the whole frame,
  so `test_the_consortium_cannot_see_the_future` and
  `test_the_consensus_is_prefix_stable` guard it. A member's result on bar `t`
  never changes its voice on bar `t`. The blend is convex, so it never levers
  past its members. Voice has a floor, so a silenced member recovers.
- **It is opt-in and costs the sum of its members.** Run it with
  `--algos ./algos ./algos/consortium --time-budget 200`. Self-exclusion uses
  the subdirectory and an `is_consortium` marker.
- **`Consortium.prepare` is idempotent** on a frame fingerprint. The
  consortium reaches `_prepare_components` as two objects, so identity dedup
  alone runs the panel twice.
- `EqualVoice` is the default. `HedgeVoice` and its `eta` are a research claim.
  State `eta` with any result.

**Autopilot**
- **A pending batch expires; it never executes late.** An approve-mode pass
  sizes its trades at that pass's prices. The next pass expires the previous
  batch before it proposes, an approval of a batch older than one
  `poll_seconds` expires it instead of submitting, and switching off expires
  whatever waits. Status `expired` exists for exactly this.
- **A daily-loss halt turns the autopilot off** (`last_error = "daily loss
  halt"`, an `autopilot_off` notification). Switching it back on the same day
  halts again on the first pass, because the engine's loss session is
  re-anchored only when the ET trading day changes (`Engine.reset_session`).
- **One lock, one connection.** The loop thread and the web's approve taps
  share the engine and its SQLite connection (`check_same_thread=False`);
  every Autopilot method holds its `RLock`. "Off" sets the stop event the
  default sleep waits on, so a loop sleeping until Monday's open exits at once.
- **The web autopilot is paper or dry-run, never live.** `autopilot_build`
  always uses the paper endpoint with credentials, else a `DryRunBroker` over
  cached bars parked at the newest shared date. Its in-memory virtual account
  does not survive a restart; the order log does.
- **`tradebot run --autopilot` builds the engine exactly as `run` does** (a
  live config still needs the latch). A replay gets a simulated clock: every
  bar is open, each sleep advances one bar, the tape's end stops the loop.

**Web and CI**
- **Pydantic coercion.** `dict[str, float]` turns integer params into floats
  and breaks `rolling`. `JobRequest.params` stays `dict | None`.
- **Starlette:** `templates.TemplateResponse(request, name, context)`. Equity
  curves serialise as `{index: [...], equity: [...]}`.
- **Keep ECharts instances out of Alpine state.** A proxied instance throws on
  multi-series updates; hold it in a closure variable (see `whatif.ts`).
- **Dashboard refresh** uses one SSE stream (`/sse/dashboard`) into an Alpine
  `live` store. SSE fits a read-only, server-to-client feed.
- **State-changing requests need `X-Requested-With: tradebot`; tests use
  `POST_HEADERS`** (from `web/guard.py`, which returns 403 without it: a
  cross-site form cannot set a custom header). The TS client adds it in
  `postJson`, so new mutating calls go through `api/client.ts`. Middleware,
  outermost first: trusted host (loopback default, `--allow-host` extends) ->
  optional `TRADEBOT_WEB_TOKEN` gate (`web/access.py`, cookie
  `tradebot_session` = HMAC of the token, or `Authorization: Bearer`) ->
  same-origin guard (`POST /login`, a plain form, is its only exemption;
  the token is never accepted in a URL). Build test clients with `tests/web_client.local_client`
  (Host `localhost`): `testserver` is deliberately not on the allowlist.
- **Chart axes drop the clock on daily data.** `equityChart.ts axisLabels`
  shows dates only when no two points share a date (daily bars carry a
  04:00/05:00 UTC session stamp that is noise); intraday series keep the time.
  Order pins use the same labels, so a pin always lands on an axis category.
- **The login body is bounded twice:** `Content-Length` must be present and at
  most 4096, and the streamed body may not exceed what it declared (a chunked
  body without a length gets 413). `test_web_guard.py` drives the raw ASGI app
  for these, because an HTTP client corrects a lying length.
- **What-if presets are real when anything daily is cached,** familiar index
  funds first, and only symbols that share at least 90 days with the rest
  (`whatif_presets.MIN_SHARED_DAYS`), so a preset never fails on first tap.
  An empty cache falls back to labelled synthetic presets.
- **A green local suite is not a green CI.** Check the actual CI run before
  you claim a gate passed.

## Docs policy

- Documents state the final, expected state. Once a question is answered or a
  decision made, write the answer and what happens next. Delete the question.
- Keep only relevant documents. Keep a paper trail only for what is done and
  for the end goal. Everything in between is noise.
- An epic's plan folder under `docs/plans/` is deleted as the epic ships.
  Durable decisions go to `docs/adr/`. Research results go to
  `docs/research-record.md`.

## Git rules

- Branch per epic: `feat/<epic>`. Merge into master with
  `git merge --no-ff --no-gpg-sign`.
- Every commit carries `--no-gpg-sign`. Never edit git config.

## Definition of done

- [ ] Tests added or updated. The suite is green, and `npm run typecheck` too
      for frontend changes.
- [ ] `tests/test_code_shape.py` passes.
- [ ] The offline, credential-free path still works.
- [ ] Every invariant above holds.
- [ ] This file, `README.md` and the skills reflect the change.
