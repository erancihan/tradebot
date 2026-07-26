# tradebot — engineering plan (2026-07-25)

Produced by a full-codebase audit: six parallel subsystem reviews, adversarial
verification of each finding, four independent roadmap assessments, and
synthesis. 16 defects confirmed, 1 refuted, 3 unverified minors.

**Read `CLAUDE.md` first.** This document supersedes the "next arc" guidance in
`docs/DESIGN-HANDOFF.md`; the locked backlog designs there (Spec 4a/4b/4c) are
unchanged and still apply.

## Verification status of the claims below

Honesty about provenance matters here, because the headline finding is that a
previous set of recorded numbers was produced by a biased instrument.

- **Verified directly, in this session, by execution:** B1 (the sizing
  look-ahead — reproduced below), the absence of `.github/`, the absence of any
  `trading-bot/` directory, `arena.db` containing zero rows, the repo layout.
- **Reported by audit agents with reproductions they ran, not re-run here:**
  every other confirmed defect (B2–B14), and all quantitative counterfactuals —
  the per-scenario bias magnitudes, the claim that three gate criteria change
  state under a corrected mark, the seed-ensemble instability figures, the
  turnover and cost-sensitivity numbers.

Treat the second category as strong but provisional. Stage 1 exists partly to
re-derive it first-hand.

---

## 1. Roadmap evaluation

The engineering is in better shape than the docs; the research record is in
worse shape than the docs.

Nearly everything the Roadmap lists as Done is genuinely present: the arena's
isolation/hardening/seccomp tiers, league, season + daemon, the portfolio stack,
the Alpaca universe screen, overlays, walk-forward, and all five
algorithms-research stages exist and behave as described. 260 tests collect and
pass offline.

Three failures, in increasing severity:

**Coordinates are wrong.** The entire Layout tree and every copy-pasteable
command in `CLAUDE.md` is rooted at `trading-bot/`, which does not exist. The
project root *is* the repo root. Verified: no such directory, and no such path
in git history.

**CI is claimed and does not exist.** `CLAUDE.md` asserts
`.github/workflows/trading-bot-ci.yml` runs pytest plus the frontend typecheck.
There is no `.github/` directory. The two mechanical gates in the
Definition-of-done have never been enforced automatically. `frontend/node_modules`
is also absent, so `npm run typecheck` cannot currently run at all.

**The arc-status block was produced by a biased engine.** This is the serious
one. `backtest.py:167` marks the sizing equity at bar `i`'s close and then fills
at bar `i`'s open (`:191`). Every number in the research record — four gate
verdicts, every fold attribution, the `make test` balance ledger — came out of
that loop. The audit's re-derivation reports that the top-line verdicts survive
(both candidates still FAIL) but the per-scenario attributions invert, which
would make the block's most valuable content — its "do not re-chase" guidance —
wrong in at least two of three cases.

Separately, `arena.db` holds zero rows. This is not evidence of dishonesty: the
journal DB is gitignored and every session runs in a fresh container, so it is
ephemeral by construction. But it means **the attempt counts cited in the record
cannot be audited from the repo**, and it explains why two counts in the same
document disagree (55 at one point, 34 later — different ephemeral databases,
not a counter running backwards). The fix is durability, not blame.

### Corrections needed in CLAUDE.md

1. Delete the `trading-bot/` prefix everywhere (lines 17, 34, 45, 129, 143, 152–153).
2. Remove the CI claim, or build `.github/workflows/`. Do not leave it asserted.
3. Add `docs/DESIGN-HANDOFF.md` and this file to the Layout; an agent following
   CLAUDE.md's own reading order never finds either.
4. Layout omits `RegimeSwitchSelector` / registry name `regime_switch`, despite
   it being the subject of a gate attempt and a gotcha. Also missing from
   `config.example.yaml`.
5. CLI line undersells the surface: add `tradebot universe`, `arena {league,
   season,gate,journal}`. Unlisted modules: `arena/contestant.py`,
   `web/server.py`, `web/dependencies.py`, `web/routes/sse.py`; root files
   `config.example.yaml`, `.env.example`, `data/cache/`, `docs/`, `LICENSE`.
6. **False as written:** "the live engine keeps no selector state — it
   recomputes from full fetched history every pass". `engine.py:146` fetches a
   truncated trailing window. Prefix-stability licenses recomputing a *prefix*;
   it says nothing about truncating the *head* of a hysteresis walk. See B6.
7. **False as written:** the cache gotcha says the manifest lists windows
   "actually pulled". `record_coverage` records the caller's *requested* bounds.
   The code's own docstring says so. See B4.
8. **False as written:** "the baseline runs the same curve, so the comparison is
   fair" (warmup caveat). `buy_and_hold` has zero warmup; `MomentumSelector(60)`
   is flat for 61 bars. See M2.
9. Mark both fold-attribution blocks and the real-data table as **produced by an
   engine with a confirmed look-ahead; retracted pending re-derivation**.
