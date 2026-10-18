"""Live/paper trading engine.

One ``rebalance()`` pass:
  1. pull recent bars and current account/positions from the broker,
  2. build a :class:`~tradebot.advisor.Proposal` with ``advisor.propose`` —
     strategy targets, selector gate, allocator weights, RiskManager sizing,
  3. submit each line's delta as a market order and persist it.

Step 2 is the very function the Today page calls, so a suggestion and an
execution cannot disagree. The same Strategy + RiskManager objects power the
backtester, so behaviour is consistent between simulation and live. A
daily-loss circuit breaker flattens the book and stops trading for the rest
of the session day once breached (``engine.session``).

Callbacks live in ``hooks``; submitting and the timer loop in ``execution``.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .. import advisor
from ..advisor import Proposal
from ..broker.base import Broker
from ..config import Settings
from ..models import utcnow
from ..notify import LogNotifier
from ..risk import RiskManager
from ..storage import Storage
from ..strategies.base import Strategy
from . import orders, pending, session, signals, unlisted
from .execution import EngineExecutionMixin
from .hooks import EngineHooksMixin
from .orders import RebalanceAction
from .pending import PassOutcome

log = logging.getLogger("tradebot.engine")


class Engine(EngineHooksMixin, EngineExecutionMixin):
    def __init__(
        self,
        settings: Settings,
        broker: Broker,
        data_source,                 # object with .history(symbol, timeframe, lookback)
        strategy: Strategy,
        risk: RiskManager,
        storage: Storage | None = None,
        mode_label: str | None = None,
        enforce_live_ack: bool = True,
        allocator=None,              # optional tradebot.allocation.Allocator
        selector=None,               # optional tradebot.selection.Selector
        overlays=None,               # optional list of tradebot.overlays.Overlay
        notifier=None,               # optional tradebot.notify.Notifier
    ) -> None:
        # The live gate is skipped for dry-runs (no real broker can be reached).
        if enforce_live_ack:
            settings.require_live_ack()  # hard gate before anything can trade
        if overlays and allocator is None:
            raise ValueError("overlays require an allocator (they transform its weights)")
        self.settings = settings
        self.broker = broker
        self.data = data_source
        self.strategy = strategy
        self.risk = risk
        self.storage = storage
        self.allocator = allocator
        self.selector = selector
        self.overlays = list(overlays or [])
        self.notifier = notifier or LogNotifier()
        # Label used for logs and storage tagging (e.g. "dry_run").
        self._mode_label = mode_label or settings.mode
        self._session_start_equity: float | None = None
        self._session_day = None             # exchange-local date of the anchor
        self._halted_day = None              # the day the breaker flattened the book
        # Approved lines the broker accepted whose `submitted` mark has not
        # been written yet (e.g. the database was locked): never sent again.
        self._sent_line_ids: set[int] = set()

    @property
    def mode(self) -> str:
        return self._mode_label


    def rebalance(self, submit: bool = True,
                  now: datetime | None = None) -> list[RebalanceAction]:
        """One full pass; returns the submitted actions (none when ``submit``
        is False: the proposal is parked as pending instead, see ``step``)."""
        return self.step(submit=submit, now=now).actions

    def step(self, submit: bool = True, now: datetime | None = None, *,
             record: bool = True) -> PassOutcome:
        """One full pass: book bracket exits, read the account, build the
        proposal (``advisor.propose``), then submit its lines, or with
        ``submit=False`` store them as pending for approval (``record=False``:
        return them unstored; the autopilot may carry its batch over)."""
        if not self.broker.is_market_open():
            log.info("Market closed; skipping rebalance.")
            return PassOutcome(market_closed=True)

        # Before anything reads the account: a stop that fired on this bar has
        # to be booked first, or sizing would be done against stale equity.
        self._check_brackets()

        now = now or utcnow()             # the pass clock: a replay's is its bar time
        day = session.roll_session(self, now)
        acct = self.broker.account()
        if self._session_start_equity is None:
            self._session_start_equity = acct.equity
        if self.storage:
            self.storage.record_equity(acct.equity, acct.cash, self.mode)
        if session.halt_on_daily_loss(self, acct.equity, day, now):
            return PassOutcome(halted=True)

        proposal = self.propose(acct.equity, acct.cash, now=now)
        if self.storage and self.allocator is not None:
            # Post-overlay: what the book actually targets.
            self.storage.record_weights(proposal.weights or {}, self.mode)
        if not submit:
            batch = pending.record_pending(self, proposal) if record else None
            return PassOutcome(proposal=proposal, batch_id=batch)
        actions, failed = self._submit_all(proposal, now)
        return PassOutcome(actions=actions, proposal=proposal, failed=failed)

    def submit_lines(self, line_ids: list[int],
                     now: datetime | None = None) -> list[RebalanceAction]:
        """Submit stored pending lines (an approval) stamped ``now``; see
        ``engine.pending``, whose ``submit_stored`` also says what failed."""
        return pending.submit_stored(self, line_ids, now).actions

    def reset_session(self, start_equity: float | None = None) -> None:
        """Start a daily-loss session: from a persisted same-day anchor, or
        (``None``) at the equity the next pass sees. The next pass adopts its
        own session day, so a restored anchor is not rolled away."""
        self._session_start_equity = start_equity
        self._session_day = self._halted_day = None

    @property
    def session_start_equity(self) -> float | None:
        return self._session_start_equity

    def propose(self, equity: float, cash: float = 0.0,
                now: datetime | None = None) -> Proposal:
        """What this pass would trade: fetch bars and positions (held names off
        the list too, to close them, unless live or ``manage_unlisted`` is off),
        then ask the advisor. Submits nothing."""
        frames = signals.fetch_frames(self)
        positions = orders.current_positions(self, frames)
        return advisor.propose(
            symbols=list(self.settings.symbols), frames=frames, equity=equity,
            cash=cash, positions=positions, strategy=self.strategy, risk=self.risk,
            selector=self.selector, allocator=self.allocator, overlays=self.overlays,
            # Full stored history for a ranked selector (see `_selector_frames`).
            selector_frames=self._selector_frames(frames) if self.selector else None,
            now=now, unlisted=unlisted.read_unlisted(self),
        )
