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
- [x] S2.1 tracer: `/whatif` page posts a hardcoded request and shows a stub result card
- [x] S2.2 `whatif.run()`: multi-symbol buy and hold with monthly contributions, compared with a lump sum
- [x] S2.3 strategy and portfolio stack plans (selector, allocator) in the same form
- [x] S2.4 benchmark comparison, drawdown and "vs buy and hold" in the result card, chart with both curves
- [x] S2.5 presets, cache-aware date bounds, pull hint when the range is not cached

## E3: Suggestions
- [x] S3.1 tracer: `/today` shows a stored dummy proposal
- [x] S3.2 `advisor.propose()` extracted from `Engine.rebalance`, with a lockstep test engine == advisor
- [x] S3.3 reasons: strategy signal, selector rank, allocator weight and risk cap in one sentence per row
- [x] S3.4 refresh job (server-side, cache first, network only with credentials), provenance and age
- [x] S3.5 account state from SQLite when no broker credentials exist

## E3b: Web hardening (before autopilot exposes trade actions)
- [x] S3b.1 same-origin guard: every `POST /api/*` requires the `X-Requested-With: tradebot` header, sent by the TypeScript client, refused with 403 otherwise (cross-origin forms cannot set it)
- [x] S3b.2 `TrustedHostMiddleware` with an allowlist from `--allow-host` (default localhost), blocks DNS rebinding
- [x] S3b.3 optional access token (`TRADEBOT_WEB_TOKEN`): when set, every request needs the cookie set by the `/login` form (or a Bearer header); documented as the way to reach the app from a phone over the network

## E4: Autopilot
- [x] S4.1 tracer: `/autopilot` page shows state from `autopilot_state`, the toggle writes the mode
- [x] S4.2 `Autopilot` runner thread: passes on `poll_seconds` inside market hours, injected clock, offline test
- [x] S4.3 `approve` mode: pending proposals, approve and reject, submit only approved rows
- [x] S4.4 `auto` mode, notifications on fills and halts, stop on a daily-loss halt
- [x] S4.5 `tradebot run --autopilot` headless parity

## E5: Expansion
- [x] S5.0 polish from the phone smoke test: equity chart axis shows dates only on daily bars, What-if presets use real cached symbols when a cache exists (verified synthetic fallback works)
- [x] S5.1 ntfy phone alerts documented, one-tap test button on the Autopilot page
- [x] S5.2 watchlist (symbols the advisor scans) editable from the Today page; holdings card on Today (`/api/holdings`, broker positions with credentials, else the order log at the last cached close; uncached symbols are named, not priced)
- [ ] S5.3 `MarketCalendar` protocol with `us_equities`, used by the season daemon and the autopilot, BIST stub with a holidays table
- [ ] S5.4 further ideas evaluated, then built or recorded as an ADR "not now"
