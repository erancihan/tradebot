"""Configuration: YAML for strategy/risk knobs, environment for secrets.

Secrets (API keys) come from the environment only, never YAML (``credentials``).

Trading mode is one of: ``backtest``, ``paper`` (default), ``live``. Live is
intentionally awkward to enable: it requires both ``mode: live`` *and* the
environment variable ``TRADEBOT_LIVE_CONFIRM=I_UNDERSTAND`` so you cannot put
real money at risk by accident.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config_build import SettingsBuilders
from .config_load import settings_from_dict
from .credentials import AlpacaCredentials  # noqa: F401 - re-exported
from .risk import RiskConfig, product_risk

LIVE_CONFIRM_ENV = "TRADEBOT_LIVE_CONFIRM"
LIVE_CONFIRM_VALUE = "I_UNDERSTAND"
VALID_MODES = ("backtest", "paper", "live")


@dataclass
class Settings(SettingsBuilders):
    mode: str = "paper"
    symbols: list[str] = field(default_factory=lambda: ["SPY"])
    timeframe: str = "1day"
    initial_cash: float = 10_000.0          # used by backtest
    poll_seconds: int = 300                 # live loop cadence
    strategy_name: str = "sma_crossover"
    strategy_params: dict[str, Any] = field(default_factory=dict)
    #: Allocation scheme name (see tradebot.allocation); None keeps the legacy
    #: fixed max_position_pct-per-symbol sizing.
    allocation_name: str | None = None
    allocation_params: dict[str, Any] = field(default_factory=dict)
    #: Cross-sectional selector name (see tradebot.selection); None means every
    #: configured symbol is always eligible (no membership gate).
    selector_name: str | None = None
    selector_params: dict[str, Any] = field(default_factory=dict)
    #: Universe source name (see tradebot.universe); None keeps the static
    #: `symbols` list as the candidate pool.
    universe_name: str | None = None
    universe_params: dict[str, Any] = field(default_factory=dict)
    #: Overlay chain (see tradebot.overlays): list of {name, params} dicts,
    #: applied to allocator weights in order. Requires an allocation scheme.
    overlays: list[dict[str, Any]] = field(default_factory=list)
    #: The product's 1% no-trade band unless the YAML sets one (``product_risk``).
    risk: RiskConfig = field(default_factory=product_risk)
    #: Optional webhook for order/halt events (tradebot.notify); None = log-only.
    notify_webhook_url: str | None = None
    notify_ntfy_topic: str | None = None    #: phone push via ntfy (see README)
    notify_ntfy_server: str | None = None   #: None means https://ntfy.sh
    #: Where the phone reaches the server; adds Approve/Skip to a pending push.
    notify_public_url: str | None = None
    db_path: str = "tradebot.db"
    commission: float = 0.0
    slippage_bps: float = 1.0
    #: Exchange calendar for scheduling (see tradebot.market). Alpaca is the
    #: only broker, so a non-US calendar changes when loops wake, not trading.
    market: str = "us_equities"
    #: YAML `autopilot: {brief_minutes_before_open: N}`; None = no brief.
    brief_minutes_before_open: int | None = None
    #: Sell held names off the list (``engine/unlisted.py``). Live never does.
    manage_unlisted: bool = True

    def __post_init__(self) -> None:
        if self.mode not in VALID_MODES:
            raise ValueError(f"mode must be one of {VALID_MODES}, got {self.mode!r}")
        if not self.symbols:
            raise ValueError("At least one symbol is required")
        from .market.registry import check_market   # stdlib-only; no pandas

        check_market(self.market)

    # --- safety gate ---------------------------------------------------------
    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    def require_live_ack(self) -> None:
        """Raise unless the live-trading confirmation env var is set correctly."""
        if not self.is_live:
            return
        if os.getenv(LIVE_CONFIRM_ENV) != LIVE_CONFIRM_VALUE:
            raise PermissionError(
                "Refusing to trade live: set "
                f"{LIVE_CONFIRM_ENV}={LIVE_CONFIRM_VALUE} to confirm you intend "
                "to risk real money. (Or use mode: paper.)"
            )

    @property
    def broker_is_paper(self) -> bool:
        return self.mode != "live"

    # --- loading -------------------------------------------------------------
    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        return settings_from_dict(cls, raw)


from .config_resolve import (  # noqa: E402,F401 - re-exported
    DB_ENV, DEFAULT_SYMBOLS, resolve_settings, trading_db_path)
