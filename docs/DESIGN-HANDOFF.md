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
- The `algos/` head-count (currently 11) is baked into tests listed in the
  CLAUDE.md gotcha. CLI arena tests must pass `--db <tmp>` or `--no-journal`.
- Every simulation surface shows start/final balance + simulated period
  (tests/conftest.py ledger, journal columns). Preserve this in new outputs.

## Spec 1 — RegimeSwitchSelector (the next gate candidate)

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

## Spec 2 — real-data gauntlet (needs user's Alpaca keys, once)

Scenarios already shipped: `scenarios/real_bear_2022.yaml`,
`real_recovery_2023.yaml`, `real_full_cycle.yaml` (source: alpaca; pull
commands in each file's header; cached bars replay offline afterwards).

- Ops order: `tradebot data pull ...` per YAML → `arena run` each scenario
  (journaled) → `arena gate --candidate xs_momentum_vt --scenarios
  scenarios/real_*.yaml` and same for any new candidate.
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

## Spec 4 — backlog seams (build only on explicit ask)

- **Bracket/stop orders**: seam is `broker/base.py Broker` ABC +
  `engine.Engine._submit_delta`. Keep `RiskManager` the sizing authority;
  brackets are exit *placement*, not sizing. Dry-run broker must simulate
  triggers off bar highs/lows to stay offline-testable.
- **Websocket streaming**: seam is `data/` (new `AlpacaStream` alongside
  `AlpacaData`); engine keeps polling as fallback; season's live feed is the
  first consumer. All tests offline via an injected fake stream.
- **Notifications**: post-fill + circuit-breaker hooks in `Engine`; a simple
  webhook/email adapter; never block the trade loop on delivery.
- **Container isolation for the arena**: deferred by owner decision — do not
  build without a new ask (rationale recorded in CLAUDE.md).

## Non-goals (owner-locked, do not re-propose)

Mean-variance/Markowitz, Black-Litterman, fundamentals screens, shorting by
default, yfinance. See CLAUDE.md Roadmap.
