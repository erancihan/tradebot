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
(commission-free, free paper trading + IEX data, $0 minimum). Greenfield; the
repo root *is* the project root. Four pillars:

1. **Trading core** — strategies, risk, backtester, broker/data adapters, CLI.
2. **Dry-run** — real-time loop with *simulated* fills against a virtual account.
3. **Arena** — load algorithms dynamically and rank them in competitions.
4. **Web dashboard** — FastAPI + TS/Tailwind/Alpine/ECharts; monitor + run sims.

Status: feature-complete for the core vision **including the portfolio stack**
(universe → selector → allocator → risk; see Roadmap); the **algorithms-research
arc's tooling is COMPLETE** (regime scenario library + robustness scorers +
classic roster + experiment journal + cross-sectional portfolio contestants +
meta strategies + promotion pass gate; no contestant has passed the gate yet —
see Roadmap arc status). The live-execution backlog (bracket exits, websocket
streaming, notifications) shipped 2026-08-05, so **`docs/DESIGN-HANDOFF.md` has
no outstanding specs left**. **316 tests, all offline & green** (web tests skip
without fastapi; the Alpaca bracket-mapping test skips without the `[live]`
extra); frontend has a strict `tsc` gate.

> **⚠ 2026-07-25 — the research record is under retraction.** A full audit found
> a look-ahead in the *sizing* path of both execution loops: they marked the
> equity used to size a fill at bar `i`'s **close**, then filled at bar `i`'s
> **open**. Reproduced directly — perturbing only bar 60's close moved the
> quantity filled at that bar's unchanged open from 96.455539 to 81.893842.
>
> **RESOLVED.** The engine is fixed (Stage 1, `_sizing_marks`) and the record
> re-derived (Stage 3). Two more suppressing bugs turned up on the way:
> `exit_rank` froze membership so the real gauntlet was inert, and the return
> criterion averaged total returns across windows of different lengths.
> **Still no contestant passes the gate** — but the old attributions were
> exactly inverted, and the margins are now tiny (0.39pp of CAGR on the real
> pack, 1.38pp of drawdown on synthetic). Worth reading in full: a PASS appeared
> after the engine fix and then vanished under the units fix, and the vanishing
> is the trustworthy part. See "Re-derived record (2026-07-25)" at the end of
> the arc-status block; the text above it is kept only as an audit trail. Full
> backlog and staged plan: `docs/PLAN.md`.

## Agent skills

Project-scoped Claude Code skills live in `.claude/skills/`:
- **tradebot-dev** — orientation + the dev/test/build loop and the pre-commit
  checklist. Start here.
- **add-strategy** — add a pluggable trading strategy.
- **add-arena-algo** — write an arena contestant or extend the arena.

Keep these in sync when workflows or invariants change.

## Layout

```
.                             # repo root == project root
├── tradebot/                 # the Python package
│   ├── strategies/           # Strategy ABC + sma_crossover, rsi_reversion, buy_and_hold,
│   │                         #   donchian_breakout, macd_trend, bollinger_reversion,
│   │                         #   meta.py (follow_leader bandit + ensemble_vote)
│   ├── indicators.py         # pure pandas: sma/ema/rsi/macd/bollinger/rolling_volatility/crossover
│   ├── risk.py               # RiskManager + RiskConfig (sizing, allocate(), caps, band,
│   │                         #   daily-loss, bracket_prices)
│   ├── allocation.py         # Allocator ABC + equal/inverse_vol/explicit + registry
│   ├── selection.py          # Selector/RankedSelector ABCs + momentum (reverse=reversal)
│   │                         #   + low_vol top-K w/ hysteresis + regime_switch
│   │                         #   (RegimeSwitchSelector: momentum/low-vol composite) + registry
│   ├── universe.py           # LiquidityScreen + AlpacaLiquidityUniverse (lazy, injectable)
│   ├── overlays.py           # Overlay ABC + vol_target/sector_cap (reduce-only) + registry
│   ├── walkforward.py        # fold-based out-of-sample evaluation (backtest --walk-forward)
│   ├── portfolio.py          # cost-basis + realised-PnL accounting (sim)
│   ├── backtest.py           # Backtester + BacktestResult (metrics)
│   ├── models.py             # Order (incl. bracket prices)/Fill/Position/Trade/Side,
│   │                         #   opens_exposure, BAR_COLUMNS, utcnow
│   ├── notify.py             # Notifier protocol + Log/Null/Webhook/Multi (stdlib urllib)
│   ├── consortium.py         # panel of algos -> one book: Voice (equal/hedge) + consensus
│   ├── broker/               # Broker ABC, AlpacaBroker (lazy SDK; bracket/OTO mapping),
│   │                         #   DryRunBroker (simulates resting bracket legs)
│   ├── data/                 # synthetic, csv loader, ReplayData, AlpacaData, BarCache,
│   │                         #   stream.py (AlpacaStream websocket + FakeStream)
│   ├── engine.py             # live/paper/dry-run rebalance loop
│   ├── storage.py            # SQLite: orders + equity snapshots + bars (tradebot.db)
│   ├── config.py             # Settings (YAML) + AlpacaCredentials (env) + live gate
│   ├── cli.py                # `tradebot` entrypoint (argparse)
│   ├── arena/                # competition system (see below)
│   └── web/                  # FastAPI dashboard (see below)
├── algos/                    # example arena contestants + how-to README
│   ├── canaries/             # non-promotable diagnostics (opt-in subdir)
│   └── consortium/           # the consortium contestants (opt-in: costs the field)
├── scenarios/                # arena scenario YAMLs incl. the regime library
│                             #   (bull_trend/sideways_chop/crash_recovery/vol_spike)
│                             #   + factor library (xs_bull_dispersion/xs_crash_haven/
│                             #   xs_crash_nohaven — 8-name pool, ONE shared market
│                             #   factor; the only scenarios that actually exercise
│                             #   cross-sectional selection)
│                             #   + real cross-sectional pack (real_xs_2021/2022/2023
│                             #   + real_xs_2024_2025h1 SEALED HOLDOUT — 12 sector
│                             #   SPDRs + TLT/GLD/SHY, 98-100% selector-active)
│                             #   + legacy real pack (real_bear_2022/real_recovery_2023/
│                             #   real_full_cycle — SUPERSEDED: 0% selector-active,
│                             #   nested windows; keep only as a calendar/cost check)
├── frontend/                 # TS + Tailwind + esbuild source for the dashboard
├── tests/                    # pytest (offline; web tests importorskip fastapi)
├── docs/                     # DESIGN-HANDOFF.md (locked backlog designs)
│                             #   + PLAN.md (audit findings + staged plan) — READ BOTH
├── data/cache/               # pulled bars + *.coverage.json manifests (gitignored)
├── config.example.yaml       # annotated settings incl. portfolio: block
├── .env.example              # ALPACA_API_KEY / ALPACA_API_SECRET / ALPACA_DATA_FEED
├── pyproject.toml            # deps + extras: [dev], [live], [web]; scripts
└── Makefile                  # install / test / demo / dryrun / arena / web
```