10. Replace the attempt counts with an honest statement of what the ledger
    currently proves (nothing, because it is ephemeral) until M8 lands.

### Degradations to record as gotchas

- Dashboard positions: `web/services/account_service.py:26` returns `[]` without
  Alpaca credentials, so the positions card is permanently empty on the offline
  path the project privileges. README's "from the SQLite log" is never true.
- `arena/market.py` `DEFAULT_HOLIDAYS` covers 2024–2026 only. It expires in ~5
  months, after which the season daemon treats 2027 holidays as trading days.
- Stale module docstrings contradicting shipped code: `arena/season.py`
  ("NOT covered here: hardened daemon, market-hours scheduling, partial-bar
  handling" — all three ship in that file), `arena/scenario.py` ("alpaca …
  arrives in Phase 2" — implemented), `arena/sandbox.py` ("see `container.py`" —
  no such file).
- README is the stalest doc: "~225 tests" against 260, and its Roadmap still
  lists the shipped dashboard as a future idea.

---

## 2. Bug backlog

Ordered by severity, then effort. Two pairs in the raw findings were the same
defect reported by two auditors; merged here.

### Fix now

**B1 — Sizing equity is marked at the fill bar's close.** CRITICAL, small code /
large consequences.

Both execution loops fill at bar `i`'s open but compute the equity used to size
that fill by marking the book at bar `i`'s close.
`tradebot/backtest.py:166-167` → consumed at `:191` (`risk.allocate`) and `:195`
(`risk.material_delta`) against `bar_prices` = opens. Same defect at
`tradebot/arena/simulation.py:77`.

Reproduced here directly. Synthetic 200 bars, seed 3, `BuyAndHold`, fractional
sizing. Perturbing **only** the close of bar 60 — strictly future relative to
that bar's open, which is unchanged — moves the equity handed to `risk.allocate`
from 9785.15 to 8307.91 and the target quantity filled at that open from
96.455539 to 81.893842. All sizing decisions before bar 60 are byte-identical.
Equity is the only channel.

Blast radius: every backtest, tournament, league, season recompute, gate verdict,
walk-forward fold and journaled balance ever produced. The bias is **not uniform
and does not cancel** between candidate and baseline — it scales with how fully
invested and how often rebalanced a contestant is, so the always-at-the-cap
`buy_and_hold` baseline harvests it hardest. The direction is toward inflation,
so the failure mode is a **false PASS**.

This is the same class as the `RegimeSwitchSelector` warmup defect fixed
earlier: each part honours its contract (targets are shifted,
`test_allocator_never_sees_the_fill_bar` pins the allocator to bars `0..i-1`)
but the *composition* leaks the fill bar in through the equity mark, and no test
guards that channel.

Fix: split the reporting mark from the sizing mark. Keep
`equity_points.append(pf.equity(close_prices))` — end-of-bar reporting is
correct. Compute a separate `sizing_equity` marked at the fill bar's open
(falling back to the previous close where an open is unusable), or at the
previous bar's close, which is exactly what the live engine sees. Must land in
`backtest.py` and `arena/simulation.py` in the same commit or the lockstep test
fails. **Pre-register which mark, and why, before running anything.**

**B2 — Live season feed loses every bar.** MAJOR, small.
`AlpacaSeasonFeed.next` marks a timestamp seen the first time it is *offered*
(`season.py:313`); `run_season_daemon` then discards it as still-forming. A bar
offered before it closes is never re-offered after it closes, so a live daily
season accumulates **zero** bars while reporting healthy ticks. This is why
"go paper-forward now" is not currently an available option. Fix: filter for
completeness inside the feed, before the dedup — or drop the dedup entirely,
since the `(season_id, symbol, ts)` PK exists to make re-feeds idempotent. Note
`append_bars` is `INSERT OR IGNORE`, so a partial bar that does land can never
be corrected.

**B3 — `RankedSelector._closes` union-aligns, fabricating NaN scores.** MAJOR, small.
`selection.py:102` builds the price matrix via `pd.DataFrame({s: f["close"]})`,
which aligns on the **union** of per-symbol indexes. Only the live engine passes
unaligned frames, so this is a pure backtest-vs-live divergence: one missing
session inserts NaN closes and blanks a symbol's score for a whole rolling
window. Invisible offline because every fixture shares an index. Fix: intersect,
matching what both execution loops already do. Apply identically to
`RegimeSwitchSelector._storm`, which calls `_closes` directly.

**B4 — Coverage manifest records the request, not the fetch.** MAJOR, small —
**but scope narrowly.** Shipped in the previous commit, so this is a regression
introduced this session. `record_coverage` writes the caller's `[start, end]`
verbatim; `tradebot data pull` leaves both `None`, which becomes an unbounded
`_MIN_TS`/`_MAX_TS` claim. After any unbounded pull, `_spans` answers True for
every subsequent window, so a range never downloaded is served as an empty frame
instead of re-fetched.

