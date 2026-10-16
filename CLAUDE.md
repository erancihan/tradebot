# CLAUDE.md: tradebot

Read this first, then `README.md` for the user tour. This file states the
current, final state of the project. Update it in the same change as the code,
and keep it at most 300 lines (`test_claude_md_stays_short`).

## What this is

A paper-trading-first equities bot in Python on Alpaca (free paper trading
and IEX data, no commission, $0 minimum). It has a trading core, a dry-run loop
with simulated fills, an arena that ranks algorithms, and a FastAPI dashboard.
The goal is a phone-first portfolio companion with three flows. **Suggestions**
say what to buy or sell today, with a reason. **Autopilot** runs the paper
account, with an approve-first mode. **What-if** replays a past plan against
buy and hold (decisions: `docs/adr/0002-portfolio-companion.md`). **Settings**
edits `config.yaml` from the phone. **History** shows what the bot ordered and
suggested. Research: `docs/research-record.md`. New work starts a new plan
folder under `docs/plans/<slug>/` (see Docs policy).

## Agent skills

Project skills live in `.claude/skills/`. Keep them in sync with this file.
- **tradebot-dev**: orientation, the dev loop, the pre-commit checklist. Start here.
- **add-strategy**: add a pluggable trading strategy.
- **add-arena-algo**: write an arena contestant or extend the arena.

## Layout

```
tradebot/
  strategies/    Strategy ABC + registry: sma_crossover, rsi_reversion, buy_and_hold,
                 donchian_breakout, macd_trend, bollinger_reversion, momentum,
                 supertrend, meta.py (follow_leader, ensemble_vote)
  indicators.py  risk.py (RiskManager + RiskConfig)  allocation.py  overlays.py
                 walkforward.py  portfolio.py  portfolio_pnl.py (round trips from fills)  models.py
  selection/     base, ranked (momentum, low_vol), regime (regime_switch), __init__ (SELECTORS)
  universe/      screen (LiquidityScreen), alpaca, discover    consortium/  voice, consensus, panel
  backtest/      result, runner (Backtester), steps (per-bar helpers shared by the
                 backtester and arena/simulation.py), flows (cash flows, growth index)
  whatif/        plan, run (run_whatif, whatif_risk, plan_window), compare, compare_many
  config.py      Settings (YAML), credentials.py (env only), config_io.py (EDITABLE_KEYS,
                 settings_to_dict, editable, write_settings: atomic, refuses secrets)
  notify.py      Notifier: Log, Null, Webhook, Ntfy, Multi, build_notifier; notify_actions (ntfy buttons)
  broker/        base (ABC), alpaca_broker (lazy SDK), dryrun + brackets (BracketsMixin)
  data/          synthetic (+ load_csv) + factor_panel, cache + coverage, replay, alpaca_data, stream
  market/        base (MarketCalendar, TableCalendar), us, bist, registry (CALENDARS)
  advisor/       propose (bars + account -> Proposal), explain, types, unlisted (off-list holdings)
  engine/        core (Engine.step -> PassOutcome), signals, orders, pending, session (daily-loss anchor),
                 fills (reconcile: Broker.order_status -> the order log's fill columns), unlisted
  autopilot/     state, schedule, runner (Autopilot, injected clock/sleep/calendar),
                 approvals, background, brief (MorningBrief), session, links (signed batch links)
  storage/       tradebot.db mixins: orders, bars, weights, proposals, autopilot, watchlist, discover
  cli/           build_parser/main + one module per command
  arena/         api, loader, interfaces, adapters, simulation, scenario, runner +
                 isolation, sandbox, scoring, gate/, result, tournament, league,
                 season/, panel, market, contestant, store + journal
  web/           app (create_app, load_settings), server, startup, guard, access, repository/,
                 schemas/, services/ account, advisor, autopilot (+ reset), autopilot_build, cache,
                   consortium, whatif_presets, notify_service, symbols_service, history_service (+ history_trades),
                   benchmark (+ _card), holdings_service, unlisted_service, discover_service, settings_service (view, save),
                   settings_validate, settings_secrets (mask alert targets), setup_service,
                   jobs/ {registry, frames, frames_many, backtest, dryrun, proposal, whatif,
                   whatif_compare, discover, catalog (strategy_catalog, stack_specs)}
                 routes/ pages, partials (+ history), sse, api/ {trading, arena, jobs (+ /stack), history (trades),
                   proposal, whatif (+ /compare), autopilot, notify, watchlist, discover, settings (+ /setup)}
                 templates/ pages (today, whatif, autopilot, history, settings, ...),
                   components (proposal_list, discover_card/_rows, watchlist, holdings, setup_card,
                   settings_*, autopilot_panel, whatif_compare, history_*, tabbar, ...)
                 static-src/ (PWA, committed), static/ (built, gitignored)
algos/           12 contestants + canaries/ and consortium/ (both opt-in)
scenarios/       regime library, factor library (xs_*), real_xs_* (+ sealed holdout), legacy real_*
frontend/        TypeScript, Tailwind, Alpine, ECharts, esbuild (settings[Form].ts, history.ts, discover.ts)
tests/  docs/ (research-record.md, adr/; plans/<slug>/ only while an epic is open)  data/cache/ (gitignored)  Makefile
config.example.yaml  .env.example  pyproject.toml ([dev], [live], [web])  deploy/ (systemd, launchd)
```

