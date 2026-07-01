"""Broker adapters. The Alpaca adapter is imported lazily via :func:`get_broker`."""

from __future__ import annotations

from .base import AccountSnapshot, Broker
from .dryrun import DryRunBroker

__all__ = ["Broker", "AccountSnapshot", "DryRunBroker", "get_broker"]


def get_broker(*args, **kwargs):
    """Lazy accessor for the Alpaca broker (avoids importing the SDK eagerly)."""
    from .alpaca_broker import AlpacaBroker

    return AlpacaBroker(*args, **kwargs)
