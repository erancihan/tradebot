"""Alpaca-backed candidate discovery (lazy SDK; every fetcher injectable)."""

from __future__ import annotations

import pandas as pd

from ..alpaca_http import bound_client
from .screen import ActivesFetcher, BarsFetcher, LiquidityScreen, TradableFetcher


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

    def resolve_details(self, exclude=()) -> list[dict[str, float | str]]:
        """Run the full pipeline and return survivors with price/ADV metrics.

        ``exclude`` (Discover's held and watched names) leaves the shortlist
        before the bars fetch and the ``max_symbols`` cap, so the cap counts
        only names the caller can use."""
        actives, tradable, bars = self._fetchers()
        skip = {str(s).upper() for s in exclude}
        shortlist = [s for s in actives(self.candidates) if str(s).upper() not in skip]
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
        from ..config import AlpacaCredentials

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

            client = bound_client(TradingClient(creds.api_key, creds.api_secret, paper=True))
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
            from ..data import get_alpaca_data

            ds = get_alpaca_data(creds.api_key, creds.api_secret, feed=creds.feed)
            # Calendar-day headroom so `window` trading days are available.
            return ds.history_many(symbols, timeframe="1day",
                                   lookback=self.screen.window * 2 + 15)

        return fetch
