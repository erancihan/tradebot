# Product: portfolio companion

## Problem
The owner wants one simple app, usable from a phone. It must tell them what to
buy, run their portfolio for them when they allow it, and show what a different
plan in the past would have produced. Today the bot can do all of this work,
but only from a terminal with YAML files and many subcommands. The dashboard
is read-only and shaped for a desktop screen.

## Success metric
From a phone browser, without a terminal, the owner can do three things in
under one minute each:
1. See today's suggested trades with a one-line reason for each trade.
2. Switch the paper account to autopilot and watch it trade.
3. Run a simulation such as "10,000 into X from 2022" and read the result.
The metric is measured by walking those three flows on a phone.

## Announcement
tradebot now works as a portfolio companion. Open it on your phone and the
Today page shows what the bot buys or sells right now, with the reason behind
each suggestion. Turn on Autopilot and it manages your paper account on its
own. You can also ask it to wait for your approval before each trade. The
What-if page replays history. Pick a few symbols, a strategy, a start date and
a monthly contribution, then compare that plan with buying and holding. The
bot stays in paper mode until you unlock live trading on purpose.

## Screens
- `mockups/today.html`. Today page: account strip, suggested trades (buy,
  sell or hold with reason and amount), refresh button, last updated time.
- `mockups/autopilot.html`. Autopilot page: status card (off, approve first,
  or automatic), start and stop controls, trades that wait for approval,
  recent fills.
- `mockups/whatif.html`. What-if page: presets, symbols, plan (strategy, or
  plain buy and hold, or monthly contributions), start and end dates, starting
  cash, monthly contribution, result card (final value, gain, worst drop,
  comparison with buy and hold) and an equity chart.
- The existing pages (Dashboard, Chart, Arena, Seasons, Consortium) stay. On
  small screens they sit under a "More" menu.

On a phone, the navigation is a bottom tab bar: Today, Autopilot, What-if,
More.
