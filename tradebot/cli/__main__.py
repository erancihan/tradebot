"""`python -m tradebot.cli ...` — the Makefile and README invoke the CLI this way."""

from __future__ import annotations

from . import main

if __name__ == "__main__":
    raise SystemExit(main())