Ship only: (1) skip `record_coverage` when the fetch came back empty; (2) when
`start`/`end` are `None`, record `fetched.index.min()/max()` rather than the
sentinels. **Do not** additionally clamp `hi = min(end, fetched.index.max())` —
the shipped manifest ends `2024-06-30` while the last bar is `2024-06-28` (a
Sunday end-date), so clamping makes `_spans` reject `real_full_cycle`'s own
declared window and reintroduces the bug commit `33379b9` fixed. Clamping needs
a manifest migration and must be proposed separately.

**B5 — Dashboard stat cards concatenate equity across modes.** MAJOR, small.
`web/routes/partials.py:21` and `pages.py:22` call `equity_series(limit=2000)`
with no mode filter, so a $100k paper account and a $10k dry-run become one
curve and the dashboard reports a drawdown that never happened. Fix: scope the
stats path to a mode and apply the same scoping to `latest_equity()`.

**B6 — Live engine recomputes selector membership over a truncated window.**
MAJOR, medium. `engine.py:146` fetches `lookback=self._lookback_days()`;
`:164` runs `selector.latest_targets` on it. `RankedSelector.membership` is a
path-dependent hysteresis walk seeded with an empty `held`, so its verdict
depends on where the frame starts — the live book holds a different set of names
than the backtest that validated it.

Fix (adjudicated): give the selector the full accumulated history. The engine
already persists every fetched bar, so read the full series back from `Storage`
and pass that, mirroring `season.py`. **Reject** the alternative of persisting
the selector's `held` set — that introduces exactly the per-contestant state the
season design deliberately avoids. Also convert `_lookback_days` to days
explicitly, and stop `ReplayData` silently ignoring `lookback`.

### Fix next

**B7 — A `.env` at the repo root makes the "offline" suite call Alpaca.** MINOR,
trivial. `tests/test_universe.py` deletes the env vars, but
`AlpacaCredentials.from_env()` calls `_maybe_load_dotenv()`, which re-reads
`.env` from the CWD. Two tests then make live HTTPS requests. This goes from
latent to live the moment credentials are in the environment. Fix: neutralise
dotenv in those tests, and add a session-scoped autouse fixture in
`tests/conftest.py` that blocks non-loopback `socket.connect` so any future
network-touching test fails loudly.

**B8 — Backtester computes signals on raw frames, arena on the intersection.**
MINOR severity, high sequencing importance, small. `backtest.py:148` computes
targets from each symbol's own unaligned frame; `simulation.py:120` feeds the
policy the intersection-aligned frame. Identical only when all symbols share an
index — which every lockstep fixture arranges and real bars do not guarantee.
**Must land before any multi-name real pack**; a 12-symbol pool has ragged
indexes by construction.

**B9 — The one-bar shifts have no absolute guard.** MINOR severity, high
durability importance, small. The `.shift(1)` on membership is protected only by
backtester-vs-arena lockstep tests. Deleting it from **both** loops — precisely
the coordinated edit CLAUDE.md's own gotcha instructs — introduces real
look-ahead and all 260 tests stay green. This is the structural reason B1
survived: *a lockstep test cannot catch an error made identically in both loops.*
Fix: single-engine, absolute-truth tests. **Rule to adopt: every shift gets one
non-relative guard.**

**B10 — `record_bars` freezes the first, still-forming version of each bar.**
MINOR, small. `storage.py:98` uses `INSERT OR IGNORE`, so the first write wins
permanently — but the engine polls intraday and the newest bar it persists is
today's partial. Fix with an upsert. **Land with B6**, which makes the persisted
history load-bearing.

**B11 — `/api/bars` ignores timeframe and mode.** MINOR, small.
`web/repository.py:65` has no `timeframe` filter although it is in the primary
key, so the chart draws duplicate overlapping candles.

**B12 — SSE stream does blocking broker I/O on the event loop.** MINOR, small.
`web/routes/sse.py` calls the synchronous `account_service.snapshot()` inside an
async generator; on the credentialed path that is three blocking HTTP round-trips
stalling every request while any tab holds the stream. Fix: offload to a thread,
or better, one shared poller so broker calls are independent of tab count.

### Accept and document

*"Accept and document" means writing a CLAUDE.md gotcha in the same change that
decides to accept it — not silence.*

**B13 — `BarCache._slice` excludes the end date's own session.** Adjudicated:
**do not change.** Two auditors reached opposite verdicts on this; the
refutation wins. The excluded bar lies outside the recorded manifest window, so
nothing false is claimed and a wider later request re-fetches. The convention
(start inclusive, end exclusive) is the standard half-open range applied
consistently to fetch, slice and manifest. The proposed "fix" would make
`_spans` reject `real_full_cycle`'s own shipped window — the same failure as
B4's rejected clause, from the other direction. Impact of leaving it: one
trailing bar out of 292/270/647, applied identically to candidate and baseline.
Write the gotcha instead.

