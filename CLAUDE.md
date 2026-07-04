# CLAUDE.md — tradebot

Onboarding for an AI agent (or human) picking up this project. Read this first,
then skim `README.md` for the user-facing tour.

> **Keep this file updated.** Whenever you add a feature, change an invariant,
> learn a gotcha, or finish a roadmap item, update the relevant section below in
> the same change. Treat CLAUDE.md as part of the definition of done — a stale
> onboarding doc is worse than none. (There's a checklist at the bottom.)

---

## What this is

A **paper-trading-first** equities trading bot in Python, built on Alpaca
(commission-free, free paper trading + IEX data, $0 minimum). Greenfield, lives
entirely under `trading-bot/`. Four pillars:

1. **Trading core** — strategies, risk, backtester, broker/data adapters, CLI.
2. **Dry-run** — real-time loop with *simulated* fills against a virtual account.
3. **Arena** — load algorithms dynamically and rank them in competitions.
4. **Web dashboard** — FastAPI + TS/Tailwind/Alpine/ECharts; monitor + run sims.

Status: feature-complete for the core vision **including the portfolio stack**
(universe → selector → allocator → risk; see Roadmap); the **algorithms-research
arc's tooling is COMPLETE** (regime scenario library + robustness scorers +
classic roster + experiment journal + cross-sectional portfolio contestants +
meta strategies + promotion pass gate; no contestant has passed the gate yet —
see Roadmap arc status). **~250 tests, all offline & green** (web tests skip
without fastapi); frontend has a strict `tsc` gate.

## Agent skills

Project-scoped Claude Code skills live in `trading-bot/.claude/skills/`:
- **tradebot-dev** — orientation + the dev/test/build loop and the pre-commit
  checklist. Start here.
- **add-strategy** — add a pluggable trading strategy.
- **add-arena-algo** — write an arena contestant or extend the arena.

Keep these in sync when workflows or invariants change.

## Layout

```
trading-bot/
├── tradebot/                 # the Python package
│   ├── strategies/           # Strategy ABC + sma_crossover, rsi_reversion, buy_and_hold,
│   │                         #   donchian_breakout, macd_trend, bollinger_reversion,
│   │                         #   meta.py (follow_leader bandit + ensemble_vote)
│   ├── indicators.py         # pure pandas: sma/ema/rsi/macd/bollinger/rolling_volatility/crossover
│   ├── risk.py               # RiskManager + RiskConfig (sizing, allocate(), caps, band, daily-loss)
│   ├── allocation.py         # Allocator ABC + equal/inverse_vol/explicit + registry
│   ├── selection.py          # Selector/RankedSelector ABCs + momentum (reverse=reversal)
│   │                         #   + low_vol top-K w/ hysteresis + registry
│   ├── universe.py           # LiquidityScreen + AlpacaLiquidityUniverse (lazy, injectable)
│   ├── overlays.py           # Overlay ABC + vol_target/sector_cap (reduce-only) + registry
│   ├── walkforward.py        # fold-based out-of-sample evaluation (backtest --walk-forward)
│   ├── portfolio.py          # cost-basis + realised-PnL accounting (sim)
│   ├── backtest.py           # Backtester + BacktestResult (metrics)
│   ├── models.py             # Order/Fill/Position/Trade/Side, BAR_COLUMNS, utcnow
│   ├── broker/               # Broker ABC, AlpacaBroker (lazy SDK), DryRunBroker
│   ├── data/                 # synthetic, csv loader, ReplayData, AlpacaData, BarCache
│   ├── engine.py             # live/paper/dry-run rebalance loop
│   ├── storage.py            # SQLite: orders + equity snapshots + bars (tradebot.db)
│   ├── config.py             # Settings (YAML) + AlpacaCredentials (env) + live gate
│   ├── cli.py                # `tradebot` entrypoint (argparse)
│   ├── arena/                # competition system (see below)
│   └── web/                  # FastAPI dashboard (see below)
├── algos/                    # example arena contestants + how-to README
├── scenarios/                # arena scenario YAMLs incl. the regime library
│                             #   (bull_trend/sideways_chop/crash_recovery/vol_spike)
├── frontend/                 # TS + Tailwind + esbuild source for the dashboard
├── tests/                    # pytest (offline; web tests importorskip fastapi)
├── pyproject.toml            # deps + extras: [dev], [live], [web]; scripts
└── Makefile                  # install / test / demo / dryrun / arena / web
```

