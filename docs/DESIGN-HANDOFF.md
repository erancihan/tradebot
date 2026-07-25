# Design handoff — next implementations

For any agent/model continuing this project. **Read `CLAUDE.md` first**: it is
the system map, the invariants (paper gate, no look-ahead, risk centralised,
lockstep engines, offline-first), the gotchas, and the honest research record.
This document only specifies work that has NOT been built yet, precisely
enough to implement without re-deriving decisions.

## Working agreements (all models)

- Definition of done is in CLAUDE.md — tests + offline path + invariants +
  CLAUDE.md updated in the same change.
- Research honesty is not optional: every evaluation is journaled; variants
  share a `family`; never tune the gate or grid-search params to force a pass
  (the fold-attribution record in CLAUDE.md explains why the current best
  candidate fails — do not re-chase it).
- The `algos/` head-count (currently 12) is baked into tests listed in the
  CLAUDE.md gotcha. CLI arena tests must pass `--db <tmp>` or `--no-journal`.
- Every simulation surface shows start/final balance + simulated period
  (tests/conftest.py ledger, journal columns). Preserve this in new outputs.

## Spec 1 — RegimeSwitchSelector (the next gate candidate) — DONE 2026-07-04

**Status: BUILT and gated — verdict FAIL (one attempt, do not re-chase).**
Shipped: `RegimeSwitchSelector` (`selection.py`, registry `regime_switch`) +
tests + `algos/xs_regime.py` (family `xs_regime`), field count bumped 11 → 12.
The gate failed for a *structural* reason, not a bug: 4/5 gauntlet scenarios are
single-symbol, where a rotation selector is a no-op and the book degenerates to
buy_and_hold (inheriting its crash drawdown); on the one multi-symbol scenario
(`cross_sectional`) it wins decisively. Full fold attribution is in the CLAUDE.md
arc-status block ("Second gate attempt — `xs_regime`"). The correct follow-up,
if pursued, is a scenario-library change (multi-symbol crash/vol regimes), NOT
param tuning. The design below is retained for the record.

**Idea (theory-driven, one attempt):** defense by *rotation*, not scaling.
Hold momentum top-K in calm regimes; when the pool's realized volatility
spikes, rotate into the K *calmest* names instead. Distinct from the vol
dial (which shrinks the book): the book stays invested, in different names.

- File: `tradebot/selection.py`. Subclass `Selector` directly (NOT
  `RankedSelector`) and *compose* a `MomentumSelector` + `LowVolatilitySelector`.
- Regime signal: mean of per-symbol `rolling_volatility(close, window)`
  across the pool (equal-weight pool vol proxy), annualized ×√252. Regime is
  "storm" at bar t iff proxy(t) > `storm_vol` (default 0.25). NaN proxy
  (warmup) = calm.
- `membership(frames)`: compute both sub-membership matrices ONCE, compute
  the regime series, and row-select: storm rows from low_vol, calm rows from
  momentum. This is prefix-stable because both subs are prefix-stable and the
  regime at t uses only bars ≤ t. Do NOT thread hysteresis state across the
  switch (keep it simple; each sub already has its own hysteresis walk).
- Params: `lookback/skip/top_k` (momentum leg), `vol_window` (low-vol leg +
  regime proxy, default 63), `storm_vol` (default 0.25), `exit_rank` passed to
  both legs. `required_history = max(legs) + 1`. Registry name: `regime_switch`.
- Tests (tests/test_selection.py): storm pool selects calm names, calm pool
  selects winners; prefix-stability (add to the existing loop test); registry.
- Contestant: `algos/xs_regime.py`, `PortfolioAlgo` with `BuyAndHold` +
  the selector + `InverseVolatility(window=30)`, `family="xs_regime"`.
  Bump the baked-in field counts 11 → 12 (see gotcha list).
- Then: `arena gate --candidate xs_regime --scenarios <all 5 synthetic>`.
  Record the verdict in CLAUDE.md arc status whatever it is. One attempt;
  if it fails, write the fold attribution before proposing anything else.

## Spec 2 — real-data gauntlet — DONE 2026-07-25

**Status: RUN. Bars are cached; both gate attempts FAILED on mean return.**
Full numbers, the inverted-vs-synthetic finding, and the "the real pack is
*still* a selector no-op on 2 of 3 scenarios" attribution are in the CLAUDE.md
arc-status block ("Real-data gauntlet"). Read that before proposing a third
candidate — the conclusion is that the **scenario library**, not the candidate,
is what needs work.

Two defects surfaced and were fixed in the same change (both have CLAUDE.md
gotchas): `BarCache` coverage is now a recorded manifest rather than inferred
from bar timestamps (real calendars never land on the requested boundaries, so
`real_*` could not replay offline at all), and `RegimeSwitchSelector` no longer
emits verdicts before its own `required_history`.

