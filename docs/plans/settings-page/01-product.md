# Product: settings page

## Problem
On a fresh machine the Today page says "run cp config.example.yaml
config.yaml". A phone has no terminal. Every setting that matters (which
symbols, which strategy, how much risk, where alerts go) must be editable
from the phone.

## Success metric
From a phone, with no terminal, the owner can go from an empty install to a
first proposal: pick symbols and a strategy, save, tap Refresh. One flow,
under two minutes.

## Announcement
tradebot now has a Settings page. Choose your symbols, strategy, risk limits,
autopilot cadence and alert topic from your phone and save. The Today page
tells you what is still missing (API keys, price history) and how to fix it.

## Screens
- Settings: sections Symbols, Strategy, Portfolio, Risk, Autopilot, Alerts,
  Market. One Save button. Paper mode is shown, not editable. Keys are shown
  as present or missing, never as values.
- Today: a setup card at the top while something is missing.
