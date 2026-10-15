# Research record

This is the paper trail of the algorithms-research work. It states what was
built, what was measured on the fixed engine, the verdicts, and the decisions
that stand. Older numbers produced before the 2026-07-25 engine fix are not
kept here. They came from a biased engine and are retracted.

## Result in one line

No contestant passes the promotion gate. The trustworthy gauntlets give a
decisive FAIL. That is the honest result, not a bug.

## What was built

- **Arena.** Contestants, tournaments, league, durable season, and the
  experiment journal. Three contestant interfaces: event-driven `Algo`,
  vectorized `Strategy`, and `PortfolioAlgo` (a whole book competes as one
  entry).
- **Fold scorers.** `worst_fold` and `consistency` in
  `arena/scoring.py`. They cut one realized equity curve into contiguous folds.
- **Regime library.** `synthetic_regime_ohlcv` with piecewise drift and
  volatility. Four single-symbol scenarios: `bull_trend`, `sideways_chop`,
  `crash_recovery`, `vol_spike`.
- **Factor library.** `synthetic_factor_panel` draws one market factor per bar.
  Each symbol gets a beta, an alpha and idiosyncratic noise. `beta_shift`
  drags betas toward 1.0 to model crisis contagion. One fixed 8-name pool
  serves every scenario. The haven costs money to hold in calm regimes. Seven
  scenarios in mirror pairs:
  - selection rewarded: `xs_bull_dispersion`, `xs_chop_dispersion`
  - selection punished: `xs_momentum_crash`
  - defense rewarded: `xs_crash_haven`, `xs_vol_spike_down`
  - defense punished: `xs_crash_nohaven`, `xs_vol_spike_up`
- **Real cross-sectional pack.** `real_xs_2021`, `real_xs_2022`,
  `real_xs_2023`, plus the sealed holdout `real_xs_2024_2025h1`. Twelve
  symbols chosen by rule: the nine sector SPDRs that predate the span (a full
  S&P partition) plus TLT, GLD and SHY. Windows are disjoint calendar years.
  Alpaca's free IEX history starts 2020-07-27, so COVID and 2018Q4 are out of
  reach.
- **Legacy real pack.** `real_bear_2022`, `real_recovery_2023`,
  `real_full_cycle` (SPY, QQQ, IWM). Superseded. The windows nest inside each
  other and the selector is inactive on two of three. It stays only as a
  calendar and cost check.
- **Classic roster.** `donchian_breakout`, `macd_trend`,
  `bollinger_reversion`, plus the earlier `sma_crossover`, `rsi_reversion` and
  `buy_and_hold`.
- **Cross-sectional selectors.** `MomentumSelector` (with `reverse=True` for
  short-term reversal), `LowVolatilitySelector`, `RegimeSwitchSelector`
  (momentum in calm regimes, low-vol in storms).
- **Meta strategies.** `FollowTheLeader` (greedy bandit on trailing P&L) and
  `EnsembleVote` (a trade needs `min_agree` members in agreement).
- **Canaries** in `algos/canaries/`. Never promotable. `oracle_topk` selects
  on future returns and must win. `random_topk` is the null model.
  `always_haven` tests whether hiding is free.
- **Consortium.** A panel of the twelve contestants blended into one book.
  `EqualVoice` is the default. `HedgeVoice` weights members by trailing P&L
  with a floor.
- **Promotion gate.** `tradebot arena gate`, described below.

## The gate

`arena/gate/`, run as `tradebot arena gate --candidate X --scenarios ...`.
The baseline defaults to `buy_and_hold`. The exit code is the verdict. All
criteria are required:

| criterion | rule |
|---|---|
| completes | the candidate finishes every scenario |
| return | mean CAGR beats the baseline (length-normalized) |
| worst fold | `worst_fold` >= baseline in a strict majority of scenarios |
| absolute drawdown | never worse than −35% (admission: "is this catastrophic?") |
| relative drawdown | no worse than the baseline, only where the baseline itself breaches −35% (competitiveness) |

Supporting rules:
- **Warmup rebasing.** Both contestants are scored from the bar where the
  later of the two starts trading. `buy_and_hold` has no warmup, and a 60-bar
  momentum selector is flat for 61 bars. Without rebasing, the comparison is
  unfair.
- **Fold sensitivity.** The gate prints the worst-fold win count for k=3..8.
- **Seed ensembles.** `--seeds N` re-draws the gauntlet, takes the median per
  criterion. A verdict that flips across draws prints `UNSTABLE`.
