"""Example contestant: an event-driven RSI mean-reversion algo.

Demonstrates the look-ahead-safe Algo interface — it only ever inspects the
current bar and indicators over past data via ``ctx``.
"""

from math import isnan

from tradebot.arena import Action, Algo, register


@register(name="rsi_dip", author="house", tags=("mean-reversion", "event"))
class RsiDip(Algo):
    def __init__(self, period: int = 14, oversold: float = 30.0, exit_level: float = 55.0) -> None:
        self.period = period
        self.oversold = oversold
        self.exit_level = exit_level

    def on_bar(self, bar, ctx) -> Action:
        rsi = ctx.rsi(self.period)
        if isnan(rsi):              # still warming up
            return Action.hold()
        if rsi < self.oversold:     # oversold -> buy the dip
            return Action.long()
        if rsi > self.exit_level:   # recovered -> step aside
            return Action.flat()
        return Action.hold()        # in between -> keep current position
