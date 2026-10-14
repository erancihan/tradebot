# Contributing to tradebot

Thanks for your interest! This project is a **paper-trading-first** equities bot
with a strong bias toward being safe, offline-testable, and easy to reason about.
Please read this once before your first PR — and skim [`CLAUDE.md`](CLAUDE.md),
which is the deep architecture/onboarding doc.

By participating you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules (the invariants)

These are non-negotiable. A PR that breaks one won't be merged until it's fixed:

- **Paper by default.** Live trading requires *both* `mode: live` **and** the
  environment latch `TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND`. Never weaken or default
  around this gate.
- **No look-ahead.** A signal at bar `t` may only use data from `t` and earlier.
  The backtester fills on `t+1`; the arena feeds a growing window so the future is
  physically invisible. Don't peek.
- **Risk stays centralised.** Strategies emit only target regimes in `{-1, 0, +1}`
  (short / flat / long). All position sizing and limits live in `RiskManager`.
- **Backtest == live.** The backtester, live engine, and arena simulation share the
  same `Strategy` + `RiskManager`. Keep `tests/test_arena_simulation.py` green.
- **Offline-first.** Everything except the literal Alpaca network call must run and
  test with no credentials and no network. New features keep a credential-free path
  and offline tests.
- **Import isolation.** The Alpaca SDK and `python-dotenv` are imported *lazily*.
  The trading core must not import anything from `tradebot/web/`.
- **No inline JS.** All browser behaviour is imported, type-checked TypeScript
  bundled by esbuild. Templates only present data.

## Dev setup

```bash
git clone https://github.com/erancihan/tradebot
cd tradebot
make install         # venv + core + dev deps (enough for tests & offline demos)
make install-web     # add the [web] extra + npm install (for the dashboard)
make test            # pytest — fully offline
```

Handy targets: `make demo` (offline backtest), `make dryrun` (replay forward-test),
`make arena` (example competition), `make web` (build frontend + serve dashboard).

Frontend work happens in `frontend/`:

```bash
cd frontend
npm ci
npm run typecheck    # strict tsc --noEmit (CI gate)
npm run build        # -> tradebot/web/static/ (gitignored, reproducible)
```

## Making a change

1. **Branch** off `master`.
2. **Keep it focused** — one logical change per PR.
3. **Add tests.** They must be offline and deterministic (seeded synthetic data via
   `tradebot.data.synthetic.synthetic_ohlcv`, or fake fetchers). Web/job tests use
   `pytest.importorskip("fastapi")`.
4. **Run the gates locally:** `make test` (and `npm run typecheck` if you touched
   the frontend). CI runs the same on Python 3.10–3.12 plus the frontend build.
5. **Update the docs** you touched — `CLAUDE.md`, `README.md`, and
   [`CHANGELOG.md`](CHANGELOG.md) are part of the definition of done.
6. **Open a PR** and fill in the template.

### Adding a strategy or arena algorithm

There are project Claude Code skills with step-by-step recipes in
[`.claude/skills/`](.claude/skills/): `add-strategy` and `add-arena-algo`. A
strategy is a pure function of price data returning a `{-1, 0, +1}` Series — see
`tradebot/strategies/sma_crossover.py` for the simplest example, register it in
`tradebot/strategies/registry.py`, and add a test to `tests/test_strategies.py`.

## Style

- Match the surrounding style; type hints throughout; `from __future__ import
  annotations` at the top of modules.
- Comments explain *why*, not *what*.
- Core logic (indicators/strategies/risk/backtest/arena) depends only on
  pandas + numpy; adapters isolate Alpaca/FastAPI.
- Don't commit secrets, `*.db`, `data/cache/`, `node_modules/`, or built assets
  under `tradebot/web/static/` — all are gitignored.

## Reporting bugs & vulnerabilities

Use the issue templates for bugs and features. For security issues, follow
[`SECURITY.md`](SECURITY.md) — report privately, not as a public issue.
