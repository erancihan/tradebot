# Design handoff — next implementations

For any agent/model continuing this project. **Read `CLAUDE.md` first**: it is
the system map, the invariants (paper gate, no look-ahead, risk centralised,
lockstep engines, offline-first), the gotchas, and the honest research record.
This document only specifies work that has NOT been built yet, precisely
enough to implement without re-deriving decisions.

> **⚠ Superseded in part, 2026-07-25.** A full-codebase audit found 16 confirmed
> defects, including a look-ahead in the *sizing* path of both execution loops
> that puts the entire recorded research record under retraction. **`docs/PLAN.md`
> is now the ordering authority** for what to do next; it supersedes the
> "next move" guidance in Spec 1 and Spec 2 below. The Spec 4 backlog designs
> (4a bracket orders, 4b streaming, 4c notifications) are unaffected and still
> apply as written.
>
> **Every spec in this document is now BUILT (4a/4b/4c shipped 2026-08-05),
> except 4d, which is deferred by owner decision.** Nothing here is
> outstanding work; it reads as the record of what was specified and what the
> implementation decided. New work needs a new design.

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

## Spec 3 — paper season ops — DONE 2026-07-26

**Status: VALIDATED end-to-end.** `arena season create` + `season run
--simulate` drives the whole daemon offline (12 ticks, standings recomputed and
persisted per tick, resumable). A live tick against Alpaca then accumulated
real bars — the proof that mattered, because before B2 the live feed silently
accumulated **zero**: it marked a bar seen the moment it was offered, and the
daemon then discarded it as still-forming, so it was never offered again once
it settled. The validation run used the affordable contestants only, because at
the time the thread-pile-up hazard below was still open; it is now closed —
`--isolation process --time-budget N` makes the budget a hard kill, so the full
field can run.

## Spec 3 — original notes (after keys)

- `arena season create --name paper1 --symbols SPY QQQ IWM --algos ./algos
  --score worst_fold` then `arena season run <id>` (daemon: market-hours
  gated; `--simulate` dry-runs the daemon offline).
- ~~KNOWN HAZARD: season recompute is thread-isolation; over-budget
  contestants leak busy threads per tick.~~ **CLOSED 2026-08-05.** The
  follow-up named here is done: `SeasonConfig` carries `isolation` *and*
  `time_budget_s`, surfaced as `season create --isolation process
  --time-budget N`. Process isolation makes the budget a hard kill, so the leak
  is structurally impossible and `meta_leader`/`meta_vote` can run in a long
  season. Verified on the full 12-contestant field. Thread remains the default
  (faster, correct for affordable fields) with its soft budget documented on
  the flag. Closing this also fixed a silent bug — `harden=False` was hardcoded,
  so a process-isolated season ran unsandboxed while reporting `ok`.

## Spec 4 — backlog

**4a, 4b and 4c are BUILT (2026-08-05)** on the owner ask "complete the
roadmap". The designs below are kept verbatim as the record of what was
specified; each carries a note on where it landed and where the implementation
made a call the design left open. 4d remains deferred.

### 4a. Bracket / stop-loss / take-profit orders — DONE 2026-08-05

**Built as specified**, with three decisions the design left open:
- `models.opens_exposure(current, delta)` is the shared entry predicate, so the
  engine (what to attach) and `DryRunBroker` (what to keep resting) cannot
  disagree. A **flip** counts as an entry; a reduction never does.
- `DryRunBroker.check_brackets()` is duck-typed off the `Broker` ABC (the spec
  said "no new methods" — a real broker holds the legs itself, so only the
  simulator needs the hook). `Engine._check_brackets` calls it via `getattr`,
  **before** it reads the account, so a stop that fired this bar is booked
  before sizing.
- One leg only maps to Alpaca `order_class=oto`, not `bracket` (Alpaca rejects a
  one-sided bracket).
- Documented, deliberate: a bracket protects *between* passes. If the signal is
  still long after a stop fires, the next pass re-enters. Asserted by test.
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

### 4b. Websocket streaming data — DONE 2026-08-05

**Built as specified.** `StreamSeasonFeed` (in `season.py`, next to the other
feeds) is the push→pull adapter rather than a `stream=` kwarg on the live feed:
the feed protocol is `next()`, so buffering pushed bars per symbol and draining
one each keeps the season loop untouched. `start(background=False)` runs the
stream inline, which is what makes `FakeStream` deterministic in tests.
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

### 4c. Notifications (fills + circuit breaker) — DONE 2026-08-05

**Built as specified**, plus a third event: `bracket_exit` (4a's synthetic
exits). `build_notifier` returns log **and** webhook when a URL is set, never
webhook-only — the log line is the local audit trail and survives a dead
endpoint.
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

---

## Spec 5 — the consortium (owner ask 2026-08-05)

> **Locked design. Written before any code, per the working agreements.**

### The problem it solves

The pass gate is a **promotion** device: one candidate, binary verdict, all or
nothing. Nothing has ever passed it, so nothing ships, and the project has been
stuck there for two arcs. The owner's reframing: don't bet on one algorithm —
run many side by side, show what each recommends, and let *voice* be continuous
rather than membership binary. A member that loses money is not evicted; it is
progressively silenced, and it can recover.