## Invariants

- **Paper by default.** Live trading needs `mode: live` and the env var `TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND`
  (`Settings.require_live_ack`). Never weaken this gate or default anything to live. The web never sets `mode`.
  Live trades only the list and never sells what it did not buy (`engine/unlisted.manages_unlisted`).
- **No look-ahead.** Targets shift one bar: decide on `t`, fill on `t+1`. The arena feeds a growing
  window. The allocator at fill bar `t+1` sees bars `<= t` only. Selector membership is computed over
  the full frame and shifted one bar. The sizing mark uses the fill bar's open (previous close as
  fallback), never the close of the bar being filled. Both loops import the one `_sizing_marks` helper.
  This choice was pre-registered: open over previous close, because the open is the actual fill price.
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
  levels. `models.opens_exposure` decides what counts as an entry, for both the engine and `DryRunBroker`.
- **Backtest == live.** `Backtester`, arena `simulate` and live `Engine` share
  `Strategy` and `RiskManager` and size the whole book in one `allocate` pass.
  `tests/test_arena_simulation.py` keeps the backtester and arena in lockstep.
  Change one loop, change the others. The one deliberate exception is bracket
  exits: the broker holds them, no simulation loop models them, and a backtest
  of a bracketed config shows the unbracketed result. Never quote a backtest as
  evidence about a stop. Do not add brackets to the backtester.
- **Import isolation.** The Alpaca SDK and `python-dotenv` load lazily inside functions. The trading core never imports `tradebot.web`.
- **Offline-first.** Everything except the literal Alpaca call runs and tests
  offline (synthetic data, fake fetchers). Every feature keeps a credential-free path and offline tests.
- **Credentials stay on the server.** The browser never receives them, and no
  config file holds them (`write_settings` refuses credential-looking keys). The
  web fetches bars through `BarCache`, except Discover's liquidity screen (one most-actives call plus a
  ~55-day batched bar request, keys only), and only with credentials in the server environment. Without them it uses cached bars and says so (`docs/adr/0001-server-side-refresh.md`).
- **Every result carries provenance:** source, symbols, window and bar count. Synthetic dates are labels, not forecasts.
- **No inline JS in templates.** All browser code is type-checked TypeScript bundled by esbuild. Templates only present data.

## Code rules

- Functions: at most 60 lines. Modules under `tradebot/`: at most 200 lines,
  aim for 150 (`tests/test_code_shape.py`). Test modules have no module limit.
- Split along section comments, one concern per file. Keep package re-exports so imports in `tests/` and `algos/` stay unchanged.
- Type hints, `from __future__ import annotations` everywhere; comments explain why.

## Dev commands

```bash
make install | install-web | install-all | test | demo | dryrun | arena | web  # :8000
cd frontend && npm run typecheck | test | build | watch:js           # after install-web
```
CLI: `tradebot {backtest,run,status,demo,arena,data,universe}`, `tradebot-web [--check]` (prints the startup line,
exits). Config: `--config`, else `$TRADEBOT_CONFIG`, else `./config.yaml`, else SPY/QQQ (`resolve_settings`; a Settings save creates it). Web db:
`--trading-db`, else `$TRADEBOT_DB`, else `db_path`, as `tradebot run`. `run --dry-run`/`--replay` forward-test.
Arena: `arena {list,run,validate,history,show,league,season,gate,journal}`,
`arena season {create,seed,list,standings,run}`. CI (`.github/workflows/ci.yml`)
runs offline pytest, `tsc --noEmit`, `npm test` and a build on every push and PR, no credentials.

## Conventions

- Core logic depends only on pandas and numpy. Adapters isolate Alpaca and FastAPI.
- Tests are offline and deterministic. Web tests use `pytest.importorskip("fastapi")`.
  `tests/conftest.py` fails any non-loopback socket and prints a simulated-balances ledger at the end.
