# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Five new strategies: `macd` (momentum), `bollinger_reversion` (volatility
  mean-reversion), `donchian_breakout` (turtle-style breakout), `momentum`
  (time-series momentum with an optional trend filter), and `supertrend`
  (ATR-based adaptive trend follower). All emit only `{-1, 0, +1}` targets.
- New pure indicators to support them: `macd`, `bollinger`, `true_range`, `atr`,
  `donchian`, and `roc`.
- MIT `LICENSE` file and a License section in the README.
- Public-repository scaffolding: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, issue/PR templates, `CODEOWNERS`, Dependabot config, and a
  GitHub Actions CI workflow (pytest on Python 3.10–3.12 + frontend typecheck/build).
- `.gitignore` hygiene entries for coverage output and OS/editor cruft.

### Changed
- The `demo` CLI now derives its `--strategy` choices from the strategy registry,
  so newly added strategies are reachable without editing the CLI.

### Fixed
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
