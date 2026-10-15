# Status: portfolio companion (suggest · autopilot · what-if)

Owner delegated gate approval on 2026-10-14 ("pick the most reasonable and
capable action; do not keep asking"). Gates are therefore approved by the
overseeing agent once the doc is written, and the owner comments if something
must change.

- Gate 1 — Product: APPROVED 2026-10-14
- Gate 2 — Architecture: APPROVED 2026-10-14
- Gate 3 — Program Design: in progress (written per epic, before that epic's slices)
- Gate 4 — Slice plan: in progress (see 04-slices.md)

## Epics (build order)
- [x] E0 — merge the two work branches into master (no-ff merge commits)
- [x] E1 — housekeeping: docs to final state, CLI split, function-length gate, mobile-first shell + PWA
- [x] E2 — What-if simulator (historical theoretical cases, multi-symbol, DCA, benchmark)
- [x] E3 — Suggestions (what to buy / sell today, with reasons)
- [x] E4 — Autopilot (managed paper/live engine with approve or auto mode)
- [ ] E5 — Expansion (phone alerts via ntfy, watchlists, market/broker abstraction for BIST)

## Slices
See `04-slices.md` (checked off there).

## Notes for a fresh session
- Work on branches named `feat/<epic>`; merge into master with
  `git merge --no-ff --no-gpg-sign`. Every git commit carries `--no-gpg-sign`.
  Never run `git config`.
- Coding model: Opus (medium effort) via subagents; this file + the gate docs
  are the hand-off. Oversight stays with the main session.
- Code rules: functions <= 60 lines, modules ~150 lines (200 = split),
  type hints, `from __future__ import annotations`. Enforced by
  `tests/test_code_shape.py` once E1 lands.
- Docs policy: documents state the final expected state only. Plan folders are
  deleted when their epic ships; durable decisions go to `docs/adr/`.
