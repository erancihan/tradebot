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
  initial_cash, strategy, portfolio, risk, notify, market, autopilot and
  manage_unlisted. The save writes `config.yaml` atomically without comments;
  the example file keeps the documentation.
- `mode` is never editable from the web. Secrets stay in `.env`; the page
  shows presence only. Alert destinations are masked in the view. A masked or
  omitted value keeps the stored one only while it still points at the same
  host or ntfy server; an empty value deletes it.
- A save stops a running autopilot loop and drops the cached runner. The
  next mode tap rebuilds it from the new file.
- A setup card on Today lists what is missing (config, keys, bars) with the
  fix for each.

## Addendum 2026-10-15: compare strategies on a what-if plan
- A comparison changes only the decision rule: every strategy runs on its
  default params with the plan's symbols, cash flows, allocator and selector.
  A plan with tuned params also gets its own row, `<name> (your settings)`.
  The window and benchmark run once.
- Meta strategies are skipped (they need a configured roster). A strategy that
  raises is listed with its error and the rest still run, within 120 seconds.
  The phone gets every row but only the top five curves plus the benchmark.

## Addendum 2026-10-15: approve first, batches, pushes and signed links
- A pass whose trades are the same `(symbol, action)` set as the waiting batch
  (its pending and rejected lines) carries that batch over: the pending lines
  and holds take the new pass's sizing, prices and time, rejected lines stay
  rejected, and the batch id stays, so the push's links keep working. History
  and Today show a carried batch at its latest refresh time.
- A rejection, even Skip of every line, holds until the proposal changes or the
  trading day ends, never longer: the same trades are not asked about again
  that day.
- A changed proposal, an approval older than one `poll_seconds`, a failed pass,
  the first tick after the close (or a pass the broker reports closed), a
  daily-loss halt, switching off and the first automatic pass expire the batch.
  A late approval never executes, and nothing waits overnight for the open.
- A batch is pushed once, then again as a reminder every
  `links.ttl_seconds(poll)` = max(2 x `poll_seconds`, 30 minutes). An approval means what the phone showed: when a refresh grows a
  pending line's notional by more than 10% over the last push, the batch is
  pushed again at once, with the new sizes. A restart pushes the batch again
  only without `TRADEBOT_WEB_TOKEN`: then the link key is per-process and the
  old push's buttons stop working. With the token the key survives, so the
  stored push (batch, time, sizes) carries over; on the paper soak six restarts
  in an hour had sent six identical pushes of one batch.
- With `notify.public_url` set, the paper account's push carries Approve all,
  Skip and Open; every other push (dry-run, replay, live) carries only Open.
  Approve and Skip POST signed links: capability tokens scoped to one account,
  one batch and one verb, valid for `links.ttl_seconds(poll)`, the reminder
  interval, so a push's buttons work until the next push arrives.
- They are the only URL-borne credential in the app. That is acceptable because
  a link can only approve or reject lines still pending in its own batch,
  through `Autopilot.act_on_batch` (account-checked, under the lock; it calls
  the page's approve and reject), and never changes the mode. Each link acts
  once per process (a second tap is a 409; after a restart a used link acts
  again until it expires). The secret derives from `TRADEBOT_WEB_TOKEN`, else
  is random per process.
- The links ride through the ntfy topic, so the topic grants approval of the
  bot's own pending paper trades: the README asks for a self-hosted or
  access-controlled ntfy and a long random topic.

## Addendum 2026-10-15: Discover, "what else could I buy?"
- Discover is a suggestion of names, never a trade: it ranks unwatched, unheld
  names by 6-1 momentum over the Alpaca most-active pool (with keys) or the cache.
- The watchlist stays the owner's decision: a name reaches suggestions or the
  autopilot only after the owner taps Add, which stops a running autopilot.

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
  later counts from day one). The card's muted lines say so: "Equal-weight <symbols> since
  <date>" and "today's list +x% · account +y% · cached closes" (or "cached and recorded closes").
- Bars are never fetched, so the comparison needs no credentials. The closes come from the
  bar cache, extended by the daily bars the account's own passes recorded in the trading db:
  the cache fills only on a Today refresh or `tradebot data pull`, while the autopilot records
  bars every pass, so a cache-only yardstick fell a session behind the bot. Each symbol's
  newest recorded bar may still be forming and is never used; a recorded bar followed by a
  later one is a completed session. Where both hold a session the cached close wins (the
  cache never holds a forming bar). The source is `cache`, or `cache+recorded` when recorded
  bars are inside the window (the card says "cached and recorded closes"). Without daily bars
  from either the card names the `tradebot data pull` command instead.
