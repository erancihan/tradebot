"""The pure-pandas liquidity screen, and the fetcher types that feed it."""

from __future__ import annotations

from typing import Callable

import pandas as pd

#: Injectable fetcher types (tests pass fakes; live code builds Alpaca ones).
ActivesFetcher = Callable[[int], list[str]]
TradableFetcher = Callable[[], "set[str] | None"]
BarsFetcher = Callable[[list[str]], "dict[str, pd.DataFrame]"]


class LiquidityScreen:
    """Pure-pandas liquidity gate: minimum price + rolling ADV floor.

    ``window`` bars of history are required to measure average dollar volume
    (close × volume); unmeasurable symbols never pass. Survivors are ranked by
    ADV descending (ties alphabetical) and optionally capped at
    ``max_symbols``.
    """

    def __init__(
        self,
        min_price: float = 5.0,
        min_dollar_volume: float = 1_000_000.0,
        window: int = 20,
        max_symbols: int | None = None,
    ) -> None:
        if min_price < 0 or min_dollar_volume < 0:
            raise ValueError("min_price and min_dollar_volume must be >= 0")
        if window < 1:
            raise ValueError(f"window must be >= 1, got {window}")
        if max_symbols is not None and max_symbols < 1:
            raise ValueError(f"max_symbols must be >= 1, got {max_symbols}")
        self.min_price = min_price
        self.min_dollar_volume = min_dollar_volume
        self.window = window
        self.max_symbols = max_symbols

    def details(self, frames: dict[str, pd.DataFrame]) -> list[dict[str, float | str]]:
        """Screen survivors with their metrics, ranked by ADV descending."""
        rows: list[dict[str, float | str]] = []
        for sym, df in frames.items():
            if df is None or len(df) < self.window:
                continue
            price = float(df["close"].iloc[-1])
            if not (price >= self.min_price):        # also rejects NaN
                continue
            dollar = (df["close"] * df["volume"]).rolling(
                self.window, min_periods=self.window
            ).mean()
            adv = dollar.iloc[-1]
            if pd.notna(adv) and float(adv) >= self.min_dollar_volume:
                rows.append({"symbol": sym, "price": price, "adv": float(adv)})
        rows.sort(key=lambda r: (-r["adv"], r["symbol"]))
        if self.max_symbols is not None:
            rows = rows[: self.max_symbols]
        return rows

    def screen(self, frames: dict[str, pd.DataFrame]) -> list[str]:
        return [str(r["symbol"]) for r in self.details(frames)]
