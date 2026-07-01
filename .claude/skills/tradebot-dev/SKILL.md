---
name: tradebot-dev
description: Use when starting work on the tradebot project (the trading bot under trading-bot/) — orientation, how to set up the env, run tests, build the frontend, and the non-negotiable invariants. Start here before changing trading-bot code.
---

# tradebot dev workflow

Project lives under `trading-bot/`. **Read `trading-bot/CLAUDE.md` first** — it is
the source of truth for architecture, invariants, gotchas, and roadmap. This
skill is the quick operational loop.

## Set up & verify (all offline, no credentials)
```bash
cd trading-bot
make install        # .venv + pip install -e ".[dev]"
make test           # pytest — must be green before and after your change
```
For dashboard work also: `make install-web` (adds `[web]` extra + `npm install`).

## Common loops
```bash
make demo           # offline backtest on synthetic data
make dryrun         # offline real-time forward-test (replay)
make arena          # example competition leaderboard
make web            # build frontend + serve dashboard (needs [web])
```
CLI surface: `tradebot {backtest,run,status,demo,arena,data}`, `tradebot-web`.

Frontend (`trading-bot/frontend/`): `npm run typecheck` (strict, CI gate),
`npm run build` (→ gitignored `tradebot/web/static/`), `npm run watch:js`.

## Before you commit — checklist
- `make test` green; `npm run typecheck` green if you touched the frontend.
- Kept an **offline, credential-free** path + offline tests.
- Respected invariants (see CLAUDE.md): **paper-first gate**, **no look-ahead**,
  **risk centralised in RiskManager**, **import isolation** (lazy Alpaca; web not
  imported by core), **no inline JS** in templates.
- Did **not** commit secrets, `*.db`, `data/cache/`, `node_modules/`, or
  `tradebot/web/static/` (all gitignored).
- **Updated `CLAUDE.md`** (status/roadmap/gotchas) and `README.md` if user-facing.

## Specialised tasks
- New strategy → use the `add-strategy` skill.
- Arena contestant or arena internals → use the `add-arena-algo` skill.

## Gotchas (full list in CLAUDE.md)
- Don't type web request dict fields as `dict[str, float]` (coerces ints → floats,
  breaks window/iloc). Use `dict | None`.
- Starlette needs `templates.TemplateResponse(request, name, context)`.
- Advance the arena/replay cursor once per loop step; keep warmup integers.
