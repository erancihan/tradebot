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
  one batch and one verb, valid for 2 x `poll_seconds` (at least 30 minutes).
- They are the only URL-borne credential in the app. That is acceptable because
  a link can only approve or reject lines already pending in its own batch,
  through `Autopilot.act_on_batch` (account-checked, under the lock; it calls the page's approve/reject), never changes the mode, and
  lives its TTL or until the batch is replaced, whichever comes first. Each link acts once (a replay is a 409) and a live
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

## Addendum 2026-10-15: quiet re-proposals
- In approve-first mode a pass whose trades are the same `(symbol, action)` set
  as the waiting batch (its pending and rejected lines) carries that batch over:
  the pending lines and holds take the new pass's sizing, prices and time, rejected
  lines stay rejected, and the batch id stays, so the push's links keep working.
  History and Today show a carried batch at its latest refresh time.
- A rejection, even Skip of every line, holds until the proposal changes or the
  trading day ends, never longer: the same trades are not asked about again that day.
- A changed proposal, an approval older than one `poll_seconds`, a failed pass, a
  pass the broker reports closed, a daily-loss halt and switching off expire the batch.
- Each process pushes a carried batch once before going quiet: without
  `TRADEBOT_WEB_TOKEN` a restart changes the link key, so the old push's buttons
  no longer work.
- A batch is pushed once when recorded, then again as a reminder every
  `links.ttl_seconds(poll)` = max(2 x `poll_seconds`, 30 minutes). The same
  number is the link lifetime, so a push's buttons work until the next push.
- An approval means what the phone showed: when a refresh grows a pending
  line's notional by more than 10% over the last push, the batch is pushed
  again at once, with the new sizes. Link lifetime is a trade-off the paper-only,
  single-use links accept; the ntfy topic itself is the credential.

## Addendum 2026-10-15: History benchmark
- History's performance card answers "is the bot beating just holding the list?": it
  compares equity with equal-weight buy and hold of the active list (the watchlist, else
  `settings.symbols`, the list the autopilot trades) from the first snapshot's equity.
- Each symbol gets an equal share at the last session close completed at or before the
  first snapshot (a snapshot taken mid-session buys at the previous close, so caching that
  day's close later cannot move the start; the next close when no earlier one is cached),
  so a bot's first day has a benchmark before that day's close is cached. The benchmark is
  marked at each later completed close through the last snapshot, ending at the last
  session every held name has (a one-name gap inside the window holds its last close). A
  name without a close at the start is left out and named; a name whose cache ends early is
  named with its last date ("QQQ bars stop at 2026-10-05").
- The alpha compares one window: equity at the snapshot that reflects the benchmark's last
  close (taken by then, or after it before the next open) against the benchmark there, and
  the card says "through <date>". Without a `mode`, `/api/equity` rows of several accounts
  get no benchmark ("pick one account to compare").
- The benchmark holds TODAY's active list from the start: a hindsight bias (a name added
  later counts from day one). The card's muted line says "today's list, held from the start".
- Bars come from the cache only, never fetched, so the comparison needs no credentials;
  without cached daily bars the card names the `tradebot data pull` command instead.
- `/api/equity` carries the daily points, the symbols, the window and the source
  (`cache`); the chart places each close at its nearest snapshot as a dashed line.

## Addendum 2026-10-15: fills
- An order is logged when the broker accepts it, at the price it was sized at.
  What the broker did with it (status, filled quantity, average fill price,
  fill time) is stored on the same row once the broker reports it
  (`Broker.order_status`; a broker that cannot report returns None).
- The bot asks about open orders of the last 7 days at three points only: the
  start of each autopilot pass, the Today refresh job (paper orders, with keys)
  and right after it submits. A page load never calls the broker for this. A
  failed lookup is one warning per order id per process and never breaks a pass
  or a suggestion. An answer that filled more than the row ordered is not stored
  (the id names another order); dry-run ids carry a per-broker random prefix, so
  a later process never claims an earlier one's order.
- History shows the fill and the slippage against the sizing price over the
  filled shares (positive = it cost money). Positions summed from the order log
  count the filled quantity whenever one above zero is known, whatever the status;
  a cancelled, expired or rejected order with nothing filled counts zero, and an
  order not yet reported (or working with nothing filled) counts in full. Alpaca's
  `replaced` maps to `canceled`; `done_for_day`, `stopped` and `suspended` stay `new`.

## Addendum 2026-10-15: the list is the mandate
- The autopilot manages exactly the active list (the watchlist, else the config
  `symbols`). A held, non-flat position whose symbol is not on the list gets a
  closing line after the list's lines: `sell` (or `buy` for a short) to zero,
  reason "not on your list: sell to flat". `advisor.propose` takes these as
  `unlisted` (`symbol -> (signed qty, last price or None)`) and stays pure.
- The engine reads them from `broker.positions()` minus the list, equities only
  (`Position.asset_class`, Alpaca's; a crypto or option position is never an
  off-list holding), and prices them with one short fetch through its own data
  source. The Today refresh reads them
  from the paper broker, or offline from the order log, priced at the last cached
  close. Without a price the line is skipped ("not on your list; no price to size
  it"), never guessed. Approve mode asks for the line like any other.
- Removing a held name from the watchlist asks first and says the autopilot sells
  it at its next pass; an unheld name gets the plain confirmation.
- The product's no-trade band is 1% of equity: `Settings` uses it when the YAML
  does not set `risk.rebalance_band_pct` (an explicit 0 turns it off), and Settings
  edits it. `RiskConfig()` keeps 0, so backtests, the arena and the research
  record keep their numbers. A banded hold says "within the 1% no-trade band".
- Simulations are unchanged: their books never hold a name outside their list.
- Live never manages unlisted names, part of the live gate: live trades only the
  list and never sells what it did not buy (`engine/unlisted.manages_unlisted`).
  Elsewhere `manage_unlisted` (default true; Settings: "Sell names that leave the
  list") switches it off for the engine and Today alike.
- Every process trades the same list: `storage/watchlist.resolve_active` is the
  one resolver. `tradebot run` (all its forms) uses the trading db's watchlist
  when it has one, in place of the config symbols and any universe screen, and
  says so on its startup line (`symbols=watchlist(3)` or `symbols=config(2)`).
- Only equity tickers (`models.SYMBOL_RE`) are managed: a crypto pair or option
  in the account is ignored and logged once. A failed batched price fetch falls
  back to one fetch per name, so one unpriceable name never unprices the rest.
  With keys, Today pulls the same short window before reading the last close.
- Config symbols are upper-cased on load; off-list matching is upper-cased.
- Exits and reductions submit before entries (`orders.exits_first`, automatic and
  approved alike), so a swap's sell funds its buy; the proposal keeps its order.
- The band is the product's, not the research's: a `tradebot backtest` of a
  Settings file uses its 1% band, while the arena, what-if and the research
  record keep `RiskConfig()`'s 0.
