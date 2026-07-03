"""Historical & latest market data via Alpaca's official SDK (``alpaca-py``).

The SDK is imported lazily inside methods so importing this module never fails
when the dependency is absent; the error only surfaces if you actually try to
fetch live data without it. Free Alpaca accounts get IEX data, which is plenty
for getting started.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from ..models import BAR_COLUMNS

# Map our simple timeframe strings to Alpaca TimeFrame objects at call time.
_TIMEFRAME_ALIASES = {
    "1min": ("Minute", 1),
    "5min": ("Minute", 5),
    "15min": ("Minute", 15),
    "1hour": ("Hour", 1),
    "1day": ("Day", 1),
}


class AlpacaData:
    def __init__(self, api_key: str, api_secret: str, feed: str = "iex") -> None:
        from alpaca.data.historical import StockHistoricalDataClient

        self.feed = feed
        self._client = StockHistoricalDataClient(api_key, api_secret)

    def _timeframe(self, timeframe: str):
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        try:
            unit_name, amount = _TIMEFRAME_ALIASES[timeframe]
        except KeyError:
            known = ", ".join(_TIMEFRAME_ALIASES)
            raise ValueError(f"Unknown timeframe {timeframe!r}. Known: {known}") from None
        return TimeFrame(amount, getattr(TimeFrameUnit, unit_name))

    def history(
        self,
        symbol: str,
        timeframe: str = "1day",
        lookback: int = 365,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch recent bars for a single symbol as a canonical OHLCV frame.

        ``lookback`` is in days for daily bars, otherwise an approximate window.
        """
        end = end or datetime.now(timezone.utc)
        start = end - timedelta(days=lookback)
        return self._fetch(symbol, timeframe, start, end)

    def bars(
        self,
        symbol: str,
        timeframe: str = "1day",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch bars over an explicit ``[start, end]`` window (used by the cache)."""
        end = end or datetime.now(timezone.utc)
        start = start or (end - timedelta(days=365))
        return self._fetch(symbol, timeframe, start, end)

    def history_many(
        self,
        symbols: list[str],
        timeframe: str = "1day",
        lookback: int = 365,
        end: datetime | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch recent bars for many symbols in one batched request.

        The SDK pages through ``next_page_token`` internally (the request
        ``limit`` is aggregate across symbols, so never set one here). Symbols
        with no bars in the window are simply absent from the result.
        """
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest

        end = end or datetime.now(timezone.utc)
        start = end - timedelta(days=lookback)
        req = StockBarsRequest(
            symbol_or_symbols=list(symbols),
            timeframe=self._timeframe(timeframe),
            start=start,
            end=end,
            feed=DataFeed(self.feed),
        )
        df = self._client.get_stock_bars(req).df
        return split_bars_frame(df, list(symbols))

    def _fetch(self, symbol: str, timeframe: str, start, end) -> pd.DataFrame:
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest

        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=self._timeframe(timeframe),
            start=start,
            end=end,
            feed=DataFeed(self.feed),
        )
        bars = self._client.get_stock_bars(req)
        df = bars.df
        if df.empty:
            return pd.DataFrame(columns=list(BAR_COLUMNS))
        # Multi-index (symbol, timestamp) -> single symbol slice.
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")
        return _normalize(df)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical OHLCV frame: tz-aware timestamp index, standard columns."""
    df = df.rename_axis("timestamp")
    df.index = pd.to_datetime(df.index, utc=True)
    return df[[c for c in BAR_COLUMNS if c in df.columns]]


def split_bars_frame(df: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Split the SDK's (symbol, timestamp) MultiIndex frame per symbol."""
    if df is None or df.empty:
        return {}
    if not isinstance(df.index, pd.MultiIndex):
        # Flat index only happens for a single-symbol response.
        return {symbols[0]: _normalize(df.copy())} if len(symbols) == 1 else {}
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            sub = df.xs(sym, level="symbol")
        except KeyError:
            continue
        if not sub.empty:
            out[sym] = _normalize(sub.copy())
    return out