`tradebot/arena/`: `api.py` (@register), `loader.py` (importlib discovery),
`interfaces.py` (Algo/Action/Context/PortfolioAlgo), `adapters.py` (Policy +
simulation_args), `simulation.py` (stepped core), `scenario.py`, `runner.py`,
`scoring.py` (incl. worst_fold/consistency), `gate.py` (promotion pass gate),
`result.py`, `tournament.py`, `league.py` (standings over a season),
`season.py` (durable, resumable real-time league + feeds + daemon),
`panel.py` (read every member's book in one pass each; self-exclusion),
`market.py` (US market-hours + partial-bar helpers), `contestant.py`, `sandbox.py`
(`--harden`: no-write + net isolation), `store.py` (runs + experiments
journal).

`tradebot/web/`: `app.py` (factory), `repository.py` (read-only SQLite),
`services/` (metrics, account, jobs), `routes/` (pages, partials, api, sse),
`schemas.py` (Pydantic), `dependencies.py`, `server.py`, `templates/` (Jinja,
componentised), `static/` (built, gitignored).

## Invariants — do not break these

- **Paper by default.** Live trading requires `mode: live` *and* env
  `TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND` (`config.Settings.require_live_ack`). Never
  weaken this gate or default anything to live.
- **No look-ahead.** Backtester shifts targets by one bar (decide on `t`, fill on
  `t+1`). The arena feeds a *growing window* so the future is physically invisible.
  Allocation weights obey the same shift: at fill bar `t+1` the allocator only
  sees bars `≤ t` (guarded by `test_allocator_never_sees_the_fill_bar`).
  **The sizing mark obeys the same rule** (fixed 2026-07-25): `_sizing_marks`
  in `backtest.py` marks the book at the fill bar's *open* (falling back to the
  previous close), never at the close of the bar being filled. Both loops import
  that one helper, so the rule cannot drift between them. **Pre-registered
  decision:** open-of-fill-bar over previous-close — both are honest, the open
  is the price actually being filled at and is tighter; they coincide on
  synthetic data, where `synthetic_ohlcv` sets `open(t) == close(t-1)`.
  Note *why* the old guards missed the leak for so long: they were lockstep
  tests, and **a lockstep test can never catch an error made identically in both
  loops.** Every shift now also has one absolute, single-engine guard —
  `test_sizing_never_sees_the_fill_bars_close` and
  `test_selector_verdict_cannot_be_acted_on_the_bar_it_is_formed`. Both were
  verified to FAIL when the corresponding shift is deleted from *both* loops,
  while the lockstep suite stays green. Keep that property when adding shifts.
- **Risk is centralised.** All sizing/limits go through `RiskManager`; strategies
  only emit targets in `{-1, 0, +1}`. Don't let strategies size positions.
  Allocators (`allocation.py`) only *propose* weights; `RiskManager.allocate`
  caps them per-name, scales the book to the gross cap (order-independent), and
  is the only place weights become share quantities. Selectors (`selection.py`)
  only *gate* membership (force non-members flat); they never size or weight.
  The no-trade band lives in `RiskManager.material_delta` (full exits always
  execute), shared by all three loops. Bracket levels are risk too:
  `RiskManager.bracket_prices` turns the configured percentages into absolute
  prices, and `models.opens_exposure` — shared by the engine and `DryRunBroker`
  so they cannot disagree — decides what counts as an entry worth protecting.
