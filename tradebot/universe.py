"""Universe selection: discover *candidate* symbols worth considering at all.

This sits upstream of everything: universe → selector (which of these to hold)
→ allocator (how much) → RiskManager (quantities). The universe changes rarely
(resolved at process start), while the selector re-ranks every bar.

The only live source is an Alpaca liquidity screen (owner decision): shortlist
today's most-active names, keep the ones Alpaca marks active + tradable, pull
recent daily bars in one batched request, and keep those above a minimum price
and rolling average dollar volume. Alpaca's free IEX feed reports only ~2% of
consolidated volume, so dollar-volume floors are conservative by construction —
set them accordingly.

Honesty note: a universe screened *today* and replayed over history is
survivorship-biased — fine for live-forward paper trading, not evidence for
historical claims. The engine records each resolved universe to SQLite so the
paper trail is point-in-time.

All Alpaca calls are lazy and injectable, so the screen itself tests offline.
"""

from __future__ import annotations

from typing import Any, Callable

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


class AlpacaLiquidityUniverse:
    """Candidate discovery from Alpaca: most-actives → tradable → ADV screen.

    ``candidates`` most-active names (by share volume) form the shortlist —
    cheap, and any name liquid enough to trade is active almost by definition.
    Activity skews to cheap/meme names, which is exactly what the price and
    dollar-volume floors then strip out.
    """

    name = "alpaca_liquidity"

    def __init__(
        self,
        candidates: int = 100,
        min_price: float = 5.0,
        min_dollar_volume: float = 1_000_000.0,
        window: int = 20,
        max_symbols: int | None = 20,
        fractionable_only: bool = False,
        actives_fetcher: ActivesFetcher | None = None,
        tradable_fetcher: TradableFetcher | None = None,
        bars_fetcher: BarsFetcher | None = None,
    ) -> None:
        if candidates < 1:
            raise ValueError(f"candidates must be >= 1, got {candidates}")
        self.candidates = candidates
        self.fractionable_only = fractionable_only
        self.screen = LiquidityScreen(min_price, min_dollar_volume, window, max_symbols)
        self._actives = actives_fetcher
        self._tradable = tradable_fetcher
        self._bars = bars_fetcher

    # --- resolution ------------------------------------------------------------

    def resolve(self) -> list[str]:
        return [str(r["symbol"]) for r in self.resolve_details()]

    def resolve_details(self) -> list[dict[str, float | str]]:
        """Run the full pipeline and return survivors with price/ADV metrics."""
        actives, tradable, bars = self._fetchers()
        shortlist = actives(self.candidates)
        allowed = tradable()
        if allowed is not None:
            shortlist = [s for s in shortlist if s in allowed]
        if not shortlist:
            return []
        frames = bars(shortlist)
        return self.screen.details(frames)

    # --- live Alpaca plumbing (lazy; only touched when nothing was injected) ----

    def _fetchers(self) -> tuple[ActivesFetcher, TradableFetcher, BarsFetcher]:
        if self._actives and self._tradable and self._bars:
            return self._actives, self._tradable, self._bars
        from .config import AlpacaCredentials

        creds = AlpacaCredentials.from_env()
        if creds is None:
            raise RuntimeError(
                "Universe resolution needs Alpaca credentials "
                "(ALPACA_API_KEY / ALPACA_API_SECRET in the environment/.env)."
            )
        return (
            self._actives or self._build_actives(creds),
            self._tradable or self._build_tradable(creds),
            self._bars or self._build_bars(creds),
        )

    @staticmethod
    def _build_actives(creds) -> ActivesFetcher:
        def fetch(top: int) -> list[str]:
            from alpaca.data.historical.screener import ScreenerClient
            from alpaca.data.requests import MostActivesRequest

            client = ScreenerClient(creds.api_key, creds.api_secret)
            resp = client.get_most_actives(MostActivesRequest(by="volume", top=top))
            return [a.symbol for a in resp.most_actives]

        return fetch

    def _build_tradable(self, creds) -> TradableFetcher:
        def fetch() -> set[str] | None:
            from alpaca.trading.client import TradingClient
            from alpaca.trading.enums import AssetClass, AssetStatus
            from alpaca.trading.requests import GetAssetsRequest

            client = TradingClient(creds.api_key, creds.api_secret, paper=True)
            assets = client.get_all_assets(
                GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY)
            )
            return {
                a.symbol
                for a in assets
                if a.tradable and (a.fractionable or not self.fractionable_only)
            }

        return fetch

    def _build_bars(self, creds) -> BarsFetcher:
        def fetch(symbols: list[str]) -> dict[str, pd.DataFrame]:
            from .data import get_alpaca_data

            ds = get_alpaca_data(creds.api_key, creds.api_secret, feed=creds.feed)
            # Calendar-day headroom so `window` trading days are available.
            return ds.history_many(symbols, timeframe="1day",
                                   lookback=self.screen.window * 2 + 15)

        return fetch


UNIVERSES: dict[str, type[AlpacaLiquidityUniverse]] = {
    AlpacaLiquidityUniverse.name: AlpacaLiquidityUniverse,
}


def build_universe(name: str, params: dict[str, Any] | None = None):
    """Instantiate a universe source by name with keyword params from config."""
    try:
        cls = UNIVERSES[name]
    except KeyError:
        known = ", ".join(sorted(UNIVERSES))
        raise KeyError(f"Unknown universe source {name!r}. Known: {known}") from None
    return cls(**(params or {}))
