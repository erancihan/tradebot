# Slices: portfolio companion

Each slice ends green (`make test` and `npm run typecheck`). Each epic is
merged to master from its `feat/<epic>` branch with a no-ff merge commit.

## E0: merge work branches
- [x] S0.1 merge `claude/stock-agent-overview-mzmfsr` (done locally, 2fd3ded)
- [x] S0.2 merge `claude/repo-metadata-config-6is0sh` with conflicts resolved
- [x] S0.3 push master, CI green on GitHub (run 38643874486, 2026-10-15)

## E1: housekeeping
- [x] S1.1 `tests/test_code_shape.py`: fail on any function over 60 lines, report modules over 200 lines
- [x] S1.2 split `tradebot/cli.py` into `tradebot/cli/` (one module per command group)
- [x] S1.3 split any other module the shape test flags
- [x] S1.4 docs to final state: concise `CLAUDE.md`, research record moved to `docs/research-record.md`, `docs/PLAN.md` and `docs/DESIGN-HANDOFF.md` deleted, README describes the companion
- [x] S1.5 mobile-first shell: responsive `base.html`, bottom tab bar, touch-size controls, PWA manifest

## E2: What-if simulator
- [ ] S2.1 tracer: `/whatif` page posts a hardcoded request and shows a stub result card
- [ ] S2.2 `whatif.run()`: multi-symbol buy and hold with monthly contributions, compared with a lump sum
- [ ] S2.3 strategy and portfolio stack plans (selector, allocator) in the same form
- [ ] S2.4 benchmark comparison, drawdown and "vs buy and hold" in the result card, chart with both curves
- [ ] S2.5 presets, cache-aware date bounds, pull hint when the range is not cached

## E3: Suggestions
- [ ] S3.1 tracer: `/today` shows a stored dummy proposal
- [ ] S3.2 `advisor.propose()` extracted from `Engine.rebalance`, with a lockstep test engine == advisor
- [ ] S3.3 reasons: strategy signal, selector rank, allocator weight and risk cap in one sentence per row
- [ ] S3.4 refresh job (server-side, cache first, network only with credentials), provenance and age
- [ ] S3.5 account state from SQLite when no broker credentials exist

## E4: Autopilot
- [ ] S4.1 tracer: `/autopilot` page shows state from `autopilot_state`, the toggle writes the mode
- [ ] S4.2 `Autopilot` runner thread: passes on `poll_seconds` inside market hours, injected clock, offline test
- [ ] S4.3 `approve` mode: pending proposals, approve and reject, submit only approved rows
- [ ] S4.4 `auto` mode, notifications on fills and halts, stop on a daily-loss halt
- [ ] S4.5 `tradebot run --autopilot` headless parity

## E5: Expansion
- [ ] S5.1 ntfy phone alerts documented, one-tap test button on the Autopilot page
- [ ] S5.2 watchlist (symbols the advisor scans) editable from the Today page
- [ ] S5.3 `MarketCalendar` protocol with `us_equities`, used by the season daemon and the autopilot, BIST stub with a holidays table
- [ ] S5.4 further ideas evaluated, then built or recorded as an ADR "not now"