- **Backtest == live.** Backtester and live `Engine` share the same `Strategy` +
  `RiskManager`. The arena's stepped `simulation.simulate` must stay consistent
  with `Backtester` — guarded by `tests/test_arena_simulation.py`. If you touch
  either execution loop, keep that test green.
  **One deliberate, documented exception: bracket exits** (`RiskConfig.
  stop_loss_pct` / `take_profit_pct`). They are resting orders the *broker*
  holds between passes; neither simulation loop models them, so a backtest of a
  bracketed config shows the un-bracketed result. This divergence is intended —
  modelling intrabar stop fills from daily OHLC would be inventing a fill path
  the data cannot support (which is why `DryRunBroker` fills them
  pessimistically: stop-before-target on the same bar, gap-through fills at the
  open, target never better than its limit). Never quote a backtest as evidence
  about a stop. Do not "fix" the divergence by adding brackets to the
  Backtester.
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
make install            # venv .venv + pip install -e ".[dev]"
make install-web        # adds [web] extra + npm install (for the dashboard)
make test               # pytest (web tests skip if fastapi absent)
make demo               # offline backtest on synthetic data
make dryrun             # offline forward-test (replay)
make arena              # run the example competition
make web                # build frontend + serve dashboard at :8000
```
CLI: `tradebot {backtest,run,status,demo,arena,data,universe}` and `tradebot-web`.
`run --dry-run`/`--replay` = forward-test;
`arena {list,run,validate,history,show,league,season,gate,journal}`.
`make test` ends with a **simulated balances** ledger (start → final per money
test; `tests/conftest.py` wraps `Backtester.run` + arena `simulate`).

Frontend (`frontend/`):
```bash
npm run typecheck       # strict tsc --noEmit (CI gate)
npm run build           # -> tradebot/web/static/{js,css} (minified, gitignored)
npm run watch:js        # dev rebuild on change
```
Stack: TypeScript, Alpine.js, Apache ECharts, Tailwind, esbuild. Built assets are
gitignored — reproduce with `npm run build`.

CI: `.github/workflows/ci.yml` — two jobs, `pytest (offline)` and
`tsc --noEmit` (+ a build). It runs on every branch push and PR.
**History worth knowing:** this file asserted a CI workflow for a long time
while no `.github/` directory existed, so neither mechanical gate in the
Definition of done had ever run automatically — which is part of how the sizing
look-ahead survived. The Python job deliberately supplies no credentials: the
offline-first invariant says the suite passes without them, and
`tests/conftest.py` fails any test that opens a non-loopback socket, so a run
that starts reaching the network breaks loudly rather than becoming flaky.
Note `frontend/node_modules` is not installed locally by default, so
`npm run typecheck` needs `make install-web` before it can run on your machine.
**And the lesson repeated itself, mildly:** the workflow existed from
2026-07-26 and the `pytest (offline)` job was red on *every* commit from then
until 2026-08-06, while local runs were green — the same commit that added CI
also made unenforceable sandbox containment fatal, and GitHub's runners do not
grant a network namespace. Nobody looked. **A green local suite is not a green
CI**; check the actual run before claiming a gate passed.

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
  and the live engine keeps **no selector state**. Hysteresis state (`held`)
  lives inside the membership walk, derived from data only — never from fills.
  Selector gating happens BEFORE the allocator is consulted, so weights are
  distributed over members only.
  The engine recomputes membership every pass from the **full accumulated
  history**, read back from `Storage` via `Engine._selector_frames` — not from
  the bounded window it fetches for the strategy. That distinction is
  load-bearing and was a real bug until 2026-07-25: a `RankedSelector` walk
  seeds `held` from an empty set, so its verdict depends on where the frame
  *starts*. Prefix-stability licenses recomputing a *prefix*; it says nothing
  about truncating the *head*. Feeding the selector the rolling fetch window
  made live holdings depend on process start time. `record_bars` is an upsert
  for the same reason — the newest persisted bar is usually still forming, and
  under first-write-wins that partial would be frozen onto the decision path
  permanently.
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
  season standings), `test_arena_season.py` (name set),
  `test_arena_tournament.py` (name set) and `test_arena_journal.py`
  ("Journaled N") assert on the field. Adding/removing an example contestant
  means updating those counts (currently 12).
- **Fold scorers are out-of-sample for the algorithm, in-sample for you (M7).**
  `worst_fold`/`consistency` chop the *realized* equity curve into segments.
  This gotcha used to say that was valid "while contestants don't fit anything
  during a run", which names the wrong risk twice over. The premise is already
  false in the letter — `FollowTheLeader` picks a sub-strategy from trailing
  P&L, `MomentumSelector` picks holdings from trailing returns — and the
  mechanism is wrong too: both are *causal*, so fold `k`'s decisions use only
  data before fold `k` and its return is uncontaminated. Adaptivity does not
  break fold causality any more than an SMA does.
  **What actually breaks it is the researcher.** Every fold shares
  human-chosen parameters selected with knowledge of these exact scenarios. The
  folds are out-of-sample with respect to the *algorithm's* information set and
  fully in-sample with respect to the *analyst's*. Also note `worst_fold` has a
  trivial optimum — an all-cash contestant scores exactly 0.0 and beats
  anything with a losing fold. That is fine inside the gate, which pairs it
  with a return check, and degenerate as a standalone arena/season ranking
  metric. And `fold_returns` is *not* "the same idea as `walkforward`":
  `walk_forward` re-runs the pipeline per fold with a warmup, this chops one
  curve.
- **The simulated cost/risk model is not the production one (M10).** Label this
  when quoting any backtest number: no `adjustment=` is passed on the Alpaca
  fetch, so cached bars are **raw, not dividend-adjusted** (understates every
  fully-invested book — it makes the baseline *harder* to beat, so it never
  rescues a candidate); `daily_loss_tripped` is referenced only in `engine.py`
  and in **neither** simulation loop, so the circuit breaker that would halt a
  paper account is switched off in every number used to decide promotion;
  scenarios ship `slippage_bps: 1.0` with zero commission, which makes high
  turnover nearly free; and `synthetic_ohlcv` sets `open(t) == close(t-1)`
  *exactly*, so the decide-at-close/fill-at-open discipline costs a synthetic
  strategy nothing while ~33% of real daily variance lives in that gap. The
  synthetic gauntlet is structurally blind to signal-to-fill decay.
- **Survivorship is handled; window selection is not (M11).** ETFs sidestep
  membership bias, and the `universe:` screen is correctly labelled
  survivorship-biased for historical use. What cannot be fixed in code: the
  date span itself was chosen in 2026 knowing what happened in it. The
  `real_xs_*` headers say so, and the sealed holdout is the only real
  mitigation — which is why it must be run once, last.
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
  **Fixed 2026-08-05: `season create --isolation process --time-budget N`.**
  `SeasonConfig` now carries `time_budget_s` and passes it to the recompute, so
  process isolation makes the budget a **hard kill** and the leak is
  structurally impossible — verified by running the full 12-contestant field
  (metas included) as a process-isolated season. Thread stays the default
  because it is much faster and correct for affordable fields; its budget is
  still soft, and that is now stated on the flag itself rather than only here.
  The same change fixed a silent bug: `harden` was hardcoded `False` with a
  comment about thread isolation, so a season created with `--isolation
  process` ran **unsandboxed** while the tournament printed a clean `ok` —
  the same failure shape as B14. Hardening is now *derived*
  (`SeasonConfig.hardened`), which is the only way it cannot drift from the
  isolation mode.
- **Cache coverage is recorded, not inferred.** `BarCache` writes a
  `*.coverage.json` manifest beside each CSV listing the windows *requested*
  from a provider, and a request inside a pulled window is served from disk.
  (The original wording here said "actually pulled". It records the **ask**, not
  the response — see the B4 caveat two bullets down.)
  Judging coverage by observed bar timestamps (the old rule) is wrong for real
  calendars: asking for `2021-12-01` yields a first daily bar stamped at the
  `05:00` UTC open (`min > start`), and `real_full_cycle` ends `2024-06-30`, a
  **Sunday**, whose last bar is the Friday before (`max < end`). Both made the
  scenario re-fetch forever and never replay offline. When a manifest exists it
  is **authoritative, gaps included** — disjoint pulls stay separate entries so
  a request spanning a hole re-fetches instead of trusting data never
  downloaded. Caches with no manifest (hand-seeded, or pre-dating this) fall
  back to the old observed-bar check, which is why the synthetic tests still
  pass unchanged.
  **Two caveats found by the 2026-07-25 audit, both unfixed (B4, B13 in
  `docs/PLAN.md`):** (a) `record_coverage` stores the *requested* bounds, so an
  unbounded `tradebot data pull` (no `--start`/`--end`) records an unbounded
  claim and every later window is then served from disk as an empty frame
  instead of re-fetched — **always pass explicit `--start`/`--end`** until this
  is fixed; (b) `_slice` is **half-open on the right**: a date-only `end`
  excludes that date's own session, because real daily bars are stamped at the
  04:00/05:00 UTC open. (b) is deliberate and is baked into the shipped
  manifests — "fixing" it makes `_spans` reject `real_full_cycle`'s own declared
  window and reintroduces the bug commit `33379b9` fixed. Changing it needs a
  manifest migration.
- **A sandbox tier that the kernel refuses is REPORTED, not fatal.** The
  capability report from `apply_hardening` used to be discarded entirely, so a
  failed `unshare(CLONE_NEWNET)` left a contestant fully networked while the
  tournament printed a clean `ok` (B14). The first fix over-corrected: it failed
  the contestant outright, which turned **CI red on every commit** — GitHub
  Actions runners will not grant a network namespace to an unprivileged process,
  so all 12 contestants died with `SandboxError` and the leaderboard came back
  empty. That is a portability fact, not a threat model; unprivileged
  containers and macOS behave the same way.
  The rule "never silently downgrade" is satisfied by **saying so**, not by
  refusing to run. Unenforceable containment now logs one loud warning per
  mechanism (not per contestant — twelve identical lines train everyone to
  ignore it) and the run proceeds. `--require-sandbox` / `require_sandbox=True`
  restores the hard failure for anyone whose threat model needs the guarantee;
  contestant code here is human-reviewed, which is the same reasoning that
  defers the container tier.
- **A scenario must be checked for degeneracy before it is trusted.** Both
  prior gauntlets silently measured nothing: 4/5 synthetic scenarios were
  single-symbol, and the real pack froze membership. In both, a cross-sectional
  selector was a *definitional* no-op, so the verdicts carried no information
  about the mechanism they claimed to test. `tests/test_scenario_library.py`
  now asserts, for every `xs_*` scenario: `top_k < pool size`, membership
  actually varies across bars, and **two different selectors disagree on ≥20% of
  live bars**. Measured "selector active" rates: new factor library 92–94%,
  `cross_sectional` 98%, `real_full_cycle` 38%, `real_bear_2022` **0%**,
  `bull_trend` **0%**. Run that check on any scenario before reading a verdict
  from it.
- **A gauntlet must be BALANCED, and the balance decides verdicts.** All seven
  `xs_*` schedules now ship: selection is rewarded by `xs_bull_dispersion` and
  `xs_chop_dispersion` and punished by `xs_momentum_crash`; defense is rewarded
  by `xs_crash_haven` and `xs_vol_spike_down` and punished by
  `xs_crash_nohaven` and `xs_vol_spike_up`. This is not bookkeeping. With only
  the first three shipped (two of them crashes) the set rewarded defensive
  books ~2:1 and returned **PASS** for `xs_momentum_vt`; over the balanced
  seven the same candidate **FAILs decisively** (mean CAGR 1.70% vs 9.73%,
  worst-fold 3/7) — it wins the two crash scenarios and loses the four
  non-crash ones. An unbalanced gauntlet does not produce a weak verdict, it
  produces a *wrong* one. `MIRROR_PAIRS` in `tests/test_scenario_library.py`
  asserts every rewarding scenario has a punishing twin differing by exactly
  one parameter.
- **The canaries say the factor library has signal, and that momentum can't
  reliably extract it.** `algos/canaries/` holds three non-promotable
  diagnostics (`oracle_topk` selects on *future* returns and must win;
  `random_topk` is the null model; `always_haven` tests whether hiding is
  free). Measured over 8 draws: the oracle wins **every** one, by +152% to
  +351% — so the signal is unambiguously there. But `xs_momentum` beats
  `random_topk` in only **4 of 8** draws. A 60-bar trailing-return selector
  picking 2 of 8 names cannot reliably harvest a +0.0002/bar alpha spread
  against 0.010/bar idiosyncratic noise; the edge is real in expectation and
  invisible on one 500-bar path. Treat "momentum beat random on this scenario"
  as a coin flip unless it is run with `--seeds`. Also measured: `always_haven`
  is *legitimately* competitive in flat and falling markets — a low-beta asset
  with slight carry should be — so the "hiding is not free" property is only
  asserted where the market rises.
- **Seed ensembles: `arena gate --seeds N`.** A single draw of a high-vol
  window is not a reliable basis for a binary decision. `xs_vol_spike_down`'s
  own shipped seed resolves *upward* — the designed effect holds in 93–98% of
  seeds but not that one. Deepening the drift until every seed complies was
  rejected: it takes ±0.0090/bar, which produces a +295% 80-bar "recovery",
  i.e. a distortion introduced to flatter a draw. **Fix the evaluation, not the
  data.** `--seeds N` re-draws the whole gauntlet, takes the median per
  criterion, and prints `UNSTABLE` when the verdict flips across draws.
- **The factor library builds the pool jointly, not as independent walks.**
  `synthetic_factor_panel` draws one market factor per bar and gives each symbol
  a beta, an alpha and idiosyncratic noise. The older `cross_sectional.yaml`
  drew each symbol independently (~0.03 mean pairwise correlation), which is the
  wrong null for cross-sectional work: a "crash" is several unrelated accidents,
  every name is a haven, and diversification is free. The pool is **fixed across
  every scenario** (re-picking it per scenario is the cheapest way to flatter a
  candidate), the haven **costs to hold** in calm regimes so "always hide"
  cannot win, and `beta_shift` drags betas toward 1.0 to model crisis contagion
  — that single parameter is the only difference between `xs_crash_haven` and
  `xs_crash_nohaven`, asserted by test so the punishing mirror cannot be quietly
  weakened.
- **`exit_rank` freezes membership when it reaches the pool size.** It defaults
  to `top_k + max(top_k // 2, 1)`, so `top_k=2` gives `exit_rank=3`. On a
  3-name pool every held name is permanently within `exit_rank` and can never
  be dropped, so **membership freezes at the first verdict**. Verified on the
  shipped real pack: `MomentumSelector(lookback=60, skip=5, top_k=2)` over
  SPY/QQQ/IWM picks `{IWM, SPY}` on 2022-02-28 and holds it for all 587 live
  bars — **zero** membership changes across the entire real gauntlet. So the
  real pack contains no evidence about cross-sectional momentum at all; it
  measures one single-day pick frozen for 2.5 years, and the previously
  recorded "170/647 bars differ" was entirely `RegimeSwitchSelector` switching
  legs, not momentum rotating. A held name must stay droppable whenever the
  pool has more than `top_k` names — fix is Stage 3 in `docs/PLAN.md`. Until
  then, pass `exit_rank` explicitly on small pools.
- **A composite selector must not out-run its own `required_history`.**
  `RegimeSwitchSelector` publishes `max(legs)` but its low-vol leg warms up
  sooner than its momentum leg; a storm inside that gap used to emit live
  verdicts early, silently making `xs_regime` diverge from `xs_momentum` on
  pools where the selector should have been a **no-op** (caught on real 2022
  bars: 8 leaked verdicts, `-8.33%` vs `-6.84%`). `membership()` now masks the
  leading `required_history - 1` rows flat, which also covers the mirror case
  (`vol_window > lookback`). Masking a *leading run* keeps prefix-stability.
  Any future composed selector needs the same guard.
- **A bracket protects BETWEEN passes; it does not veto a live signal.** After a
  stop fires, the next `rebalance()` re-enters if the strategy still says long —
  that is a rebalancing bot working correctly, not a bug, and
  `test_a_forward_test_stops_out_and_books_the_loss` asserts exactly that
  behaviour so nobody "fixes" it by accident. If you want a cooldown, that is a
  *strategy* decision (emit flat), not a broker one. Two more properties worth
  keeping: brackets ride only on fills that **add** risk (`models.opens_exposure`,
  shared by the engine and `DryRunBroker` so they cannot drift), and
  `DryRunBroker.check_brackets` is duck-typed rather than on the `Broker` ABC —
  a real broker holds the resting legs itself, so only the simulator needs a
  polling hook and the ABC stays four methods wide.
- **Streaming is an arrival optimisation, not a second source of truth.**
  `data/stream.py` pushes bars; `StreamSeasonFeed` buffers them back into the
  season's pull-shaped `next()`. Bars remain the source of truth and the PK
  dedup still backstops duplicates, so a streamed season and a polled season
  accumulate the same history (asserted by
  `test_a_streamed_season_accumulates_the_same_bars_as_a_replay`). The `Engine`
  deliberately keeps polling — its loop is timer-driven by design and a socket
  would only add a failure mode. `start(background=False)` runs a `FakeStream`
  inline, which is what makes the tests deterministic without sleeps or joins.
- **A consortium is a decision rule, so it obeys every rule a decision rule
  obeys.** `consortium.py` blends member books into one; the danger is that
  `prepare()` hands it the *whole* frame at once, which is exactly the shape
  that makes look-ahead easy to introduce by accident. Precomputing is licensed
  only because every member is causal, and two absolute guards hold it there:
  `test_the_consortium_cannot_see_the_future` (perturb a late bar, assert no
  earlier decision moves) and `test_the_consensus_is_prefix_stable`. Voice has
  its own guard — a member's performance on bar `t` must not change its
  influence on bar `t`.
  Three more properties worth keeping: the blend is **convex**, so it can never
  lever past what its members already asked for and needs no renormalisation;
  **agreement is conviction**, so a split panel shrinks the position instead of
  flipping a coin; and voice has a **floor**, so a silenced member can recover
  (it is a dimmer, not a door).
- **The consortium is opt-in for a reason, and it is not the roster's cost.**
  It lives in `algos/consortium/` — a subdirectory `loader._expand`'s
  non-recursive glob never reaches — like `algos/canaries/`. It costs the *sum
  of its members* by construction (~17s for 250 bars × 2 symbols with the
  current field, dominated by the metas), so putting it in `algos/` would slow
  every ordinary tournament and blow the default 10s budget. Run it with
  `--algos ./algos ./algos/consortium --time-budget 200`. Measured on one
  factor scenario (8 symbols × 500 bars): **68.6s of panel**, of which
  `meta_leader` is 23.9s and `meta_vote` 19.7s — two members are 64% of the
  cost. Do **not** trim the roster to fit a budget: that is fitting to the
  harness, the same rule as the metas. Self-exclusion is guarded twice (the
  subdirectory, plus an `is_consortium` marker attribute rather than a name
  match) because a consortium that loads itself recurses until the process dies.
- **A component can fill two roles, and preparing it twice doubles the bill.**
  The consortium is its own signal *and* its own weighting, so it reaches
  `_prepare_components` as two objects — the policy wrapper and the allocator.
  `Consortium.prepare` is therefore idempotent on a frame fingerprint, and
  `_prepare_components` also dedupes by identity. This was not theoretical: the
  first gauntlet run turned 68s into 137s and returned **TIMEOUT on every
  scenario** at a 120s budget, which reads exactly like "the candidate is too
  slow" rather than "the framework called it twice". Identity dedup alone does
  **not** cover it — the two objects are genuinely different — so the guard has
  to live on the expensive call.
- **A consortium over a correlated roster is one strategy wearing many hats.**
  The current twelve members are mostly trend/mean-reversion variants over one
  equity-beta pool. Averaging correlated members reduces the noise in the
  estimate, not the systematic exposure. The binding constraint on a consortium
  being *worth* anything is member **diversity** — a roster problem, not a
  combiner problem — so the next real work is new member kinds, not a cleverer
  weighting. This caveat is rendered on the dashboard page itself, not just
  written here, so it travels with the numbers.
- **Adaptive voice is a research claim, not infrastructure.** `HedgeVoice`
  weights members by trailing P&L, which is a momentum bet on your own
  strategies — the same class of rule the canaries measured at 4 wins in 8
  draws. `EqualVoice` is the default and the baseline any scheme must beat;
  Hedge is used rather than greedy leader-following because it carries a regret
  bound. `eta` is a declared researcher degree of freedom: state it when
  quoting any result.
- **A notifier is an observer and can never break a trade.** Every `send` is
  wrapped (`Engine._notify`) and `WebhookNotifier` swallows every URL/OS error,
  because an unreachable endpoint halting the trade loop is exactly backwards.
  `build_notifier` returns log **plus** webhook, never webhook-only: the log
  line is the local audit trail and stays useful when the remote is down. The
  webhook adapter is tested against a real loopback `http.server` — the offline
  guard allows `127.0.0.1` exactly so adapters can be tested for real instead of
  through a mock that would also pass if the code posted nothing.

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
**⚠ ARC STATUS SUPERSEDED — see "Re-derived record (2026-07-25)" at the end of
this block. `xs_momentum_vt` now PASSES the real-data gate. Everything from
here to that heading is the pre-fix record, kept for the audit trail; its
numbers and its attributions are wrong.**

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
bugs; new gate attempts need a *different idea*, not another parameter.
**Second gate attempt — `xs_regime` (RegimeSwitchSelector), 2026-07-04: FAIL,
one attempt, do not re-chase.** The idea was defense by *rotation* not scaling:
hold momentum top-2 in calm regimes, rotate into the 2 calmest names when the
pool's realized vol proxy (equal-weight mean vol, annualized, > 0.25) spikes.
Gate vs buy_and_hold over the 5 synthetic scenarios: beats mean return
(31.53% vs 28.04%) and completes everywhere, but loses the worst-fold majority
2/5 and blows the drawdown limit (−48.25% on crash_recovery). (Numbers
re-derived 2026-07-25 after the composite-warmup fix below; the original run
read 30.63% mean return and lost the same two criteria, so the verdict and its
attribution are unchanged.) **Structural
attribution:** four of the five gauntlet scenarios (bull_trend, sideways_chop,
crash_recovery, vol_spike) are **single-symbol `[DEMO]`** — a rotation selector
is definitionally a *no-op* there (top-2 over a 1-name pool selects that name in
both regimes; there is no calmer name to flee to), so the book degenerates to
buy_and_hold and inherits its −48% crash drawdown and its warmup-drag near-ties
in worst fold. On the ONE scenario with a real cross-section (`cross_sectional`,
6 names) the mechanism fires and wins decisively: 40.69% vs 22.57% return,
worst-fold +0.006 vs −0.011, drawdown −13.24%. So the idea is sound *where it
can act*; it fails the gauntlet because 4/5 gate scenarios have no cross-section
to rotate within. The correct next step (if pursued) is a scenario-library
change — multi-symbol crash/vol regimes that contain calm names to rotate into —
NOT tuning `storm_vol`/`vol_window` (that would fit the harness). Left as the
honest result. Promotion mechanics verified offline end-to-end: the exact
candidate stack ran as a core config through `run --replay` (+7% on the
demo replay) and an 11-contestant replay season.

**Real-data gauntlet — run 2026-07-25 (owner supplied paper Alpaca keys).**
Bars pulled once (SPY/QQQ/IWM, daily, IEX, 2021-12-01 → 2024-06-30; 647 bars
each) and cached; every result below replays with **no credentials in the
environment**. Two gates, both **FAIL**, both for the *same* reason and it is
not the one the synthetic gauntlet gave:

| candidate | mean ret | baseline | worst-fold | deepest DD | verdict |
|---|---|---|---|---|---|
| `xs_momentum_vt` | 13.52% | 17.75% | **3/3** | −17.76% | FAIL |
| `xs_regime` | 12.38% | 17.75% | **3/3** | −22.38% | FAIL |

This *inverts* the synthetic outcome. On real bars both candidates win
worst-fold in **every** scenario and keep drawdown far inside the limit
(baseline takes −24.55% on the full cycle) — the robustness case they were
built for holds up. They fail purely on **mean return**, and essentially all of
the gap is `real_recovery_2023`: 26.66% vs buy_and_hold's 43.87%. A top-K
inverse-vol book with a 60% per-name cap systematically concedes to just
holding everything in a straight-up bull. That is a real trade-off, not a bug.
**The real pack is still not a fair cross-sectional test.** `top_k=2` over
`real_bear_2022`/`real_recovery_2023` (SPY, QQQ) selects *both* names every
bar — the selector is a **no-op**, exactly the flaw that sank the synthetic
gauntlet (4/5 single-symbol), only milder. Verified directly: momentum vs
regime membership differs on **0 of 292** and **0 of 270** bars there, and on
170/647 only in `real_full_cycle` (3 names, top-2). So all three `xs_*`
variants tie exactly at 26.66% in 2023 — nothing to select, no storm, dial
inert. Do NOT read these two FAILs as evidence against rotation or vol-dialing;
the gauntlet still barely exercises either. A genuine test needs a pool with
real cross-sectional dispersion **and** something uncorrelated to rotate into
(SPY/QQQ/IWM are one equity-beta factor). That is a scenario-library change,
which remains the correct next move — still NOT param tuning.
Journal after this arc: `xs_momentum` 34 attempts (2 variants), `xs_regime` 17,
every other family 17.

**RETRACTED 2026-07-25 — everything above in this arc-status block.** Three
corrections, none of which change the headline (both candidates still FAIL):

1. **The numbers came from a biased engine** (B1 — the sizing look-ahead in the
   retraction banner at the top of this file). The bias is turnover- and
   exposure-dependent, so it does *not* cancel between candidate and baseline;
   the fully-invested `buy_and_hold` benchmark harvests it hardest. The audit
   reports that under a corrected mark the per-scenario attributions **invert**.
   Treat every fold attribution above as unreliable, especially "this
   candidate's remaining gaps are structural trade-offs, not bugs" — two of the
   three worst-fold losses that sentence explains away may be the bug.
2. **The warmup caveat was wrong**, not merely imprecise. It used to say the
   comparison is fair because "the baseline runs the same curve". It does not:
   `buy_and_hold` has zero warmup while `MomentumSelector(lookback=60)` is flat
   for 61 bars. Rebasing post-warmup reportedly moves `real_recovery_2023` from
   −17.2pp to −1.6pp and reverses 2 of 3 real-pack worst-fold wins. Fix is in
   the gate (extend windows backward by `required_warmup`), not the label — M2.
3. **The attempt counts are unauditable.** `arena.db` is gitignored and every
   session runs in a fresh container, so the ledger is ephemeral by
   construction — nothing survives to check these against, which is also why
   two counts in this file disagree (55 earlier, 34 here: different databases,
   not a counter running backwards). Worse, `arena gate` journals every
   contestant for every scenario, so one 5-scenario gate adds +5 to all 12
   families — which is why `buy_and_hold`, never iterated once, carries the same
   17 as a candidate under active development. The statistic currently measures
   gate invocations, not iterations of an idea. M8.

The **structural** conclusion survives all three and is the one to carry
forward: neither gauntlet exercises the mechanism it is meant to test. `top_k=2`
over a 2-symbol pool selects both names every bar. A genuine test needs a pool
with real cross-sectional dispersion **and** something uncorrelated to rotate
into. Still NOT param tuning. Design: `docs/PLAN.md` §4.

### Re-derived record (2026-07-25, Stage 3) — THIS is the current record

Everything above this heading is superseded. Re-run on the fixed engine
(sizing mark corrected, `exit_rank` freeze fixed, targets computed after
alignment). **Still NO contestant passes the gate** — but for completely
different reasons than the old record gave, and much more narrowly.

| gauntlet | candidate | mean CAGR | baseline | worst-fold | deepest DD | verdict |
|---|---|---|---|---|---|---|
| real (3) | `xs_momentum_vt` | 8.79% | 9.18% | 2/3 | −18.97% | FAIL (return, by 0.39pp) |
| synthetic (5) | `xs_momentum_vt` | **10.41%** | 6.84% | **4/5** | −36.38% | FAIL (drawdown, by 1.38pp) |
| synthetic (5) | `xs_regime` | 20.36%* | 16.90%* | **5/5** | −52.86% | FAIL (drawdown) |

\* pre-M3 figures (mean total return); the others are mean CAGR.

**A PASS appeared and then vanished, and the vanishing is the honest part.**
Judged on mean *total return* — the original aggregation — `xs_momentum_vt`
passed the real gate 14.79% vs 11.71%. Under M3's length-normalization it fails
8.79% vs 9.18%. Averaging total returns over windows of 292, 270 and 647 bars
has no interpretation: the baseline's huge 2023 rally sits in the *shortest*
window, so normalizing for time rewards it. The units fix made passing harder,
which is exactly why it is admissible under the plan's own good-faith test.

**The recorded attributions were exactly inverted.** The old record said
`xs_momentum_vt` "passes mean-return + drawdown but loses the worst-fold
majority 2/5". It now passes mean return *and* worst-fold 4/5, and fails only
on drawdown, by 1.38pp. Do not carry forward any fold attribution written
before this date — in particular "this candidate's remaining gaps are
structural trade-offs, not bugs" was wrong: they were the bugs.

How much the leak flattered the benchmark: `crash_recovery`'s `buy_and_hold`
goes −28.92% → **−37.20%**, and `sideways_chop`'s flips sign, +14.34% →
**−1.84%**. The baseline is the most exposed contestant and harvested the bias
hardest, which is why the candidates looked worse than they were.

**Why the real pack finally means something.** The `exit_rank` freeze had made
it inert: momentum picked one pair and held it for all 587 live bars. It now
makes 42 membership changes and uses all three pairs, so the gauntlet actually
tests cross-sectional selection for the first time.

### Final state after the full methodology pass (2026-07-25)

The verdict flipped **four times** as each defensible correction landed, which
is itself the most important result in this file:

| judged on | real pack | verdict |
|---|---|---|
| biased engine, mean total return | 13.52% vs 17.75% | FAIL |
| fixed engine, mean total return | 14.79% vs 11.71% | PASS |
| + M3 length-normalization (CAGR) | 8.79% vs 9.18% | FAIL |
| + M2 post-warmup rebasing | **10.98% vs 9.52%** | **PASS** |

Every step was a construct fix argued without knowing its effect, and no single
one is wrong. A quantity that reverses under four honest choices, on margins of
0.4–1.5pp, is **not a measurement** — it is M4's point made concrete. Do not
promote on it.

**Confirmed on real bars too (2026-07-26).** The old SPY/QQQ/IWM pack is
superseded by `real_xs_*`: twelve rule-chosen symbols (the nine sector SPDRs
that predate the span — a complete S&P partition, so no discretion in the pick
— plus TLT/GLD/SHY), disjoint calendar-year windows, and a sealed holdout.
Measured: **98–100% selector-active** (the old pack scored 0%), sector
dispersion of 40–113pp a year, and a haven that genuinely **fails** in 2022
(TLT −33% alongside equities) while GLD works in 2023–25 — so no candidate can
win merely by owning bonds. `xs_momentum_vt` over 2021/2022/2023: mean CAGR
**−1.30% vs 6.87%**, worst-fold **0/3**. Decisive FAIL, on the first real-data
gauntlet this project has had that can actually see cross-sectional selection.
Alpaca's free IEX history starts 2020-07-27, so the pack cannot contain COVID
or 2018Q4 — the windows are what the data permits.

**The trustworthy verdict is the balanced factor library, and it is a decisive
FAIL:** mean CAGR **2.03% vs 11.17%**, worst-fold 3/7, over seven scenarios
that run 89–100% selector-active. `xs_momentum_vt` wins both crash scenarios
and loses all five others. That gauntlet is balanced, non-degenerate, and its
margin is wide enough to survive the choices above.

The real pack's PASS should be read alongside what the gate now prints about
it: `selector active: real_bear_2022:0% real_recovery_2023:0%
real_full_cycle:38%` plus `WINDOWS OVERLAP` on all three pairs. The tooling is
telling you that pack cannot test cross-sectional selection and counts one
price path three times. **Use the factor library for verdicts; keep the real
pack as a reality check on cost and calendar behaviour.**

**How close it is, and what still stands between it and a promotion:**
- Real gauntlet: fails return by **0.39pp** of CAGR. Synthetic: fails drawdown
  by **1.38pp**. Both are inside any reasonable error bar, which is the point of
  M4 — these are point estimates with no interval, so "nearly passed" and
  "nearly failed" are the same statement. Do not read either as a near-miss to
  be nudged over.
- The three real scenarios are **nested** — `real_bear_2022` (292 bars) and
  `real_recovery_2023` (270) are both fully contained in `real_full_cycle`
  (647). The gate now prints `WINDOWS OVERLAP` when it detects this, but does
  not silently reweight: picking a canonical window is the gauntlet author's
  call, not the gate's.
- Fold sensitivity is printed and holds up on the real pack (`k=3..8: 3:2 4:2
  5:2 6:3 7:2 8:2`); on synthetic it is shakier (`3:5 4:4 5:3 6:5 7:4 8:3` —
  the 4/5 win count is 3/5 at k=5 and k=8, one step from failing that criterion
  too).
- The pool is still three correlated equity-beta ETFs. The Stage 4/5 library
  remains the right next move.

**Do not tune the −35% drawdown limit or revert M3** to convert either FAIL.
Both bounds are doing their job. The attempt counter climbs every time a
gauntlet is re-run (`xs_momentum` is at 42 after this session's re-derivations),
and that is working as intended — it is measuring exactly what it should.

**M5 resolved 2026-08-05 (owner decision): the gate now has TWO drawdown
criteria, because they measure different things.** Conflating them into one
absolute number was the original error.

| check | asks | role |
|---|---|---|
| absolute, `-35%` | is this catastrophic? | admission |
| relative, vs baseline | is this worse than just holding? | competitiveness |

Both are required, so the change can only turn a PASS into a FAIL — which is
what made it admissible with no pre-registration ceremony (`docs/PLAN.md`'s own
test: a change that makes the candidate in flight fail *harder* is admissible).
**The rejected alternative was `absolute OR relative`**, which would have
converted the recorded synthetic FAIL by 1.38pp. Do not re-propose it.

The relative check is **scoped to scenarios where the baseline itself breaches
the limit** — exactly where the absolute bound stops measuring the candidate
and starts measuring the regime. Unscoped it is *unsatisfiable*: an all-cash
baseline takes zero drawdown, so no long-only candidate could match it. Same
trivial optimum that makes `worst_fold` degenerate alone; caught by an existing
CLI test, not by inspection. Where the baseline stays calm the gate prints
"not applicable" and the absolute bound stands by itself.

Verified: on `crash_recovery` the candidate fails the absolute bound at
-36.38% while `buy_and_hold` takes **-52.91%**, and the new relative check
*passes*. The verdict did not move. Nothing was converted.

**Consortium arc (owner ask 2026-08-05): BUILT, and the first verdict is in.**
The reframing was the owner's: stop betting on one algorithm, run a panel, make
voice continuous rather than membership binary. That changes the gate's job —
it becomes an *admission* test rather than a promotion decision — which is the
same split the M5 resolution made explicit. Design locked in
`docs/DESIGN-HANDOFF.md` Spec 5 before any code, with the implementation's
three departures recorded underneath it.

**Balanced factor library, 7 scenarios, equal voice, engine e2 — FAIL:**

| criterion | result | |
|---|---|---|
| completes | 7/7 | ✓ |
| mean CAGR | **3.37% vs 9.17%** | ✗ |
| worst fold >= baseline | **5/7** (k=3..8: 4,4,4,5,5,4 — never fails) | ✓ |
| drawdown vs −35% | −40.56% (baseline −49.11%) | ✗ |
| drawdown vs baseline where confounded | 2/2 | ✓ |

**This is the textbook diversification trade, and its failure mode is the exact
opposite of `xs_momentum_vt`'s.** The consortium is more robust than the
baseline on every robustness measure — it wins worst-fold at *every* fold count
tried, and it beats `buy_and_hold`'s drawdown in both crash scenarios
(−33.64% vs −45.93%, −40.56% vs −49.11%). It fails on **return**, and it fails
there systematically: it dilutes the rallies (`xs_vol_spike_up` 76.60% vs
136.64%, `xs_momentum_crash` 1.77% vs 20.90%). Averaging correlated members
lowers variance and drawdown roughly in proportion to how much return it gives
up. That is what averaging correlated things does.

**So the pre-registered caveat was confirmed, not refuted.** It was written into
the spec, the code and the dashboard page *before* the gauntlet ran: this roster
is twelve trend/mean-reversion variants over one equity-beta pool, so a panel
over it is one strategy wearing many hats. The measured result is precisely that
signature. **The binding constraint is member diversity — a roster problem, not
a combiner problem.** Do not respond to this FAIL by tuning voice; the next
useful work is member kinds that are actually uncorrelated with the existing
twelve.

**Adaptive voice bought essentially nothing, which is the answer the design
predicted.** `consortium_hedge` (exponential weights, eta=2.0, floor=0.02) over
the same seven: mean CAGR **3.68% vs equal voice's 3.37%** — +0.31pp — same
verdict, same criteria pattern, worst-fold 5/7 either way. Per scenario it is
noisier than that net figure suggests: hedge wins `xs_vol_spike_up` by **+12pp**
(88.84% vs 76.60%) and loses `xs_momentum_crash` and `xs_chop_dispersion`. A
scheme whose largest single-scenario effect is 12pp and whose average effect is
0.31pp is mostly reallocating noise.

That is what the canary evidence already implied about weighting by trailing
P&L, and it is why `EqualVoice` is the default. **Do not tune `eta`.** The
correct reading is that voice is not where the leverage is; the roster is.

Worth noting where the M5 split earned its keep on its first real use: the
absolute bound is the binding criterion here and it is *confounded* in the
scenario that breaks it (baseline −49.11%), while the relative check passes 2/2.
Without the split this would have read as "too risky" when the candidate was in
fact the *safer* of the two books in every crash.

**Live-execution backlog — DONE 2026-08-05** (owner ask: "complete the
roadmap"). The three locked Spec 4 designs in `docs/DESIGN-HANDOFF.md` shipped
together; 4d stays deferred on its own rationale (threat model, not effort).
- **4a bracket orders** — `RiskConfig.stop_loss_pct`/`take_profit_pct` →
  `RiskManager.bracket_prices` → absolute prices on `Order`. `AlpacaBroker`
  maps both legs to `order_class=bracket` and one leg to `oto`; `DryRunBroker`
  simulates the resting legs from each bar's high/low so the whole feature is
  offline-testable. Deliberate backtest divergence — see the invariant.
- **4b websocket streaming** — `data/stream.py` (`AlpacaStream` lazy +
  `FakeStream`) and `arena/season.py StreamSeasonFeed`. The season is the first
  consumer; the `Engine` still polls, on purpose.
- **4c notifications** — `notify.py` (`Notifier` protocol, `LogNotifier`
  default, `WebhookNotifier` on stdlib urllib, `MultiNotifier`); `notify:`
  config block; the engine emits `order`, `bracket_exit` and `halt` events.

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
