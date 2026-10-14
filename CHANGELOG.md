# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