**B14 — Unverified minors.** Record; fix opportunistically.
`arena/runner.py` discards the capability report from `apply_hardening`, so a
failed `unshare(CLONE_NEWNET)` leaves a contestant networked while the
tournament reports `ok` — this contradicts the module's own "never silently
downgrade" rule and deserves a gotcha even before it is fixed.
`arena/season.py` increments `ticks` after every `continue`, so `max_ticks`
bounds *applied* ticks but cannot terminate a run whose feed is dry.
`frontend/src/charts/equityChart.ts` `seasonOption` feeds each series
positionally against the longest curve, shifting late-joining contestants onto
the wrong steps.

---

## 3. Next arc

**Re-qualify the instrument, then rebuild the gauntlet — one arc, two stages,
with a hard gate between them.**

Stage gate, stated so it is checkable: *no new research measurement is
generated, and no scenario baseline recorded, until the perturbation guard (B9)
is green on a fixed engine (B1).*

### Why this ordering

Three of the four independent assessments put the engine fix first, and the
assessment arguing for the scenario library concedes the point in its own
sequencing section ("fix B1 before generating any library baselines — every
number shifts").

1. The bias does not cancel between candidate and baseline; it scales with
   exposure and turnover, and the baseline is the most exposed contestant.
2. The error direction is toward false PASS — the one failure mode the gate
   exists to prevent.
3. The record's "do not re-chase" guidance is its highest-value asset for a
   future agent, and it is built on attributions the audit reports as inverted.
   An agent obeying it abandons a possibly-correct idea for a fabricated reason.
4. The durable deliverable is the guard class, not the patch. The project's
   stated correctness argument is "backtest == live, guarded by lockstep tests".
   B1 and B9 together prove that argument unsound.
5. The reported bias is largest in exactly the regimes a new library must
   contain. Building the library first means constructing the discriminating
   test where the instrument is least accurate.

### Why not the alternatives

**Paper-forward now.** Superficially strongest — reality cannot be gamed by a
buggy backtester. Currently impossible: B2 means a live daily season accumulates
zero bars, silently. Beyond that the live path is a *different system* from the
researched one (B6, B3, B10), so a paper season would spend months producing one
data point from an untested execution path. A season whose feed silently drops
bars is a fake fair test — strictly worse than a known-biased backtest.

**Library first.** See point 5, and the library assessment's own concession.

**Fix the audit.** Explicitly out of scope: B5, B11, B12 and all frontend work
are real but no research decision depends on them.

### The honest case against

This arc produces zero new trading knowledge and the headline verdict does not
change — both gates still FAIL afterward. A reasonable person could land B1 as a
small patch, footnote the record, and spend the arc on the library where the
genuine constraint lives.

The concession: this arc's value is epistemic, not alpha. The counter is that
you cannot currently tell whether the *previous* arc produced trading knowledge.
Binding the re-derivation to the library build, rather than running it as a
standalone hardening arc, is the answer to this objection — the arc still ends
with a better test, not just a cleaner conscience.

### What would falsify this recommendation

Run these before committing to the arc; they are cheap.

1. Re-derive both gate verdicts with the mark moved to the fill-bar open. If no
   criterion changes state and the real-pack gap stays within ~0.5pp, the bias
   is inert at decision boundaries — downgrade B1 to a patch and go to the
   library. This is one script, and the whole plan rests on it.
2. Re-derive with the previous bar's close instead. If the two honest marks
   disagree materially (>2pp on any scenario), the choice of mark is itself a
   researcher degree of freedom and must be pre-registered.
3. If B2's feed fix is genuinely small, start a paper season in parallel on day
   one — it costs wall-clock, not attention — and let it accumulate during
   stages 1–3.

---

## 4. Scenario library plan

The binding constraint on the research programme is that **neither gauntlet
exercises the mechanism it is meant to test**. Verified on the shipped real
pack: momentum and regime-switch membership differ on 0 of 292 and 0 of 270
bars. `top_k=2` over a 2-symbol pool selects both names every bar.

### Three amendments the design must carry

**Seed ensembles are mandatory, not optional.** A single 500-bar draw recovers
the designed symbol ranking only ~48% of the time. Re-drawing the five current
synthetic scenarios 8× and re-applying the gate arithmetic reportedly yields
PASS on 2 of 8 redraws — the gate is adjudicating a ~1.9pp mean difference
against ~20pp of sampling noise. Ship `arena gate --seeds N` (default 10),
median aggregation, and an `UNSTABLE` verdict when the decision flips across
seeds. This is anti-flattery in both directions and cannot be aimed at a
candidate.

**The warmup honesty label is wrong.** Not "the baseline runs the same curve, so
it is fair" — `buy_and_hold` has no warmup and a 60-bar momentum selector is
flat for 61 bars. Fix it in the design, not the label: pull every real window
with `required_warmup` extra bars before its declared start, and score from the
declared start for both contestants. `walkforward.py` already owns this
discipline; the gate does not.

**Fix `exit_rank` for small pools first.** `exit_rank` defaults to
`top_k + max(top_k//2, 1)` = 3 for `top_k=2`. On a 3-name pool every held name
is permanently within `exit_rank`, so membership **freezes at the first
verdict**. On the shipped real pack `xs_momentum` reportedly picks its pair once
and holds it for all 647 bars. If true, the real gauntlet contains no evidence
about cross-sectional momentum at all — it measures one single-day pick frozen
for 2.5 years. **Verify this first; it is the single most consequential
unverified claim in the audit.**

### Synthetic set

A factor generator, not independent random walks. The current
`cross_sectional.yaml` has mean pairwise return correlation ~0.03 — six
unrelated random walks, where a "crash" is six unrelated accidents, every name
is a haven, and diversification is free.

```
F_t      ~ N(drift_seg, vol_seg)                  # one shared market path
beta_s,t = beta_s + beta_shift_seg * (1 - beta_s) # crisis correlation shock
r_s,t    = alpha_s,seg + beta_s,t * F_t + N(0, idio_s)
```

One fixed pool across every scenario, never re-picked per scenario — that alone
removes the largest flattery lever. High-beta growth (β 1.3–1.4), market-like
(β 1.0), defensive (β 0.6–0.7), a persistent laggard whose rejection must *pay*,
and a haven (β −0.2) that **costs to hold**, so "always hide" cannot win and
only timing the rotation can.

Seven schedules, balanced so no single mechanism can sweep a strict majority:
bull dispersion and chop dispersion reward selection; a momentum crash punishes
it; a crash with a haven and a downward vol spike reward defense; the same crash
with correlations driven to 1, and an *upward* vol spike, punish it. Mirror
pairs differ by exactly one parameter.

### Real set

A pool of 12 chosen by rule, not taste: the nine sector SPDRs that predate the
span (a complete partition of the S&P 500, so there is no discretion in the
pick) plus TLT, GLD, SHY. This satisfies both requirements the current pack
fails — real sector dispersion of 40–90pp per year, and a haven that is
genuinely a different factor and whose haven-ness *fails* in 2022 while working
in 2020. Critically, `buy_and_hold` holds all 12 including the havens, so a
candidate cannot win merely by having access to gold.

Windows named by dates, not by what happened in them, so boundaries cannot be
nudged. Disjoint — the current pack's three scenarios are nested (292 and 270
bars both fully contained in the 647-bar full cycle), so "mean over 3 scenarios"
is one path counted three times. One window is a **sealed holdout: run once,
last, record whatever it says.**

