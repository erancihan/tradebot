# ADR 0002: the portfolio companion and its three flows

Date: 2026-10-15. Status: accepted, shipped.

## Context
The owner wants one simple app, usable from a phone, that says what to buy,
runs the portfolio when allowed, and replays past plans. The bot already had
every underlying capability behind a terminal and YAML files.

## Decision
One new core concept, the proposal, feeds three flows.

- The advisor (`tradebot/advisor/`) computes a proposal: per symbol, the
  target, the share delta, the notional and a one-sentence reason. The engine
  builds its orders from the same function, so a suggestion and an execution
  cannot disagree.
- The autopilot (`tradebot/autopilot/`) runs the engine on a schedule with
  the modes off, approve first and automatic. It runs as a thread inside the
  web process and also headless through `tradebot run --autopilot`. Live
  trading stays behind the config file and the environment latch. The web
  layer cannot switch it on.
- What-if (`tradebot/whatif/`) replays a plan with monthly contributions
  against equal-weight buy and hold with the same cash flows. Money gain is
  the headline number because it answers the owner's question directly.
- The web layer is phone first: a bottom tab bar (Today, Autopilot,
  What-if, More), a PWA manifest, and token access for use over a network.
- Market calendars sit behind `MarketCalendar` (`tradebot/market/`) so Borsa
  Istanbul can be scheduled now and traded later, once a broker exists.
- Phone alerts go through ntfy with no new dependency.

## Decided not now
- Native mobile app: the PWA covers the phone.
- Bank or broker funding automation: no API on the free tier.
- A BIST broker adapter: needs a brokerage API decision first.
- Multi-user accounts: single owner, token access is enough.
- Container isolation for arena contestants: contestant code is human
  reviewed (see `docs/research-record.md`).

## Consequences
- The Today page and the engine share one code path. Change `propose`, not
  `rebalance`.
- Every result and proposal carries provenance (source, window, age).
- The offline, credential-free path still runs every page.
