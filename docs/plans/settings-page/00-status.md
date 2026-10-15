# Status: settings page (configure from the phone)

Gate approvals delegated by the owner (2026-10-14). Approved when written.

- Gate 1 Product: APPROVED 2026-10-15
- Gate 2 Architecture: APPROVED 2026-10-15
- Gate 3 Program Design: APPROVED 2026-10-15
- Gate 4 Slice plan: APPROVED 2026-10-15

## Slices
- [x] S1 tracer: `/settings` page renders the current settings read-only, under More
- [x] S2 save: `POST /api/settings` validates and writes `config.yaml`, server settings reload
- [ ] S3 strategy and portfolio pickers from the registries, params as typed fields
- [ ] S4 setup card on Today: config, credentials, cached bars, with the fix for each
- [ ] S5 autopilot and alerts sections (poll seconds, brief lead time, ntfy topic, market)
- [ ] S6 CLAUDE.md trimmed back under 300 lines (gotchas compressed, nothing dropped in substance)

## Notes for a fresh session
Branch `feat/settings`. Same rules as before: `--no-gpg-sign`, worktree,
Opus agent, merge `--no-ff` to master, delete this folder when shipped and
add the decisions to `docs/adr/0002-portfolio-companion.md`.