`tradebot/arena/`: `api.py` (@register), `loader.py` (importlib discovery),
`interfaces.py` (Algo/Action/Context/PortfolioAlgo), `adapters.py` (Policy +
simulation_args), `simulation.py` (stepped core), `scenario.py`, `runner.py`,
`scoring.py` (incl. worst_fold/consistency), `gate.py` (promotion pass gate),
`result.py`, `tournament.py`, `league.py` (standings over a season),
`season.py` (durable, resumable real-time league + feeds + daemon),
`market.py` (US market-hours + partial-bar helpers), `sandbox.py`
(`--harden`: no-write + net isolation), `store.py` (runs + experiments
journal).

`tradebot/web/`: `app.py` (factory), `repository.py` (read-only SQLite),
`services/` (metrics, account, jobs), `routes/` (pages, partials, api),
`schemas.py` (Pydantic), `templates/` (Jinja, componentised), `static/` (built,
gitignored).

## Invariants — do not break these

- **Paper by default.** Live trading requires `mode: live` *and* env
  `TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND` (`config.Settings.require_live_ack`). Never
  weaken this gate or default anything to live.
- **No look-ahead.** Backtester shifts targets by one bar (decide on `t`, fill on
  `t+1`). The arena feeds a *growing window* so the future is physically invisible.
  Allocation weights obey the same shift: at fill bar `t+1` the allocator only
  sees bars `≤ t` (guarded by `test_allocator_never_sees_the_fill_bar`).
- **Risk is centralised.** All sizing/limits go through `RiskManager`; strategies
  only emit targets in `{-1, 0, +1}`. Don't let strategies size positions.
  Allocators (`allocation.py`) only *propose* weights; `RiskManager.allocate`
  caps them per-name, scales the book to the gross cap (order-independent), and
  is the only place weights become share quantities. Selectors (`selection.py`)
  only *gate* membership (force non-members flat); they never size or weight.
  The no-trade band lives in `RiskManager.material_delta` (full exits always
  execute), shared by all three loops.
- **Backtest == live.** Backtester and live `Engine` share the same `Strategy` +
  `RiskManager`. The arena's stepped `simulation.simulate` must stay consistent
  with `Backtester` — guarded by `tests/test_arena_simulation.py`. If you touch
  either execution loop, keep that test green.
- **Import isolation.** The Alpaca SDK and `python-dotenv` are imported *lazily*
  (inside methods/functions), so the core works without them. The whole `web/`
  package must not be imported by the trading core. Keep these boundaries.
- **Offline-first.** Everything except the literal Alpaca network call runs and
  tests offline (synthetic data, fake fetchers). New features must keep a
  credential-free path and offline tests.
- **No inline JS in templates.** All browser behaviour is imported, type-checked
  TS bundled by esbuild. Templates only present data.

## Dev environment & commands

Python (works offline; no creds needed for tests/demos):
```bash
cd trading-bot
make install            # venv .venv + pip install -e ".[dev]"
make install-web        # adds [web] extra + npm install (for the dashboard)
make test               # pytest (web tests skip if fastapi absent)
make demo               # offline backtest on synthetic data
make dryrun             # offline forward-test (replay)
make arena              # run the example competition
make web                # build frontend + serve dashboard at :8000
```
CLI: `tradebot {backtest,run,status,demo,arena,data}` and `tradebot-web`.
`run --dry-run`/`--replay` = forward-test; `arena {list,run,validate,history,show}`.
`make test` ends with a **simulated balances** ledger (start → final per money
test; `tests/conftest.py` wraps `Backtester.run` + arena `simulate`).