- **Degeneracy report.** The gate prints "selector active %" per scenario.
  Provider scenarios that share one price path print `WINDOWS OVERLAP`.
- **Provenance.** Every journal row carries `ENGINE_VERSION`, the library
  content hash, the start and final balance, and the simulated window.
  `arena journal --export ledger.csv` makes the ledger committable.

## Measured verdicts (current engine)

### `xs_momentum_vt` on the balanced factor library (7 scenarios): FAIL

| criterion | result |
|---|---|
| mean CAGR | 2.03% vs 11.17% |
| worst fold | 3/7 |

It wins both crash scenarios and loses the other five. The library runs
89–100% selector-active. This is the gauntlet to judge on.

### `xs_momentum_vt` on the real cross-sectional pack (2021, 2022, 2023): FAIL

| criterion | result |
|---|---|
| mean CAGR | −1.30% vs 6.87% |
| worst fold | 0/3 |

The pack runs 98–100% selector-active. Sector dispersion is 40–113pp a year.
The haven fails in 2022 (TLT −33% next to equities) and GLD works in 2023–25,
so no candidate wins by owning bonds alone.

### Regime library (4 single-symbol scenarios plus `cross_sectional`): FAIL

| candidate | mean CAGR | worst fold | deepest DD | fails on |
|---|---|---|---|---|
| `xs_momentum_vt` | 10.41% vs 6.84% | 4/5 | −36.38% | absolute drawdown, by 1.38pp |
| `xs_regime` | not re-run on CAGR | 5/5 | −52.86% | absolute drawdown |

On `crash_recovery`, `buy_and_hold` takes −52.91%, so the relative drawdown
check passes there. The absolute bound still fails. Four of these five
scenarios hold one symbol, so a selector has nothing to choose and the book
degenerates to `buy_and_hold`. This library carries no evidence about
cross-sectional selection.

### Consortium, equal voice, balanced factor library: FAIL

| criterion | result |
|---|---|
| completes | 7/7, pass |
| mean CAGR | 3.37% vs 9.17%, fail |
| worst fold | 5/7, pass at every k from 3 to 8 |
| absolute drawdown | −40.56%, fail (baseline −49.11%) |
| relative drawdown | 2/2, pass |

The baseline figure differs from the `xs_momentum_vt` run because rebasing
depends on the pair's warmup. The consortium beats `buy_and_hold` on every
fold measure and on drawdown in both crashes (−33.64% vs −45.93%,
−40.56% vs −49.11%). It loses on return because it dilutes the rallies
(`xs_vol_spike_up` 76.60% vs 136.64%, `xs_momentum_crash` 1.77% vs 20.90%).
Averaging correlated members lowers variance and return together.

### Consortium, hedge voice (eta=2.0, floor=0.02): FAIL

Mean CAGR 3.68% against equal voice's 3.37%. Same verdict, same criteria
pattern, worst fold 5/7. The largest single-scenario effect is +12pp on
`xs_vol_spike_up` (88.84% vs 76.60%). It loses `xs_momentum_crash` and
`xs_chop_dispersion`. Adaptive voice reallocates noise.

### Canaries (8 draws of the factor library)

- `oracle_topk` wins every draw, by +152% to +351%. The signal is there.
- `xs_momentum` beats `random_topk` in 4 of 8 draws. A 60-bar trailing-return
  selector picking 2 of 8 names does not reliably extract a +0.0002/bar alpha
  spread against 0.010/bar noise on one 500-bar path.
- `always_haven` is competitive in flat and falling markets, as a low-beta
  asset with carry is. Hiding is costly only where the market rises.

## The lesson about point estimates

The legacy real pack's verdict flipped four times as four honest corrections
landed (engine fix, CAGR instead of total return, warmup rebasing). It ended
at a PASS of 10.98% vs 9.52%. The gate reports that pack as 0%, 0% and 38%
selector-active with overlapping windows. A verdict that reverses on margins
of 0.4–1.5pp is not a measurement. The gate reports point estimates with no
interval (M4, open). Do not promote on a margin inside the noise, and do not
read "nearly passed" as a near miss to nudge over.

## Defects found by the 2026-07-25 audit

All fixed unless marked.