### The fitting-the-harness safeguard

Six rules. The first three bind before any result is seen; the last three are
falsifiable checks that run in CI.

1. **Mirror pairs.** For every mechanism the library rewards, it contains a
   scenario where that mechanism costs, differing by exactly one parameter.
   Weakening a mirror is a visible one-line diff, asserted by test.
2. **Parameter provenance.** No number without an external referent cited in the
   YAML header. Seeds assigned by rule, never searched — seed search is the
   cheapest and least visible way to fake a pass.
3. **Pre-registration with a versioned identity.** The set ships as one commit
   before any candidate runs against it. The gate journals the library's content
   hash. Editing a scenario after seeing a result forces a new library version,
   so the journal reads "candidate X, library v2, attempt 1 (v1: 3 attempts)".
4. **The bracket test.** Three canaries in `algos/canaries/`: `always_haven`
   must lose everywhere (or the haven is a free lunch); `random_topk` must land
   mid-pack (or there is no learnable signal); `oracle_topk`, a deliberate
   look-ahead selector never promotable, must win by a wide margin (or the
   scenario contains no signal at all). Admit a scenario only if
   `oracle >> candidates > random >= always_haven`. Candidate-agnostic by
   construction: it asks "can this test measure skill", never "did my favourite
   win".
5. **The degeneracy assertion** — the check that would have caught both prior
   gauntlets on day one. For every gauntlet scenario assert `top_k < n_symbols`,
   that membership varies across bars, and that two different selectors produce
   different membership on ≥20% of live bars. Today's real pack scores 0% and
   fails immediately. Print it as a per-scenario "selector active %" column in
   the gate report so degeneracy is visible in the output rather than discovered
   months later.
6. **Seed ensembles**, per the amendment above.

One thing to flag rather than fix: the gate's absolute −35% drawdown criterion
is **not scenario-invariant**, since crash depth is a free parameter of the
library. Set crash depths from referents under Rule 2 and leave the gate
untouched. If everyone then fails on drawdown, that is the honest result. Making
that criterion relative must be a separate, pre-registered change.

---

## 5. Methodology corrections

### Where the methodology is sound — do not invent work here

An audit that finds only faults is not calibrated. These are genuinely right:
the one-bar decision discipline on targets, membership and allocator history
(B1 is a defect in the *sizing mark*, not in that discipline); prefix-stability
as a selector contract, and the composite-warmup fix; `walkforward.py`'s fold
warmup handling; comparing candidate and baseline on the same path as variance
reduction; `family` as the journal's primitive; recording start/final balance
and the simulated window alongside every score; the declared non-goals; and the
intellectual honesty of publishing FAILs, refusing to tune the gate, and
self-diagnosing the single-symbol degeneracy. That last diagnosis was correct as
far as it went — it stopped one step short of noticing the same defect on the
real pack.