- Web layering is strict: `routes -> services -> repository`. Partials serve
  first paint and Alpine polling. JSON endpoints feed charts.
- Never commit secrets, `*.db`, `data/cache/`, `node_modules/` or `tradebot/web/static/`.

## Gotchas

**Execution and data**
- **Change `advisor.propose`, not `Engine.rebalance`.** The engine calls
  `propose` and submits its lines, so a Today suggestion is exactly what a pass
  would trade (`test_propose_matches_engine_rebalance_deltas`).
- **Bad prices are flat.** NaN, inf or non-positive prices never reach sizing. All three loops skip the symbol (`math.floor(NaN)` raises).
- **Allocator history:** `aligned.iloc[:i]` at fill bar `i`. **ReplayData** advances once per step.
- **Selectors are prefix-stable** (verdict at `t` from bars `<= t` and earlier verdicts). A ranked
  walk starts from an empty set, so a truncated frame changes the verdict: the engine recomputes from
  full stored history (`Engine._selector_frames`), and `record_bars` upserts forming bars.
- **Composite selectors mask their own warmup** (`required_history - 1` rows).
  `exit_rank`: a held name stays droppable in any pool larger than `top_k`.
- **Cache coverage is a manifest** (`*.coverage.json`, gaps included) of the requested bounds:
  give `tradebot data pull` explicit `--start`/`--end`. Ranges are half-open (`_slice` drops the
  end date's 04:00/05:00 UTC session); changing that needs a migration. **A daily fetch never caches
  a forming bar:** `BarCache` clamps the end to the last completed session (US close; `clock` injected).
- **Cost model differs from production:** raw (not dividend-adjusted) bars, no daily-loss halt
  in simulation, 1 bp slippage, and synthetic `open(t) == close(t-1)` hides signal-to-fill decay.
  Label it beside any quoted backtest. **Window selection is a bias:** run the sealed holdout once, last.
- **Offline positions come from the order log** (signed sum per symbol for `settings.mode` via
  `storage.orders.effective_qty`: `filled_qty` when the broker has said, nothing for a cancelled,
  expired or rejected order beyond its partial fill, else the full `qty`), equity and cash from the
  newest snapshot, else `initial_cash`. Holdings use the same sum at the last cached close (unpriced
  = skipped, never guessed), or the paper broker with credentials. **Fills are learned by
  `engine/fills.reconcile`** (open orders of the last 7 days) at the start of each autopilot pass,
  in the Today refresh job (paper orders, with keys) and right after a submit; never on a page load.
- **History** shows `default_mode()`, else `settings.mode`, pinned by `?mode=` in its URLs; orders and batches page on a
  `(ts, id)` keyset each (`X-History-Next`). `orders.price` is the sizing price (NULL on a flatten or old row); `schema.migrate` adds a later column on open, the web never.
  The performance card compares with equal-weight buy and hold of today's active list from cached daily closes extended by
  the account's recorded daily bars, all but each symbol's newest (may be forming; cache wins a shared date; `benchmark_bars.py`,
  source `cache+recorded`), bought at the last close completed before the first snapshot (`services/benchmark.py`; `benchmark_card.py`:
  alpha from the snapshot at the benchmark's last close), no fetch; absent (noted) without bars or mixed accounts.
  **Trades** are round trips by average cost (`portfolio_pnl.book`) from filled orders only (`filled_orders`: `filled_qty > 0`, any status); hand trades never count, open ones show no P&L. `orders.intent` (entry | exit, NULL on old rows = opens as before): an exit with no trip to close is an `UnmatchedExit` ("Sold without a recorded buy"), never a short, never in the summary.
- **The Today refresh** gives the selector the whole cached history and the strategy the last `required_history + 30` bars, so engine and web can differ when their histories start on different days.
- **One list everywhere:** the watchlist when not empty, else `settings.symbols` (`storage/watchlist.resolve_active`;
  web `with_active_symbols`, a copy; `tradebot run` too, printing `symbols=watchlist(N)`). A watchlist edit stops a running
  autopilot (`autopilot_service.reset`), as a Settings save does. Symbols match `models.SYMBOL_RE` after upper-casing.
- **The autopilot manages exactly the list:** a held equity off the list gets a sell-to-flat line (`unlisted` in
  `advisor.propose`; `engine/unlisted.py`, web `unlisted_service`; no price = skipped; exits submit first; only
  `models.is_equity`: crypto and options are left alone by the engine, Today and the breaker's flatten). Never live;
  `manage_unlisted: false` turns it off. The 1% band is the product's (`Settings`, `risk.product_risk`, so a `tradebot
  backtest` of a Settings file uses it); the arena, what-if and the research record keep `RiskConfig()`'s 0.
- **Discover** ranks by the `MomentumSelector` score over the cached or Alpaca pool, excludes
  held and watched names, persists in `discover_runs`; Add seeds an empty watchlist first.
- **Contributions are not returns.** With `cash_flows` metrics use the growth
  index `equity_t / (equity_{t-1} + flow_t)`: a flow is invested at its bar's
  open and earns that bar. The arena never passes flows. What-if cash: month's first bar.
- **What-if books are fully investable** (`whatif_risk()`). The benchmark is
  equal-weight buy and hold with the same cash, so a buy-and-hold plan ties it.
- **Compare strategies** runs each strategy on defaults with the plan's allocator and selector,
  plus a tuned plan as `<name> (your settings)`; the server flags the plan's row (`plan`). Meta
  strategies (a roster) are skipped, a raising one is an `errors` entry, 120 s cap.

**Arena and season**
- **Isolation:** `process` is the default for `arena run`/`gate`; `season create` defaults to `thread`.
  `process` forks with a hard kill and never downgrades. `thread` is soft (marks `TIMEOUT`, cannot kill). `auto` warns before falling back.
  Never wrap a worker in a `ThreadPoolExecutor` context manager: its exit waits for the task.
- **Sandbox:** process isolation hardens by default (no writes, empty network
  namespace) unless `--no-harden`. `--seccomp` denies `execve`/`ptrace`
  last, after `no_new_privs`. An unenforceable tier (CI, macOS) logs one warning
  per mechanism. `--require-sandbox` makes it fatal. `sandbox.scrub_secrets`
  removes `ALPACA_*` and `TRADEBOT_LIVE_CONFIRM` from the child's environment.
- **`arena run` journals** into `--db` (default `./arena.db`). Tests pass
  `--db <tmp_path>` or `--no-journal`. `run_tournament` has no side effects.
- **The `algos/` head-count (12) is in tests** (`test_web.py`,
  `test_arena_season.py`, `test_arena_tournament.py`, `test_arena_journal.py`).
  `canaries/` and `consortium/` are subdirectories the loader glob skips.
- **Meta strategies are expensive:** `_TailBounded` caps each call to `2 x required_history`.
  Use `--time-budget 20`. Never trim a roster to fit a budget.
- **Fold scorers are in-sample for the analyst** (parameters chosen knowing the
  scenarios), and `worst_fold` alone has a trivial optimum (all cash = 0.0). Check a
  scenario for degeneracy first (`tests/test_scenario_library.py`).
- **A gauntlet must be balanced** (`MIRROR_PAIRS`). An unbalanced one gives a wrong
  verdict. One draw is a coin flip: use `arena gate --seeds N`, and fix the evaluation,
  never the data. The factor pool is fixed, joint, and the haven costs money to hold.
- **Season bars are the source of truth.** The `(season_id, symbol, ts)` key
  makes re-delivery idempotent. The feed backfills up to `catchup` (30) missed
  bars. Seed a new season (`arena season seed`). Backfilled standings are not a
  live-forward claim (`seeded_through`). Expensive fields need `--isolation
  process --time-budget N`. Hardening derives from isolation.
- **Consortium:** obeys every decision-rule invariant (guarded by `test_the_consortium_cannot_see_the_future`,
  `test_the_consensus_is_prefix_stable`). Convex blend, voice floor. Opt-in, run with `--time-budget 200`.
  `prepare` is idempotent on a frame fingerprint. `EqualVoice` is the default. State `eta` with any `HedgeVoice` result.

**Live execution and autopilot**
- **A bracket protects between passes, it does not veto a signal:** the next
  pass re-enters. `DryRunBroker` fills stop before target, gap-through at the
  open, and only on a bar *after* the entry bar (a parked replay would book a
  phantom exit each pass). Streaming only speeds bar arrival; the `Engine` polls.
- **A notifier never breaks a trade:** sends are wrapped, remote notifiers swallow errors. `deliver() -> bool` is only for the test-alert button ("not delivered").
- **A pending batch is re-sized or expired, never executed late:** a pass proposing the same
  `(symbol, action)` set refreshes it in place (sizing, prices, holds, `created_at`, so History and
  Today show its latest refresh time; same batch id, so the push's link still works). A rejection,
  even Skip of every line, holds until the proposal changes or the session day ends (`waiting_batch`).
  A changed proposal, an approval older than one `poll_seconds`, a failed pass, the first tick after
  the close (`tick` expires with no pass; so does a broker-closed pass), a halt, and switching off expire it. One push per batch and process (a restart pushes again:
  the link key may be new), plus a reminder every `links.ttl_seconds` (max(2 x poll, 30 min), also the
  link TTL) or at once when a refresh grows a line's notional past `GROWTH_TOLERANCE` (10%) of what the push said (`announced_*` state).
- **Signed batch links** (`autopilot/links.py`; buttons when `safe_public_url(notify.public_url)`)
  are paper-only (other pushes get just "Open") and account-bound (`account:batch:verb:exp`); they act
  on that account's pending lines under the lock (`Autopilot.act_on_batch`; foreign batch = 409). Key
  from `TRADEBOT_WEB_TOKEN`, else per-process; `ttl_seconds`; single use per process (after a
  restart a used link acts again until `exp`). They skip the cookie gate, not the guard. **The ntfy topic grants approval.**
- **The daily-loss breaker is per session day and flattens** (`engine/session.py`):
  each pass rolls the anchor when `now`'s exchange date changes (a replay's `now` is
  its newest bar); a breach closes every equity position and stays out that day. The
  autopilot also turns off; its anchor persists per scope (`autopilot/session.py`).
- **One lock, one connection:** the loop thread and web taps share the engine and SQLite
  (`check_same_thread=False`, WAL, `busy_timeout=5000`) under the Autopilot `RLock`. A line
  is `submitted` once the broker accepts it; later bookkeeping only logs. A mode switch wakes the loop.
- **The web autopilot is paper or dry-run, never live** (`autopilot_build`); a
  dry-run's account dies with a restart. `tradebot run --autopilot` builds as `run`, keeps
  state in scope `cli_<account>` (never the web's), expires no pending lines at start; a
  replay's clock reads its bars. Orders carry the pass clock, as batches do (approval: the tap's).
- **With a morning brief, "off" keeps the loop alive** to send briefs from `engine.propose` (nothing
  stored). `brief_for` prevents resends. A brief-only loop is `tradebot run --autopilot --mode off`.

**Web and CI**
- **The web writes `config.yaml` without comments. Secrets stay in `.env`**, read only from the
  working directory (`Path.cwd()`, never upward; launchd's `WorkingDirectory`), `DOTENV_KEYS` only. A save merges
  the editable keys into the file on disk (mode, db_path, costs, universe kept), validates by building
  every component, writes atomically, then `autopilot_service.reset` stops the loop (stored mode kept).
- **Alert destinations are masked both ways** (`settings_secrets`): a masked or omitted value keeps the
  stored one only while it still points at the same host or ntfy server; `""` deletes it. Settings responses are `Cache-Control: no-store`.
- **Alpine state is a Proxy:** `structuredClone` throws (copy with JSON); ECharts lives in a closure.
  An x-show chart box is 0 wide at init (`charts/fit.ts` `fitToBox`); `$store` bindings need `x-data`.
- **Pydantic coercion:** `JobRequest.params` stays `dict | None` (float coercion breaks ints).
- **Starlette:** `templates.TemplateResponse(request, name, context)`. Equity curves serialise as
  `{index: [...], equity: [...]}`. Dashboard refresh is one SSE stream into an Alpine `live` store.
- **State-changing requests need `X-Requested-With: tradebot`** (`web/guard.py`).
  Tests send `POST_HEADERS`, the TS client adds it in `postJson`. Middleware,
  outermost first: trusted host -> optional `TRADEBOT_WEB_TOKEN` gate -> guard.
  `POST /login` is the only guard exemption; signed batch links skip only the token gate. The token
  never rides in a URL. Test clients use `tests/web_client.local_client` (Host `localhost`).
- **The login body is bounded twice** (declared `Content-Length` <= 4096 and the
  streamed body). `test_web_guard.py` drives raw ASGI because clients fix lying lengths.
- **Chart axes drop the clock on daily data.** What-if presets are real when daily bars are
  cached (`MIN_SHARED_DAYS`), else labelled synthetic. **A green local suite is not a green CI.**

## Docs policy

- Documents state the final, expected state: once a question is answered, write the answer and what happens next, and delete the question. Keep only relevant documents.
- An epic's plan folder under `docs/plans/` is deleted as the epic ships. Durable
  decisions go to `docs/adr/`. Research results go to `docs/research-record.md`.

## Git rules

- Branch per epic: `feat/<epic>`. Merge into master with `git merge --no-ff --no-gpg-sign`.
- Every commit carries `--no-gpg-sign`. Never edit git config.

## Definition of done

- [ ] Tests added or updated; the suite and (for frontend changes) `npm run typecheck` are green.
- [ ] `tests/test_code_shape.py` passes. The offline, credential-free path still works.
- [ ] Every invariant holds. This file (<= 300 lines), `README.md` and the skills reflect the change.
