<!-- Thanks for contributing! Keep PRs focused. Delete sections that don't apply. -->

## What & why

<!-- What does this change and why? Link any issue: "Closes #123". -->

## How

<!-- Brief notes on the approach, and anything a reviewer should look at first. -->

## Definition of done

<!-- From CLAUDE.md. Tick what applies; explain anything unchecked. -->

- [ ] Tests added/updated and `make test` is green (plus `npm run typecheck` if the frontend changed).
- [ ] The offline, credential-free path is preserved (no test needs network or API keys).
- [ ] Invariants respected: paper-by-default gate, no look-ahead, risk stays centralised in `RiskManager`, import isolation (lazy Alpaca/dotenv; core never imports `web/`).
- [ ] Docs updated where relevant (`CLAUDE.md`, `README.md`, `CHANGELOG.md`).

## Notes for reviewers

<!-- Screenshots for dashboard changes, backtest numbers for strategy changes, etc. -->