- `/api/equity` carries the daily points, the symbols, the window and the source
  (`cache`, or `cache+recorded`); the chart places each close at its nearest snapshot as a
  dashed line. A dry run's recorded bars never count: a replay records the frame it was
  given, synthetic or not, under `dry_run`.

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
  off-list holding), and prices them with one batched short fetch through its own
  data source, falling back to one fetch per name, so one unpriceable name never
  unprices the rest. The Today refresh reads them from the paper broker (pulling
  the same short window into the cache first), or offline from the order log,
  priced at the last cached close. Without a price the line is skipped ("not on your list; no price to size
  it"), never guessed. Approve mode asks for the line like any other.
- Removing a held name from the watchlist asks first and says the autopilot sells
  it at its next pass; an unheld name gets the plain confirmation.
- The product's no-trade band is 1% of equity: `Settings` uses it when the YAML
  does not set `risk.rebalance_band_pct` (an explicit 0 turns it off), and Settings
  edits it. A banded hold says "within the 1% no-trade band". The band is the
  product's, not the research's: a `tradebot backtest` of a Settings file uses it,
  while the arena, what-if and the research record keep `RiskConfig()`'s 0.
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
  in the account is ignored and logged once.
- Config symbols are upper-cased on load; off-list matching is upper-cased.
- Exits and reductions submit before entries (`orders.exits_first`, automatic and
  approved alike), so a swap's sell funds its buy; the proposal keeps its order.

## Addendum 2026-10-15: Trades
- History answers "how did my trades do?" with a Trades card under the
  performance card, built from the order log's fills for the page's account
  (`?mode=` pins it, as for the rest of History).
- The fills are the orders with a known fill: `filled_qty > 0` and a fill
  price, whatever the status (a cancel after a partial fill counts the shares
  that filled, as positions do), oldest fill first. Commission is 0 (Alpaca).
  Hand trades in the same account are not in the log and never count. A bot
  sale of a hand-bought holding (the off-list mandate) is in the log: it is
  listed as an unmatched exit, not a trade (below).
- Accounting is average cost per symbol (`tradebot/portfolio_pnl.py`, pure): a
  trip opens on the first fill, scales in at the average price, and each
  reducing fill realises `(exit - avg) x shares` (sign flipped for a short). The
  trip closes when the position is flat; a fill through zero closes it and
  opens the next trip with the remainder at the fill price. A closed trip shows
  its shares, average entry and exit, P&L and P&L over cost, and its dates.
- Open positions show "open since <date> at avg <price>" and no P&L (the log
  has no prices); a partial exit's realised part is shown beside it but is not
  in the summary, which covers closed trips only: closed, wins, losses, win
  rate, realised, average win and loss, best, worst, and profit factor (gross
  wins over gross losses, None without a loss). A break-even trip is neither.
- Each order records why it was sent: `orders.intent` is `entry` when it opens
  or grows exposure (`models.opens_exposure`, a flip too) and `exit` for a
  reduction, an off-list close or a daily-loss flatten. `schema.migrate` adds
  the column on open; older rows stay NULL and book as before (a NULL sell can
  open a short: strategies can short). An `exit` fill never opens a position:
  with no open trip in that symbol, or beyond the open quantity, the rest is an
  unmatched exit (a hand-bought holding, or a buy older than the fill log),
  listed under "Sold without a recorded buy" and never in the summary.
- `GET /api/history/trades?mode=` returns `{summary, trades, open, unmatched,
  provenance}` with provenance `{mode, source: "order log fills", orders}`.

## Addendum 2026-10-18: approval safety
- An approval buys only what the approver saw. Each push keeps its sizes under
  its links' `exp` (`announced_pushes`); a tap holds every line to the push it
  came from, and the page sends `seen` (line id to notional). A line grown past
  `GROWTH_TOLERANCE` (10%) of that stays pending: the growth re-push and the
  refreshed page show the new size and ask again. Why: a still-valid button of
  an older push bought a size a refresh had grown 1.5x. A request without
  `seen` (an older client) is not checked, for compatibility.
- Before an approved line is sent its position is read again; a line whose
  holding changed since the pass (a hand trade, a stop that fired) is expired,
  never sent. Why: a stored "sell N" against a position already gone opened an
  N-share short on a margin paper account, and a stored buy could double.
- A line the broker accepted is never sent again, even when marking it
  `submitted` fails (the engine keeps the sent ids in memory and retries the
  mark). Why: a locked database left the line pending and a second tap
  ordered it twice.
- No approval while the market is closed: it expires the batch. Why: a DAY
  market order sent after the close queues for the next open at prices nobody
  saw.
- A failed submit is never silent: it sets `last_error` naming the symbols,
  pushes `order_failed`, and the page names it; a signed link whose lines
  failed answers 502 and is given back so the same button retries.
- A Skip lasts only while the proposal is unchanged: the runner records the
  batch it parked last, and an all-holds pass in between makes the same trades
  a new question. A repeated all-holds pass refreshes its batch instead of
  adding one per poll.
- One loop per account. A Settings or watchlist save hands a pass still in
  flight to the next build, which waits for it before starting a new loop; a
  stopped runner starts no pass and parks nothing. Run either `tradebot run
  --autopilot` or the web autopilot on an account, never both: they would
  each trade it.
- The headless CLI arms Approve and Skip only with `TRADEBOT_WEB_TOKEN`:
  without it its key is per-process and no web server could verify the links.
- A reminder comes at the earlier of the interval and the push's own link
  expiry (`announced_exp`), so a raised poll cannot leave dead buttons on the
  phone.