Frontend (`trading-bot/frontend/`):
```bash
npm run typecheck       # strict tsc --noEmit (CI gate)
npm run build           # -> tradebot/web/static/{js,css} (minified, gitignored)
npm run watch:js        # dev rebuild on change
```
Stack: TypeScript, Alpine.js, Apache ECharts, Tailwind, esbuild. Built assets are
gitignored — reproduce with `npm run build`.

CI: `.github/workflows/trading-bot-ci.yml` runs pytest + (npm ci, typecheck,
build) on changes under `trading-bot/**`.

## Conventions

- Match the surrounding style; comments explain *why*, not *what*. Type hints
  throughout. `from __future__ import annotations` at the top of modules.
- Core logic (indicators/strategies/risk/backtest/arena) depends only on
  pandas+numpy. Adapters isolate Alpaca/FastAPI.
- Tests are offline and deterministic (seeded synthetic data, fake fetchers).
  Web/job tests `pytest.importorskip("fastapi")`.
- Web layering is strict: `routes → services → repository`. Partials are reused
  for both first paint and Alpine polling. JSON endpoints feed charts.
- Commits: clear messages; do not commit secrets, `*.db`, `data/cache/`,
  `node_modules/`, or `tradebot/web/static/` (all gitignored).

## Gotchas / lessons learned

