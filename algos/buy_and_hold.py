"""Example contestant: a buy-and-hold baseline (event-driven, always long).

Useful as a benchmark — any 'smart' algo should justify itself against it.
"""

from tradebot.arena import Action, Algo, register


@register(name="buy_and_hold", author="house", tags=("baseline", "event"))
class BuyAndHold(Algo):
    def on_bar(self, bar, ctx) -> Action:
        return Action.long()