That changes the gate's job rather than retiring it. The gate becomes an
**admission** test (is this sane, complete, non-catastrophic?), which is exactly
the split the M5 resolution just made explicit: absolute drawdown → admission,
relative drawdown → competitiveness → voice.

### What already exists (do not rebuild)

`arena` runs N contestants side by side. `league`/`season` evolve their
standings over wall-clock time, durably. `strategies/meta.py` already does
adaptive weighting (`FollowTheLeader`) and agreement (`EnsembleVote`) — but over
sub-*strategies*, not over arena contestants. The gap is one layer: nothing
aggregates *contestant* recommendations into a single book with attribution.

### Core definition

A member's **recommendation** at bar `t` is the book it would hold if it were
trading the whole account alone: a weight vector over symbols. This is a
modelling choice and it must be stated wherever results are quoted — a member
sized against the consortium's capital is not the same object as a member sized
against a slice of it.

Recommendations are extracted at the one point where all three contestant kinds
converge: the `desired` quantities `simulate` hands to `RiskManager.allocate`.
Vectorized, event and portfolio members therefore all produce the same shape,
and cross-sectional members are first-class rather than a special case.

- `simulation.simulate` gains an **optional `on_decision` callback**, invoked
  once per bar with `(i, ts, targets, desired, equity, prices)`. It observes;
  it must not influence the loop. Default `None` keeps every existing call
  byte-identical, so the backtest/arena lockstep test is untouched.
- `arena/panel.py` runs each member **once** through `simulate` with that hook
  and returns a per-member `DataFrame` of weights (bars × symbols) plus the
  member's own equity curve. Cost is `O(members × bars)`, not
  `O(members × bars²)` — the trap `_TailBounded` was invented for.

### Voice

`tradebot/consortium.py`:

- `EqualVoice` — every member `1/N`. **The default, and the baseline any other
  scheme has to beat.** Equal weighting over a diverse panel is famously hard
  to improve on.
- `HedgeVoice(eta, floor)` — exponential weights: `w_m ∝ exp(eta · cumulative
  log return of m up to t-1)`, renormalised, with a **floor** so no member is
  ever fully silenced. The floor is the owner's requirement made literal:
  failures stay in the mix and can recover. Hedge is chosen over greedy
  leader-following because it carries a regret bound — it provably does no
  worse than the best member in hindsight, up to a log term. `FollowTheLeader`
  carries no such guarantee, and the canary evidence in CLAUDE.md says
  trailing-return selection is a coin flip at these sample sizes.

Voice at bar `t` uses member curves strictly before `t` — the same one-bar
discipline as every other decision in the codebase, and prefix-stable by
construction.

### Combination

```
score(s, t) = Σ_m voice_m(t) · weight_m(s, t)      # signed
target(s, t) = sign(score)                          # stays in {-1, 0, +1}
raw_weight(s, t) = |score|                          # agreement == conviction
```

Weights are then normalised across symbols and handed to `RiskManager` exactly
like an allocator's output. **Sizing stays with the RiskManager** — the
consortium proposes, risk disposes. Disagreement shrinks a position rather than
producing a coin flip, which is the property that makes the panel worth having.

### Part A — the advisory panel (build first)

Read-only. No capital at risk, no research risk.

- `web/services/consortium_service.py` — builds the panel from stored bars +
  loaded algos, via `arena/panel.py`.
- `/api/consortium` (JSON), `/partials/consortium`, and a `/consortium` page:
  every member, its current recommendation per symbol, its voice, its trailing
  performance. Server-rendered partial reusing the existing `partialLoader` —
  no new TS, same approach as the allocations card.
- Layering stays `routes → services → repository`; the trading core still must
  not import `web/`.

### Part B — the consortium as a contestant (build second)

`algos/consortium.py`, registered like any other contestant, so it must beat
`buy_and_hold` on the same gauntlet as everything else. Being the framework
earns it no exemption — that is the whole point of building it this way.

- **Self-exclusion is mandatory and tested.** A consortium whose member paths
  include `./algos` would load itself and recurse forever. Members are filtered
  by a marker attribute, not by name matching.
- The `algos/` head-count goes 12 → 13. Four test files assert on it (see the
  CLAUDE.md gotcha); update all four.
- Run it through the balanced factor library and the real `xs_*` pack, journal
  the attempts, and record the verdict **whatever it says**.

### Known limits — state these wherever results are quoted

1. **The current roster is not diverse.** Twelve contestants, mostly
   trend/reversion variants over one equity-beta pool. Averaging correlated
   members reduces estimation noise, not systematic exposure. A consortium over
   this roster is one strategy wearing twelve hats, and its measured benefit
   will be correspondingly small. The binding next constraint is *new member
   kinds*, not a better combiner. Do not report a consortium result without
   this caveat.
2. **"Any financial loss is a fail" is the consortium's objective, not a
   per-member gate.** Applied literally per member, only cash survives and the
   panel is empty. Losses set a member's voice; they never evict it.
3. **Adaptive voice must earn its place.** `HedgeVoice` is itself a research
   claim. Ship `EqualVoice` as the default and treat any adaptive scheme as a
   contestant that has to beat it — the project's own methodology, applied to
   the combiner.