- **Arena isolation & timeouts.** `arena/runner.py` has two runners behind the
  `Runner` protocol, chosen by `default_runner`:
  - `SubprocessRunner` (**default** on POSIX, `--isolation process`): each
    contestant runs in a forked process with a **hard** wall-clock timeout (the
    process is killed on expiry) + optional CPU/memory `rlimit`s
    (`--cpu-seconds` / `--memory-mb`). A runaway/hostile algo can't stall the
    tournament or keep burning CPU. Results return via a `Queue` (consume with
    the budget to avoid the queue-not-drained deadlock).
  - `InProcessRunner` (`--isolation thread`): portable **soft** runner — a
    daemon thread + `join(timeout)`; marks `TIMEOUT` but can't force-kill the
    thread (the daemon keeps running in the background; never blocks exit).
  Modes (`default_runner`): `process` (default) **raises** if fork is unavailable
  — it never silently downgrades hard→soft; `thread` is the explicit soft opt-in;
  `auto` prefers process and warns before falling back to soft.
  Lesson: never wrap a worker in a `ThreadPoolExecutor` context manager — its
  `__exit__` does `shutdown(wait=True)` and blocks until the (uninterruptible)
  task ends, silently defeating the timeout.
  Subprocess uses `fork` (args passed by inherited memory, so non-picklable
  contestant factories/frames are fine; only the result is pickled back).
  Hardening (`sandbox.py`) is **ON by default** for process isolation
  (`run_tournament`/`run_league`/`default_runner` default `harden=True`,
  `--no-harden` to opt out): the child gets no disk writes + a fresh empty net
  namespace. The **seccomp** tier is opt-in (`--seccomp`, default off): on top of
  hardening it loads a `libseccomp` filter (via ctypes, `libseccomp.so.2`)
  denying `execve`/`execveat`/`ptrace` with `EPERM`, so a contestant can't shell
  out (`subprocess`/`os.system`) or trace another process. It is applied **last**
  in `apply_hardening` and forces `no_new_privs` on first (an unprivileged
  seccomp load requires it); it deliberately does **not** block `clone`/`fork`
  (multiprocessing's result-queue feeder thread needs it). The continuous
  `season` recompute runs on `thread` isolation for speed (can't sandbox) and
  passes `harden=False` explicitly.
- **Pydantic coercion:** typing a request field `dict[str, float]` coerces
  integer params (e.g. `fast`, `period`) to floats and breaks `rolling`/`.iloc`.
  `web/schemas.py JobRequest.params` is deliberately left untyped (`dict | None`).
- **Starlette TemplateResponse:** current Starlette requires the request-first
  signature `templates.TemplateResponse(request, name, context)`. The legacy
  `(name, context)` form mis-parses the context dict as the template name.
- **ReplayData cursor:** advance the replay cursor exactly once per loop step
  (the engine does many `history()` calls per pass); never auto-advance in
  `history()`. Keep `required_history`/warmup integers.
- **Equity-curve charts:** the arena/job equity is serialised as
  `{index: [...], equity: [...]}` JSON; persisted in arena_results, returned by
  job/arena APIs.
- **Joint allocation replaced per-symbol clamping.** The Backtester, arena
  `simulate`, and `Engine.rebalance` all size the whole book in one
  `RiskManager.allocate` pass (gather targets/prices → weights → quantities).
  The old first-come-first-served `clamp_to_exposure` loop is gone from the
  execution paths (the primitive remains for direct use); if the book is
  over-subscribed the *desired* weights are scaled down, which can force
  reductions — that is intended rebalancing, not a bug. Keep all three loops
  identical (guarded by `test_simulate_matches_backtester_with_allocator`).
- **Allocator history slicing:** in both backtest and arena loops the allocator
  is called at the *fill* bar `i` with `aligned.iloc[:i]` — bars strictly before
  the fill — over the same fillable-symbol set in both engines. Change one,
  change the other, or the lockstep test fails.
- **Selectors must be prefix-stable** (verdict at `t` depends only on bars
  `≤ t` + earlier verdicts, so a prefix recompute reproduces the prefix —
  guarded by `test_membership_is_prefix_stable_no_lookahead`). That property is
  load-bearing twice: the backtest/arena loops *precompute* `membership()` over
  the full frame and `.shift(1)` it (fill bar `t+1` sees the verdict from `t`),
  and the live engine keeps **no selector state** — it recomputes from full
  fetched history every pass (bars are the source of truth, like the season).
  Hysteresis state (`held`) lives inside the membership walk, derived from data
  only — never from fills. Selector gating happens BEFORE the allocator is
  consulted, so weights are distributed over members only.
- **Season = bars are source of truth.** A live `Season` (`season.py`) persists
  only the accumulated bars (+ a standings snapshot per tick) to SQLite; each
  tick re-ranks the field with `run_tournament(..., frames=accumulated)`. No
  per-contestant state is stored, so resume = reload bars and keep stepping;
  duplicate bars are idempotent (PK `(season_id, symbol, ts)`), so re-feeding old
  bars from a live feed is harmless. Recompute is O(history)/tick — fine for
  daily cadence; the default isolation is `thread` (light, re-evaluates data the
  contestants already survived).
- **`algos/` head-count is baked into a few tests.** The web/season fixtures run
  a tournament over the whole `algos/` dir; `test_web.py` (arena run entries,
  season standings), `test_arena_season.py` (name set) and
  `test_arena_journal.py` ("Journaled N") assert on the field. Adding/removing
  an example contestant means updating those counts (currently 11).
- **Fold scorers assume fixed parameters.** `worst_fold`/`consistency` treat
  segments of the *realized* equity curve as out-of-sample folds. That's valid
  while contestants don't fit anything during a run. If a contestant ever
  optimizes in-run, its early folds become in-sample — use `walkforward.py`
  with true refits instead.
- **`arena run` writes the journal by default.** Every CLI tournament records
  attempts into `--db` (default `./arena.db`). Tests that invoke
  `main(["arena", "run", ...])` must pass `--db <tmp_path>` (or `--no-journal`)
  or they'll litter the CWD. Journaling is CLI-layer only — the library
  `run_tournament` has no side effects (the season recompute loop depends on
  that).
- **Meta strategies are expensive under the growing-window replay.** The arena
  calls `latest_target` per bar per symbol and a meta recomputes its whole
  roster each call. `_TailBounded` (strategies/meta.py) caps that call to a
  `2×required_history` tail — same bounded-history semantics the live engine
  has always had — turning O(bars²·subs) into O(bars·subs). The constant is
  still ~a roster-multiple of a plain contestant (profiled: each classic sub
  costs 0.5–1.0 ms/call), so on multi-symbol scenarios (cross_sectional: 6
  symbols × 500 bars ≈ 3000 calls) the metas need `--time-budget 20`; the
  single-symbol scenarios fit the default 10s. Don't "fix" this by trimming
  the roster to fit the budget — that's fitting to the harness.
- **Season + over-budget contestants = thread pile-up.** The season recompute
  is O(history) *per tick* on `thread` isolation, and the soft runner cannot
  kill a running contestant — an over-budget algo leaks a busy daemon thread
  *every tick* until the loop crawls. Keep season fields to affordable
  contestants (or short replays); the 10-min season replay timeout seen on
  2026-07-04 was exactly this with `meta_leader` in the field.

## Roadmap

Done: trading core · dry-run · arena (loading, both interfaces, Alpaca cache,
persistence, **hard subprocess isolation** w/ kill-on-timeout + CPU/mem limits,
**strict isolation modes** — process/thread/auto, no silent downgrade,
**sandbox ON by default** for process isolation: no disk writes +
network-namespace isolation, `--no-harden` to opt out; **seccomp tier**
`--seccomp` blocks `execve`/`ptrace`) ·
dashboard (equity+orders+positions+leaderboards, order markers, browser-run
backtests/dry-runs, **candlestick price chart** w/ order markers, **live account
header + dashboard auto-refresh** w/ pause + last-updated, `/api/account`) · CI ·
arena **league** (`arena league` — standings evolve
over a replayed season) · durable **season** (`arena season` — resumable
real-time league: SQLite bars/standings that survive restarts; replay feed +
thin live Alpaca feed) · **season daemon** (`market.py` market-hours gating +
next_open + partial-bar drop, supervised loop with **injected clock/sleep** so
the whole loop is dry-run-testable offline via `season run --simulate`,
`/seasons` dashboard standings view) · **portfolio foundation** (weight-aware
`RiskManager.target_qty` + joint order-independent `RiskManager.allocate` in
all three execution loops; `allocation.py` allocator registry — `equal`,
`inverse_vol`, `explicit` — wired via the `portfolio:` config block; target
weights persisted to `target_weights` in SQLite) · **cross-sectional selector**
(`selection.py` `MomentumSelector` — 12-1 style trailing-return rank, hold
top-K, `exit_rank` hysteresis; gates strategy targets in all three loops with
the one-bar shift; `buy_and_hold` strategy as the selector-only signal;
`portfolio.selector` config block; `demo --portfolio` showcase) · **no-trade
rebalancing band** (`RiskConfig.rebalance_band_pct` via
`RiskManager.material_delta`, exits always execute; ~10× turnover cut in the
demo) · **Alpaca-backed universe** (`universe.py`: `LiquidityScreen` — min
price + rolling-ADV floor, ranked by ADV, `max_symbols` cap; pure pandas,
offline-tested — and `AlpacaLiquidityUniverse`: most-actives shortlist →
`get_all_assets` active+tradable filter → batched `history_many` bars → screen;
all fetchers lazy AND constructor-injectable for offline tests; `universe:`
config block replaces `symbols` at startup — replay ignores it; `tradebot
universe` preview command; snapshots persisted to `universe_snapshots`) ·
**dashboard allocations view** (`/api/allocations` + `/partials/allocations`
+ "Target allocations" card on the dashboard: weight bars for the latest
rebalance + the resolved candidate universe as chips; server-rendered partial,
refreshes via the existing partialLoader — zero new TS) · **overlays**
(`overlays.py`: reduce-only weight transforms chained between allocator and
RiskManager — `sector_cap` w/ inline map or CSV + conservative "other" bucket
for unmapped names, `vol_target` exposure dial that scales down when realized
book vol exceeds target and never levers up; `portfolio.overlays` config list;
engine records POST-overlay weights) · **walk-forward evaluation**
(`walkforward.py` + `backtest --walk-forward N`: contiguous out-of-sample
folds, each warmed up with `required_warmup` — the max `required_history`
across strategy/selector/allocator/overlays — per-fold metrics + dispersion).

**Portfolio expansion — DONE** (owner-approved 2026-07; investigation report in
the session notes). All locked stages shipped: foundation → weighting schemes →
momentum selector + band → Alpaca liquidity-screen universe → dashboard view →
overlays + walk-forward. Honesty regime stands: live-forward paper; historical
backtests over a current-membership universe must be labelled
survivorship-biased.
Non-goals (do not re-propose): mean-variance/Markowitz optimizers (error
maximizer), Black-Litterman, fundamentals/value screens (no Alpaca data),
shorting by default, yfinance as a real dependency.

**Next arc — algorithms research** (owner request 2026-07): build agents and
algorithms that run ON this system. The arena is the harness (contestants →
tournaments → league → season → promote to paper via the trading core). See
the session plan; key rule: every new algo ships with offline tests + a
walk-forward pass, and multiple-testing honesty (count what you tried).
Promotion pipeline: contestant → `arena validate` → tournaments across the
regime scenario library → replay league → walk-forward → pass gate (positive
worst fold, beats `buy_and_hold` net of costs, drawdown in bounds) → register
as a core `Strategy` → paper dry-run → paper season.
*Stage 1 — research lab (DONE):* **robustness scorers** (`worst_fold`,
`consistency` in `arena/scoring.py` — split the realized equity curve into
contiguous folds; valid as out-of-sample because contestants have fixed
params, nothing is fit mid-run) · **regime scenario library**
(`synthetic_regime_ohlcv` piecewise drift/vol segments, continuous price path;
`Scenario.regimes`; four shipped YAMLs) · **classic roster** (donchian_breakout,
macd_trend, bollinger_reversion strategies + macd/bollinger_bands indicators +
`algos/` contestants: donchian, macd_cross, bollinger_dip — each with offline
tests + a walk-forward smoke pass). Verified end-to-end: the library
discriminates as theory predicts (trend-followers top the bull scenario,
mean-reverters top the chop by `consistency`, buy_and_hold sinks in
crash_recovery by `worst_fold`).
*Stage 2 — experiment journal (DONE):* every `arena run` journals one attempt
per contestant into the arena DB's `experiments` table (`--no-journal` opts
out; failures count too). Each attempt records its **start/final balance and
simulated data window** next to the score (additive-column migration upgrades
older DBs on open; pre-migration rows print "-"); `arena journal` shows all
three — scores rank, dollars-over-a-window tell the story. The `make test`
balance ledger shows the same period per simulated run. `@register(..., family=...)` groups variants of one
idea so attempts accumulate against the family (default: the contestant name).
`tradebot arena journal [--family X]` prints the ledger + a multiple-testing
reminder once any family passes one attempt. `ArenaStore.record_attempts` /
`journal_summary` / `journal_entries`.
*Stage 3 — cross-sectional contestants (DONE):* **`PortfolioAlgo`** third
contestant interface (`arena/interfaces.py`) — a whole book (strategy +
selector + allocator + optional overlays) competes as ONE entry, `kind=
"portfolio"`; `adapters.simulation_args` hands the stack to `simulate`, which
already ran it (lockstep with the Backtester guarded by
`test_arena_portfolio.py`). Sizing stays with the tournament's shared
RiskManager. New selectors: `MomentumSelector(reverse=True)` = short-term
reversal (hold the losers), `LowVolatilitySelector` (`low_vol`) — both on the
shared `RankedSelector` walk (prefix-stable by construction).
`Scenario.symbol_overrides` gives the plain-synthetic pool a per-symbol
drift/vol spread (`scenarios/cross_sectional.yaml`; ignored when `regimes`
set). Examples: `algos/xs_momentum.py`, `algos/xs_reversal.py`. Verified:
xs_momentum finds the persistent leaders and beats buy_and_hold on the spread
scenario.
*Stage 4 — adaptive/meta algos (DONE):* `strategies/meta.py` —
`FollowTheLeader` (greedy bandit: per bar, trade the sub-strategy with the
best trailing-window P&L, computed with the same one-bar shift as execution;
prefix-stable; ties → roster order) and `EnsembleVote` (long/short only when
`min_agree` sub-strategies agree; default strict majority; long wins the
impossible tie). Both accept `strategies:` as instances or `{name, params}`
dicts (lazy registry import avoids the cycle); default roster = mixed
trend/reversion four. Contestants: `algos/meta_leader.py`, `meta_vote.py`.
*Stage 5 — pass gate + runbook (DONE):* `arena/gate.py` `evaluate_gate` +
`tradebot arena gate --candidate X --scenarios ...` — judges a candidate vs a
baseline (default `buy_and_hold`) over a scenario gauntlet; checks: completes
everywhere · beats baseline mean return · `worst_fold` >= baseline in a
strict majority · drawdown never worse than `--max-drawdown` (default 35%).
Exit code = verdict; runs are journaled; the family's attempt count prints
with the verdict. Runbook in README (validate → gate → walk-forward → replay
dry-run → paper/season).
**Arc status (2026-07-04): tooling complete; NO contestant has passed the
gate yet — that is the honest result, not a bug.** Gauntlet outcomes: classics
protect drawdown but concede too much return vs buy_and_hold; raw
`xs_momentum` beats mean return but takes a −48% momentum-crash drawdown;
`xs_momentum_vt` (the vol-dialed variant, one theory-driven iteration: target
= benchmark vol so the dial only acts on true spikes) passes mean-return +
drawdown but loses the worst-fold majority 2/5 — two losses are ~30bps
selector-warmup drag, one real (vol_spike: the dial de-risked a spike the
market rallied through). Journal: `xs_momentum` family at 55 attempts. Do NOT
tune the gate or grid-search params to force a pass; the next iteration must
be theory-driven. **Fold attribution (2026-07-04, don't re-chase):** the three
worst-fold losses are (a) bull_trend: a 1-basis-point tie in fold 2 — noise,
warmup drag sits in fold 1 which is NOT the worst fold, so a warmup-hold
selector feature would not flip it; (b) cross_sectional: −1.35% vs −1.15% in a
shared dip — the inherent cost of top-2 concentration (fold 4 shows the
payoff: +19.9% vs +3.9%); (c) vol_spike: the dial's definitional trade-off.
Conclusion: this candidate's remaining gaps are structural trade-offs, not
bugs; new gate attempts need a *different idea*, not another parameter. Promotion mechanics verified offline end-to-end: the exact
candidate stack ran as a core config through `run --replay` (+7% on the
demo replay) and an 11-contestant replay season.

Deferred (decided, do not re-propose without a new ask):
- **Container/gVisor containment** — the strongest, OS-level tier, for fully
  untrusted third-party code. The in-process tiers escalate as: rlimits →
  `--harden` (no disk writes + net isolation) → `--seccomp` (deny
  `execve`/`ptrace`); a container/gVisor runner would be the next step up.
  **Deferred by owner decision**: contestant code is human-reviewed before it
  runs, so the threat model doesn't warrant tight OS-level containment now — the
  `--harden`/`--seccomp` tiers are sufficient. If the model ever changes (e.g.
  accepting unreviewed third-party submissions), this is the build: it changes
  the execution model (fork passes non-picklable factories/frames by inherited
  memory — a container boundary can't, so contestants would be re-discovered from
  file paths *inside* the container) and adds a docker/image dependency to the
  run + CI path. `docker` is available in the dev env; the seam is
  `default_runner` returning a `ContainerRunner` for a new `isolation="container"`
  mode. `sandbox.py` returns a capability report and degrades gracefully where a
  mechanism is unavailable.

(Dashboard updates via a single **SSE** stream `/sse/dashboard` into a shared
`live` Alpine store: it pushes the account snapshot and bumps a `live:tick`
heartbeat that the chart/table components re-fetch on; one pause toggle gates it.
SSE over WebSocket because the dashboard is read-only (server→client) and gets
free auto-reconnect — see `web/routes/sse.py` + `frontend/src/sse.ts`.)

## Definition of done (every change)

- [ ] Tests added/updated; `make test` green (and `npm run typecheck` if FE).
- [ ] Offline + credential-free path preserved.
- [ ] Invariants above respected (paper gate, no look-ahead, risk centralised,
      import isolation).
- [ ] **This CLAUDE.md updated** (status, roadmap, gotchas, layout as needed) and
      `README.md` if user-facing.
