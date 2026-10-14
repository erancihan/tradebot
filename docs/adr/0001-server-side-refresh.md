# ADR 0001: the web server computes suggestions and can fetch bars

Date: 2026-10-14. Status: accepted.

## Context
Until now the dashboard never fetched market data. Every result came from the
local bar cache or from synthetic data, and the operator pulled bars from a
terminal. The owner now wants to use the app from a phone and get fresh
suggestions with one tap. A phone has no terminal.

## Decision
The web server computes proposals on request. When Alpaca credentials exist
in the server environment, the refresh job fetches missing bars through
`BarCache`, so every fetch is cached and later runs replay offline. Without
credentials the job uses cached bars only and the page says so. The browser
never receives credentials, and the web layer still places no order outside
the autopilot flow. Tests stay offline: the refresh job is tested with a fake
fetcher.

## Consequences
- Every result still carries provenance (source, window, bar count, age).
- The invariant "offline-first" holds: the credential-free path works.
- The invariant "the dashboard never fetches" is retired.
