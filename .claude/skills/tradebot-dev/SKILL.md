---
name: tradebot-dev
description: Use when starting work on the tradebot project (a paper-trading-first equities bot; the repo root is the project root). Covers orientation, env setup, tests, the frontend build, code-shape rules, git rules and the non-negotiable invariants. Start here before changing tradebot code.
---

# tradebot dev workflow

The repo root is the project root. Read `CLAUDE.md` first. It holds the
layout, invariants, code rules, gotchas and docs policy. Shipped decisions live in `docs/adr/`;
work in progress has a plan folder under `docs/plans/<slug>/`. This skill is
the quick operational loop.

## Set up and verify (offline, no credentials)
```bash
make install        # .venv + pip install -e ".[dev]"
make test           # pytest, green before and after your change
```
For dashboard work also run `make install-web` (adds the `[web]` extra and
runs `npm install`), or `make install-all` for every extra (`[dev,live,web]`)
plus `npm install`.

## Common loops
```bash
make demo           # offline backtest on synthetic data
make dryrun         # offline real-time forward-test (replay)
make arena          # example competition leaderboard
make web            # build frontend + serve the dashboard (needs [web])
```
CLI: `tradebot {backtest,run,status,demo,arena,data,universe}`, `tradebot-web`
(`--check` validates the config and exits); `--config` defaults to
`./config.yaml` when present for both. Service files for an always-on
server live in `deploy/` (`deploy/README.md`).

Frontend (`frontend/`): `npm run typecheck` (strict, CI gate), `npm test`
(Node behaviour tests in `frontend/tests/*.test.ts`, `fetch` stubbed), `npm run
build` (output to the gitignored `tradebot/web/static/`), `npm run watch:js`.

## Code rules
- Functions and methods: at most 60 lines.
- Modules under `tradebot/`: at most 200 lines, aim for 150. Split along
  section comments and keep package re-exports so imports stay unchanged.
- `tests/test_code_shape.py` enforces both limits. Run it after every split.
- Type hints, `from __future__ import annotations`, comments explain why.

## Git rules
- Work on `feat/<epic>`. Merge into master with `git merge --no-ff --no-gpg-sign`.
- Every commit carries `--no-gpg-sign`. Never edit git config.

## Before you commit
- `make test` green, `tests/test_code_shape.py` included. `cd frontend && npm
  run typecheck && npm test` green for frontend changes.
- An offline, credential-free path and offline tests remain.
- Invariants hold (see CLAUDE.md): paper-first gate, no look-ahead, risk
  centralised in `RiskManager`, import isolation (lazy Alpaca, the core never
  imports `web`), no inline JS in templates.
- No secrets, `*.db`, `data/cache/`, `node_modules/` or `tradebot/web/static/`
  in the commit.
- `CLAUDE.md`, `README.md` and these skills state the new final state. Answered
  questions and finished plans are deleted, not kept.

## Specialised tasks
- New strategy: use the `add-strategy` skill.
- Arena contestant or arena internals: use the `add-arena-algo` skill.

## Gotchas (full list in CLAUDE.md)
- Do not type web request dict fields as `dict[str, float]`. Pydantic turns
  integers into floats and breaks `rolling`/`iloc`. Use `dict | None`.
- Starlette needs `templates.TemplateResponse(request, name, context)`.
- Advance the arena or replay cursor once per loop step. Keep warmups as
  integers.