### Legitimate: the gate measures the wrong construct

These are construct and units fixes, argued independently of any candidate's
outcome. Several make passing **harder**; that is the test of good faith.

- **M1 — Freeze and retract.** Mark the arc-status tables as produced by an
  engine with a confirmed look-ahead. Do not cite them until regenerated.
- **M2 — Give the gate `walk_forward`'s warmup discipline.** Note the structural
  bias this removes: `worst_fold` currently flatters long-warmup strategies for
  free, because a dead fold returns ≈0 and 0 beats any negative fold under
  `min()`.
- **M3 — The aggregator is wrong, not the bar.** Arithmetic mean of *total
  returns* over windows of 270/292/647 bars, some nested inside others, has no
  interpretation. Length-normalize and de-duplicate overlapping windows.
- **M4 — A point estimate is used where an interval is required.** With ~20pp of
  per-scenario sampling noise, "cand 29.93% vs base 28.04% → ok" is 0.1σ. Report
  the difference with an uncertainty estimate and require the candidate to clear
  noise.
- **M5 — The criteria mix incommensurable reference frames.** Three checks are
  relative to the baseline; drawdown is absolute (−35%) in scenarios where the
  baseline itself takes −48%. That combination is close to unsatisfiable for any
  long-only book. **Pre-register separately, ship alone, never alongside a
  library change or a candidate run.**
- **M6 — `worst_fold` at a hardcoded `k=4` is an undeclared researcher degree of
  freedom.** The verdict is reportedly not stable to it. `min()` over a
  partition is an order statistic of a tiny dependent sample — maximally
  boundary-sensitive — used as a binary criterion with no tolerance band. Report
  across k ∈ {3..8} and require the win to hold at a majority, or replace with a
  partition-free statistic.
- **M7 — The fold-scorer caveat names the wrong risk.** It says the scorers are
  valid "while contestants don't fit anything during a run". The premise is
  already false in the letter (`FollowTheLeader` selects in-run from trailing
  P&L), but the stated *mechanism* is also wrong: both are causal, so fold `k`'s
  return is uncontaminated. Adaptivity does not break fold causality any more
  than an SMA does. **What actually breaks it is the researcher** — all folds
  share human-chosen parameters selected with knowledge of these exact
  scenarios. Folds carved from one realized path are out-of-sample with respect
  to the *algorithm's* information set and fully in-sample with respect to the
  *analyst's*. Also record that `worst_fold` has a trivial optimum: an all-cash
  contestant scores exactly 0.0 and beats anything with a losing fold — fine
  inside the gate paired with a return check, degenerate as the arena/season
  ranking metric the README currently recommends.
- **M8 — Make the journal durable and meaningful.** Four problems. *Durability*:
  the DB is gitignored and the container is ephemeral, so nothing survives —
  commit the ledger or a CSV export. *Semantics*: `cmd_arena_gate` journals every
  contestant for every scenario, so one 5-scenario gate adds +5 to all 12
  families; that is why `buy_and_hold`, never iterated once, carries the same
  count as a candidate under development. *Coverage*: journaling is CLI-only, so
  the league, the season's per-tick re-runs, the web job runner and any REPL
  iteration are invisible — the record's claim that a parameter choice was "one
  theory-driven iteration" is plausible on its reasoning but architecturally
  uncorroborable, because a grid search leaves an identical footprint.
  *Reporting*: `journal_summary` picks each family's best score with
  `ORDER BY score DESC` **across metrics**, so a Sharpe of 2.1 outranks a
  `worst_fold` of 0.03 — a max over incomparable scales, conditioned on the
  maximum.
- **M9 — Stamp provenance on every recorded number:** engine version, seed set,
  fold count, cost assumptions, library version. Half the trouble above is that
  the headline numbers have no attached provenance.
- **M10 — Align the research cost model with production.** `slippage_bps: 1.0`
  and zero commission make high turnover essentially free. More sharply:
  `data/synthetic.py` sets `open(t) == close(t-1)` **exactly**, so the
  decide-at-close/fill-at-open discipline costs a synthetic strategy nothing,
  while on real SPY bars ~33% of daily close-to-close variance occurs in that
  gap — the synthetic gauntlet is structurally blind to signal-to-fill decay.
  Whole-share sizing at $10k is a 4–5% quantization per position, which also
  makes the 1% no-trade band inert for $450 ETFs. No `adjustment=` is passed
  when fetching, so cached bars are **raw, not dividend-adjusted** — this makes
  the baseline harder to beat, so it does not rescue the candidates, but it must
  be labelled. And `daily_loss_tripped` is referenced only in `engine.py` —
  never in either simulation loop, so the circuit breaker that would halt a
  paper account is switched off in every number used to decide promotion.
