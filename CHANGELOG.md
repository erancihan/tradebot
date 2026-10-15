# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (2026-10-15): the phone-first portfolio companion
- Today page and advisor: `advisor.propose`, extracted from
  `Engine.rebalance`, computes each symbol's target, share delta, notional and
  a one-sentence reason. The server refreshes a proposal cache first and
  fetches missing bars only with server-side keys. Offline, the account comes
  from the SQLite log.
- What-if page: replays a plan with monthly contributions against equal-weight
  buy and hold with the same cash. Any strategy and the portfolio stack are
  allowed. Presets come from the cache, the date pickers are bounded by cache
  coverage, and an uncached range shows the `tradebot data pull` command.
- Autopilot: off, approve first and automatic modes, with a durable mode.
  Approve-first trades park as pending lines that expire with the next pass.
  The loop runs as a thread in the web process and switches itself off on a
  daily-loss halt. `tradebot run --autopilot --mode off|approve|auto` runs it
  headless.
- Web hardening: a Host allowlist (`--allow-host`, `TRADEBOT_ALLOWED_HOSTS`),
  a required `X-Requested-With` header on state-changing requests, an
  optional access token with a posted `/login` form and an HMAC cookie, and a
  bounded login body.
- Mobile shell: a bottom tab bar (Today, Autopilot, What-if, More) and an
  installable PWA manifest.
- Market calendars behind a `MarketCalendar` protocol: `us_equities` and
  `bist`. The autopilot and the season daemon schedule against the configured
  `market:`.
- Morning brief: `autopilot.brief_minutes_before_open` sends the day's
  proposal before each open, in any mode.
- ntfy phone alerts (`notify.ntfy_topic`, `notify.ntfy_server`) and a one-tap
  **Send test alert** on the Autopilot page.
- Watchlist on the Today page. While it has symbols, the refresh and the
  autopilot scan it instead of the config's `symbols`.
- Holdings card on the Today page, from the paper account or the order log.
- Settings page: edits `config.yaml` from the phone with registry dropdowns
  and typed parameters for strategy, selector and allocator, plus risk,
  autopilot, alerts and market. A save validates, writes atomically, reloads
  and stops a running autopilot. It never shows a broker key or changes
  `mode`. A **Finish setting up** card on Today lists what is missing.
- `docs/adr/0002-portfolio-companion.md` records the companion decisions.

### Changed (2026-10-15)
- README restructured around the phone-first companion, with the terminal
  reference and research tooling after it.
- Housekeeping: large modules split into packages by concern (arena season,
  pass gate, journal, consortium, selection, store, universe, cache coverage)
  under the code-shape limits.

### Fixed (2026-10-15, review round)
- Alert failures log only the error class and code, and alert destinations
  are masked in failure logs.
- What-if symbols are validated before they reach the bar cache.
- `Autopilot.start` checks and starts atomically.
- A watchlist edit stops a running autopilot, so it never trades a removed
  symbol.
- The daily-loss anchor is persisted, so a rebuild cannot reset the breaker.
- An approved line is marked submitted before any bookkeeping, and SQLite
  opens in WAL mode.
- A 0-minute morning brief reads as off, and a bad config never returns a 500.
- The Settings page can remove an alert destination.
- A dry-run checks bracket levels only on bars after the entry bar.
- Broker credentials are scrubbed from the forked arena child.

### Merged
- `claude/stock-agent-overview-mzmfsr`: the algorithms-research arc, the
  consortium, the live-execution backlog (brackets, streaming, notifications)
  and the dashboard data-source and provenance work.
- `claude/repo-metadata-config-6is0sh`: the new strategies, indicators and
  public-repository scaffolding listed below.

### Added
- Two new strategies: `momentum` (time-series momentum with an optional trend
  filter) and `supertrend` (ATR-based adaptive trend follower). Both emit only
  `{-1, 0, +1}` targets. (MACD, Bollinger and Donchian already ship as
  `macd_trend`, `bollinger_reversion` and `donchian_breakout`.)
- New pure indicators to support them: `true_range`, `atr`, `donchian`, and `roc`.
- MIT `LICENSE` file and a License section in the README.
- Public-repository scaffolding: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, issue/PR templates, `CODEOWNERS`, Dependabot config, and a
  least-privilege `permissions:` block on the CI workflow.
- `.gitignore` hygiene entries for coverage output and OS/editor cruft.
- Code-shape rules: functions at most 60 lines, `tradebot/` modules at most 200
  lines, enforced by `tests/test_code_shape.py`.
- `docs/research-record.md`: the condensed paper trail of the research work.
- The portfolio-companion plan under `docs/plans/portfolio-companion/` and
  `docs/adr/0001-server-side-refresh.md`.

### Changed
- Docs consolidated to final state: `CLAUDE.md` is a short map of layout,
  invariants, code rules and gotchas. `docs/PLAN.md` and
  `docs/DESIGN-HANDOFF.md` are removed. Their live facts moved to `CLAUDE.md`
  and their results to `docs/research-record.md`.
- The `demo` CLI now derives its `--strategy` choices from the strategy registry,
  so newly added strategies are reachable without editing the CLI.

### Fixed
- The arena sandbox on macOS: `prctl` and `unshare` do not exist there, so the
  forked contestant crashed and every hardened tournament timed out. A missing
  syscall now lands in the capability report as "not enforced" and the run
  continues with one warning per mechanism.
- The live/dry-run engine and the `RiskManager` now reject non-finite or
  non-positive prices (NaN/inf/≤0) instead of raising on `math.floor(NaN)` —
  matching the backtester/arena, which already skip such bars.

## [0.1.0] - 2026-07-01

### Added
- Initial import: paper-trading-first equities bot on Alpaca.
- Trading core — strategies (SMA crossover, RSI reversion), centralised
  `RiskManager`, backtester with `t → t+1` execution, portfolio accounting,
  broker/data adapters, and the `tradebot` CLI.
- Dry-run — real-time loop with simulated fills against a virtual account.
- Arena — dynamic algorithm loading and ranked competitions, with hard
  subprocess isolation (kill-on-timeout, CPU/memory limits), an on-by-default
  sandbox (no disk writes + network isolation), an opt-in seccomp tier, a
  replayed **league**, and a durable, resumable real-time **season**.
- Web dashboard — FastAPI + TypeScript/Tailwind/Alpine/ECharts, with equity,
  orders, positions, leaderboards, a candlestick price chart, a live account
  header, and an SSE refresh stream.

[Unreleased]: https://github.com/erancihan/tradebot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/erancihan/tradebot/releases/tag/v0.1.0
