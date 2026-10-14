# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through GitHub's built-in flow:

1. Go to the [**Security** tab](https://github.com/erancihan/tradebot/security/advisories/new).
2. Click **Report a vulnerability** and describe the issue, including reproduction
   steps and impact.

You'll get an acknowledgement, and we'll coordinate a fix and disclosure timeline
with you. Please give a reasonable window to address the issue before any public
disclosure.

## Scope & threat model

This is a **paper-trading-first** project. A few things are worth calling out for
anyone assessing risk:

- **Credentials never live in the repo.** Alpaca keys are read from the
  environment / a git-ignored `.env`; only `.env.example` is tracked. Never commit
  real keys — if you do, rotate them immediately.
- **Live trading is gated.** Placing real orders requires *both* `mode: live` in
  config *and* the environment latch `TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND`. Reports
  showing this gate can be bypassed are especially welcome.
- **The arena runs third-party algorithm code.** It defends in depth — hard
  subprocess isolation with kill-on-timeout, CPU/memory rlimits, and an
  on-by-default sandbox (no disk writes + network-namespace isolation), plus an
  opt-in seccomp tier that denies `execve`/`ptrace`. Sandbox-escape reports are
  in scope. Note: contestant code is assumed to be human-reviewed before it runs,
  so OS-level containment (containers/gVisor) is intentionally out of scope for now.
- **The web dashboard is read-only.** It opens SQLite in read-only mode and cannot
  place orders; browser-run backtests/dry-runs execute against synthetic data in
  paper mode only.

## Supported versions

The project is pre-1.0; only the latest `master` receives security fixes.