- **M11 — Survivorship framing is right; the live biases are different ones.**
  The ETF choice genuinely sidesteps membership bias. What is unlabelled:
  **window selection** (the 2021-12 → 2024-06 span was chosen after the fact for
  its narrative shape, then three nested scenarios carved from it), and the
  degeneracy of the selector on the real pack.

### Forbidden — refuse if proposed later

Lowering the drawdown limit; dropping the return check; changing strict majority
to plurality; sweeping `storm_vol`/`vol_window`/`target_vol`/`lookback` until
something clears; trimming a meta roster to fit a time budget; searching seeds;
editing a scenario after a result without a version bump.

**The distinguishing test between M1–M11 and this list:** a legitimate change is
specifiable without knowing which candidate is in flight, and its effect on the
current candidate's verdict is not known in advance. M4 and M6 both plausibly
make the current candidates fail *harder*; that is what makes them admissible.

---

## 6. Sequenced plan

Every stage preserves, and its Definition of Done re-checks: the paper-by-default
gate, no look-ahead, risk centralised, backtest == live == arena lockstep,
import isolation, offline-first, and docs updated in the same change.

Paper credentials are available and egress is open. Only **Stage 5** needs them,
for one pull. Everything else is pure-offline — the existing cache replays with
no credentials in the environment.

**Stage 0 — Doc truth pass and record freeze.** Pure offline, no code. Half a
day. Apply §1's corrections. Mark the arc-status blocks retracted pending
re-derivation. State plainly that the ledger is ephemeral and its counts are
unauditable. Add the B13 and B14 gotchas. Do this **first and separately**, so
no later commit mixes "the instrument was biased" with "here is a new result" —
mixing them is how a record becomes unauditable.
*DoD:* no CLAUDE.md claim is falsifiable by a command in the repo; every
retracted number is labelled at its point of use; the CI claim is either built
or deleted; the `trading-bot/` prefix is gone.

**Stage 1 — Instrument fix and the guard class. DONE 2026-07-25.** B1, B8, B9
shipped. The falsification checkpoint ran first and the arc survived it:
candidate mean return 13.52% → 10.67%, baseline 17.75% → **11.71%**, worst-fold
3/3 → 2/3, and `real_full_cycle` flipped from candidate-loses to
candidate-wins. Criteria changed state, so the bias was material. The mark
choice (fill-bar open) is pre-registered in CLAUDE.md. Both new guards were
verified to fail when their shift is deleted from *both* loops while the
lockstep suite stays green. **Also confirmed here:** the `exit_rank` freeze —
`xs_momentum` makes zero membership changes across all 587 live bars of the
real pack, so that gauntlet contains no cross-sectional evidence at all. Split the reporting mark from the sizing mark in both loops in one commit.
Move target computation after alignment. Add the absolute single-engine guards.
**Falsification checkpoint first:** run the fill-bar-open and prev-close variants
side by side; if no criterion changes state, stop and re-scope.
*DoD:* the lockstep test is green; every shift has one non-relative guard that
fails when the shift is deleted from **both** loops — verify by actually
deleting it; the mark choice is recorded as a pre-registered decision.

**Stage 2 — Live-path convergence. DONE 2026-07-25.** B6 + B10 + B3 + B2 + B7
all shipped, each with a test that fails without the fix. The offline backstop
(B7) is worth a note: the first version used `str.startswith(("", ...))`, which
is True for every string and silently disabled the whole guard — it now matches
loopback hosts exactly, and was verified to actually fire against a real
outbound connect. B6 and B10 land together — B6 makes B10 load-bearing. B7 lands here
because Stage 5 introduces credentials and this is the last quiet moment to
install the socket backstop.
*DoD:* a test asserts `latest_targets(<what the engine actually fetches>)`
equals `membership(full).iloc[-1]` on **ragged** bars; a season test drives the
feed through a fake fetcher and asserts bars actually accumulate.

