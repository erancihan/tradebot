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

## Addendum 2026-10-15: settings from the phone
- `/settings` edits the YAML keys symbols, timeframe, poll_seconds,
  initial_cash, strategy, portfolio, risk, notify, market and autopilot.
  The save writes `config.yaml` atomically without comments; the example
  file keeps the documentation.
- `mode` is never editable from the web. Secrets stay in `.env`; the page
  shows presence only. Alert destinations are masked in the view, a blank
  value keeps the stored one, and a stored secret is never carried over to
  a changed server or host.
- A save stops a running autopilot loop and drops the cached runner. The
  next mode tap rebuilds it from the new file.
- A setup card on Today lists what is missing (config, keys, bars) with the
  fix for each.

## Addendum 2026-10-15: compare strategies on a what-if plan
- A comparison changes only the decision rule: every strategy runs on its
  default params with the plan's symbols, cash flows, allocator and selector.
  Tuned params stay a single-run affair; the window and benchmark run once.
- Meta strategies are skipped (they need a configured roster). The phone gets
  every row but only the top five curves plus the benchmark.

## Addendum 2026-10-15: approve from the phone notification
- With `notify.public_url` set, a pending batch's ntfy push carries Approve all,
  Skip and Open. Approve and Skip POST signed links: capability tokens scoped to
  one batch and one verb, valid for 2 x `poll_seconds` (at least 10 minutes).
- They are the only URL-borne credential in the app. That is acceptable because
  a link can only approve or reject lines already pending in its own batch,
  through `Autopilot.act_on_batch` (account-checked, under the lock; it calls the page's approve/reject), never changes the mode, and
  dies with the batch. Each link acts once (a replay is a 409) and a live
  account never gets an Approve link. The links ride through the ntfy topic,
  so the topic grants approval: the README asks for a self-hosted or
  access-controlled ntfy. The secret derives from `TRADEBOT_WEB_TOKEN`, else is
  random per process.
- Links are paper-only and account-bound.

## Addendum 2026-10-15: Discover, "what else could I buy?"
- Discover is a suggestion of names, never a trade: it ranks unwatched, unheld
  names by 6-1 momentum over the Alpaca most-active pool (with keys) or the cache.
- The watchlist stays the owner's decision: a name reaches suggestions or the
  autopilot only after the owner taps Add, which stops a running autopilot.