Scenarios already shipped: `scenarios/real_bear_2022.yaml`,
`real_recovery_2023.yaml`, `real_full_cycle.yaml` (source: alpaca; pull
commands in each file's header; cached bars replay offline afterwards).

- Ops order: `tradebot data pull ...` per YAML → `arena run` each scenario
  (journaled) → `arena gate --candidate xs_momentum_vt --scenarios
  scenarios/real_*.yaml` and same for any new candidate. One superset pull
  (`--symbols SPY QQQ IWM --start 2021-12-01 --end 2024-06-30`) covers all
  three windows. Note `data pull` needs the `[live]` extra installed
  (`pip install -e ".[live]"`) — the core deliberately has no Alpaca dep.
- Caveats to handle in interpretation, not code: IEX volume ≈2% of consolidated
  (irrelevant here — no volume screens in these scenarios); real calendars
  have gaps/halts — `Backtester` aligns on index intersection already; warmup
  eats the first ~60-90 bars of each window (the gate compares against the
  baseline over the same curve, so this is fair, but note it when reading
  absolute returns).
- Success criterion for promotion stays the same gate; a pass here plus a
  walk-forward on the pulled data = promote per the README runbook.

## Spec 3 — paper season ops (after keys)

- `arena season create --name paper1 --symbols SPY QQQ IWM --algos ./algos
  --score worst_fold` then `arena season run <id>` (daemon: market-hours
  gated; `--simulate` dry-runs the daemon offline).
- KNOWN HAZARD (CLAUDE.md gotcha): season recompute is thread-isolation;
  over-budget contestants leak busy threads per tick. Keep `meta_leader` /
  `meta_vote` OUT of long seasons until someone implements a per-season
  time-budget or process-isolated recompute (acceptable follow-up work:
  plumb `isolation=` through `SeasonConfig`).

## Spec 4 — backlog (build only on explicit ask; designs locked here)

### 4a. Bracket / stop-loss / take-profit orders
- Config: `risk: {stop_loss_pct, take_profit_pct}` (both optional, fractions
  of entry price). They live on `RiskConfig` — risk stays centralised;
  strategies still emit only {-1, 0, +1}.
- `models.py`: `Order` gains optional `stop_loss: float | None` and
  `take_profit: float | None` *price* fields (absolute prices, computed by
  the engine from entry price × config at submit time).
- `Broker` ABC: extend `submit(order)` semantics only — no new methods.
  `AlpacaBroker` maps to `order_class="bracket"` (lazy SDK import as ever).
  `DryRunBroker` simulates triggers each loop pass from the bar's high/low
  (stop fires before target on the same bar — pessimistic, deterministic),
  emitting a synthetic exit fill; this keeps the whole feature offline-testable.
- Engine seam: `Engine._submit_delta` attaches bracket prices on *entries
  that increase |position|*; reductions/exits never carry brackets. Backtester
  parity is explicitly NOT required (brackets are a live-execution concern);
  document that divergence in CLAUDE.md invariants when built.
- Tests: DryRunBroker trigger unit tests (gap-through-stop, same-bar both,
  no-trigger) + a replay dry-run showing a stopped-out position.

### 4b. Websocket streaming data
- New `data/stream.py`: `AlpacaStream` wrapping `alpaca-py`'s
  `StockDataStream` (lazy import), interface
  `run(symbols, on_bar: Callable[[str, pd.DataFrame], None])` delivering
  1-bar frames in canonical `BAR_COLUMNS` shape; plus `FakeStream(frames)`
  for tests (replays a dict of frames bar by bar, no network).
- First consumer: the season's live feed (`season.py LiveSeasonFeed` gains a
  `stream=` alternative to polling). The `Engine` keeps polling — do NOT
  rewrite the rebalance loop; streaming is a data-arrival optimisation, and
  bars remain the source of truth (dedupe by PK is already idempotent).
- Tests: FakeStream-driven season tick test; no `[live]` extra imports at
  module top (import isolation invariant).

### 4c. Notifications (fills + circuit breaker)
- New `notify.py`: `Notifier` protocol with `send(event: dict) -> None`;
  `WebhookNotifier(url)` POSTing JSON via stdlib `urllib` (no new deps);
  `LogNotifier` default. Config block: `notify: {webhook_url: ...}`.
- Engine hooks (constructor-injected, default `LogNotifier`): after each
  submitted order (symbol, side, qty, price, mode) and on the daily-loss
  halt. Delivery failures are logged and swallowed — never block or crash
  the trade loop. Season daemon may reuse the same notifier for standings.
- Tests: injected recording notifier in a replay dry-run (fill events seen,
  halt event on a forced breaker trip); webhook adapter tested against a
  local `http.server` thread — still offline.

### 4d. Container isolation for the arena
Deferred by owner decision — do not build without a new ask (rationale and
the `ContainerRunner` seam are recorded in CLAUDE.md's Deferred section).

## Non-goals (owner-locked, do not re-propose)

Mean-variance/Markowitz, Black-Litterman, fundamentals screens, shorting by
default, yfinance. See CLAUDE.md Roadmap.