**Stage 3 — Re-derivation and methodology instrumentation. PARTLY DONE
2026-07-25.** Shipped: the `exit_rank` small-pool fix, M6 (fold-count
sensitivity printed across k=3..8 beside the worst-fold check), M8's semantics
half (the gate journals only the candidate's family, not the whole field), and
the full re-derivation of all four recorded gate verdicts. **Result:
`xs_momentum_vt` PASSES the real-data gate** and the recorded attributions were
exactly inverted — see the re-derived record in CLAUDE.md.
M3 and M9 have since landed too. **M3 reversed the PASS**: judged on mean CAGR
instead of mean total return, `xs_momentum_vt` fails the real gate 8.79% vs
9.18%. Averaging total returns over 292-, 270- and 647-bar windows has no
interpretation, and the baseline's 2023 rally sits in the shortest one, so
normalizing for time rewards it. The gate now also prints `WINDOWS OVERLAP`
when scenarios are carved from one pulled price path — but only for provider
data, since synthetic scenarios share an epoch by construction while being
independent draws. M9 stamps `ENGINE_VERSION` on every journal row so pre- and
post-fix numbers can never be compared silently.

**Stage 3 COMPLETE.** M2 landed as post-warmup rebasing inside the gate rather
than as wider data pulls: both contestants are now scored from the bar where
the *later* of the two starts trading, detected from the curve. M8's durability
half is `arena journal --export ledger.csv`, so the ledger can be committed and
the attempt counts actually checked.

**M2 flipped the real-pack verdict back to PASS** (10.98% vs 9.52% mean CAGR),
the fourth flip in the sequence. See the final-state table in CLAUDE.md: the
conclusion is that the real pack cannot support a binary decision at these
margins, and the balanced factor library — a decisive FAIL at 2.03% vs 11.17% —
is the gauntlet to judge on. Re-run all four
gate verdicts, the synthetic gauntlet, the walk-forwards and the balance ledger
on the fixed engine. Rewrite the arc-status block with corrected numbers and
**explicit retraction** of invalidated attributions — not a quiet amendment.
State which conclusions survive and which do not.
*DoD:* every number carries engine version, seed set, fold count and cost
assumptions; the journal counts evaluations of the family under development, not
the whole field.

**Stage 4 — Synthetic scenario library. PARTLY DONE 2026-07-25.** Shipped:
`synthetic_factor_panel` (one shared market factor, per-symbol beta/alpha/idio,
`beta_shift` for crisis contagion), the `source: factor` branch in `Scenario`,
the fixed 8-name pool, three scenarios including the `xs_crash_haven` /
`xs_crash_nohaven` mirror pair, and `tests/test_scenario_library.py` enforcing
Rules 1, 2 and 5 — mirror-pair single-parameter identity, parameter provenance
in the YAML headers, and the degeneracy assertion. The new scenarios run
92–94% selector-active against 0% for the single-symbol scenarios they replace.
All seven schedules now ship, and Rule 6 (`--seeds N`) with them. The balance
turned out to decide verdicts rather than merely soften them: over the first
three schedules (two of which were crashes) `xs_momentum_vt` **PASSED**; over
the balanced seven it **FAILs decisively** (mean CAGR 1.70% vs 9.73%,
worst-fold 3/7), winning both crash scenarios and losing all four non-crash
ones. An unbalanced gauntlet does not produce a weak verdict — it produces a
wrong one.

**Stage 4 COMPLETE.** Rules 1–6 all ship: mirror pairs asserted by test,
parameter provenance in every YAML header, library content-hash journaling, the
canary bracket in `algos/canaries/`, the degeneracy assertion (also printed by
the gate), and seed ensembles. Ship as **one
pre-registration commit before any candidate runs against it.** Canaries go in
`algos/canaries/`; `loader._expand` uses non-recursive `glob("*.py")`, so a
subdirectory does not disturb the field count of 12 baked into four test files —
confirm that.
*DoD:* `synthetic_ohlcv`/`synthetic_regime_ohlcv` byte-identical (assert, do not
assume); the degeneracy assertion, mirror-pair identity, haven-costs-to-hold and
canary bracket all enforced by test; `--seeds` defaults to 10 with median
aggregation and an `UNSTABLE` verdict.

**Stage 5 — Real scenario pack.** Needs paper credentials for one pull, then
offline forever. ~1 day plus compute. Land B4 before the pull. Use **explicit**
`--start`/`--end`. Write honesty headers covering IEX volume, raw un-adjusted
bars, the after-the-fact window selection, and the inception-date exclusions.
*DoD:* every scenario replays with no credentials in the environment — verify by
unsetting them; the degeneracy assertion passes on the real pack (it fails today
at 0 of 292); gauntlets run on ~500-bar slices per the meta time-budget gotcha.

**Stage 6 — Deferred backlog.** Not part of the arc; scheduled so it is not
forgotten. B5, B11, B12, B14's minors, the holiday table expiry, the stale module
docstrings, the README refresh, and CI if §1 item 2 was resolved by building.
**Explicitly out of scope for Stages 1–5** — the single largest risk to this plan
is the arc becoming "fix the audit".

## Open uncertainties

- The quantitative counterfactuals were not re-run first-hand. Stage 1's
  falsification checkpoint exists because the plan rests on them.
- ~~Whether the `exit_rank` freeze claim holds on the shipped real pack~~
  **CONFIRMED 2026-07-25, and worse than reported.** `MomentumSelector(60, 5,
  top_k=2)` over SPY/QQQ/IWM picks `{IWM, SPY}` on 2022-02-28 and never changes
  again — 0 membership changes in 587 live bars, not just on the 2-symbol
  scenarios. The real gauntlet measures one single-day pick frozen for 2.5
  years. Fix in Stage 3.
- Alpaca's free IEX history depth for a 2016 start is unverified. If the
  provider will not serve it, drop the earliest window rather than shortening
  the gate windows.