| id | defect | status |
|---|---|---|
| B1 | Both loops sized a fill at bar `i`'s open using equity marked at bar `i`'s close. Perturbing only bar 60's close moved the filled quantity from 96.455539 to 81.893842. | fixed: `_sizing_marks` marks at the fill bar's open |
| B2 | The live season feed marked a bar seen before it closed, so a live season stored zero bars. | fixed |
| B3 | `RankedSelector._closes` aligned on the union of indexes and fabricated NaN scores. | fixed: intersection |
| B4 | The coverage manifest recorded an unbounded claim after an unbounded pull. | fixed: records fetched bounds, skips empty fetches |
| B5 | Dashboard stat cards mixed equity across modes. | fixed |
| B6 | The live engine ran the selector over a truncated window. | fixed: full history from `Storage` |
| B7 | A `.env` file made the offline suite call Alpaca. | fixed: socket guard in `tests/conftest.py` |
| B8 | The backtester computed signals on raw frames, the arena on aligned frames. | fixed: targets after alignment |
| B9 | The one-bar shifts had only lockstep guards. | fixed: absolute single-engine guards |
| B10 | `record_bars` froze the first, still-forming bar. | fixed: upsert |
| B11 | `/api/bars` ignored timeframe and mode. | fixed |
| B12 | The SSE stream blocked the event loop on broker I/O. | fixed: `asyncio.to_thread` |
| B13 | `BarCache._slice` excludes the end date's own session. | accepted: half-open range, see CLAUDE.md |
| B14 | The runner discarded the sandbox capability report. | fixed: reported once per mechanism |
| S1 | `exit_rank` froze membership on small pools: zero changes across 587 live bars. | fixed |
| S2 | `RegimeSwitchSelector` emitted verdicts before its own warmup. | fixed: leading rows masked |

Methodology corrections:

| id | correction | status |
|---|---|---|
| M1 | Retract numbers from the biased engine. | done |
| M2 | Warmup discipline in the gate. | done: rebasing |
| M3 | Length-normalize returns. | done: mean CAGR |
| M4 | Report an interval, not a point estimate. | open |
| M5 | Split absolute and relative drawdown. | done |
| M6 | Report worst fold across k=3..8. | done |
| M7 | Fold scorers are in-sample for the analyst. | documented |
| M8 | Durable journal, candidate-only journaling. | done, journaling stays CLI-only |
| M9 | Provenance on every number. | done: `ENGINE_VERSION` |
| M10 | Cost model differs from production. | documented, see CLAUDE.md |
| M11 | Window selection bias. | documented, plus a sealed holdout |

## Standing decisions

Do not re-chase, re-propose, or "fix" these without a new owner ask.

- **Do not tune the gate.** No lower drawdown limit, no dropped return check,
  no plurality instead of strict majority, no revert of the CAGR fix. Each
  bound is doing its job.
- **Do not use `absolute OR relative` drawdown.** It converts the recorded
  1.38pp synthetic FAIL. Both checks are required.
- **Do not sweep parameters to clear the gate.** This covers `storm_vol`,
  `vol_window`, `target_vol`, `lookback` and voice `eta`. That fits the
  test bench. The next iteration needs a different idea.
- **Do not search seeds or edit a scenario after seeing a result** without a
  library version bump. Seed search is the cheapest way to fake a pass.
- **Do not deepen scenario drifts until every seed complies.** It takes
  ±0.0090/bar, which produces a +295% 80-bar "recovery". Fix the evaluation
  with `--seeds`, not the data.
- **Do not trim a meta or consortium roster to fit a time budget.** Raise the
  budget instead.
- **Do not re-pick the factor pool per scenario.** It is the cheapest way to
  flatter a candidate.
- **Do not improve the consortium by tuning voice.** The binding constraint is
  member diversity. The next useful work is member kinds uncorrelated with the
  current twelve.
- **Do not read the regime library or the legacy real pack as evidence about
  selection.** Use the balanced factor library for verdicts.
- **Run the sealed holdout `real_xs_2024_2025h1` once, last,** and record
  whatever it says.
- **Non-goals:** mean-variance or Markowitz optimizers (error maximizers),
  Black-Litterman, fundamentals or value screens (no Alpaca data), shorting by
  default, yfinance as a real dependency.
- **Container or gVisor isolation is deferred.** Contestant code is
  human-reviewed, so `--harden` and `--seccomp` match the threat model. If
  unreviewed third-party code is ever accepted, add a `ContainerRunner` behind
  `default_runner` with `isolation="container"`.
