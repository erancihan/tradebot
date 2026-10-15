"""Configuration: YAML for strategy/risk knobs, environment for secrets.

Secrets (API keys) are read from the environment only and never live in YAML,
so a config file is safe to commit. A `.env` file is loaded if python-dotenv is
installed, but it is optional.

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

from .credentials import AlpacaCredentials  # noqa: F401 - re-exported
from .risk import RiskConfig, product_risk

LIVE_CONFIRM_ENV = "TRADEBOT_LIVE_CONFIRM"
LIVE_CONFIRM_VALUE = "I_UNDERSTAND"
VALID_MODES = ("backtest", "paper", "live")


@dataclass
class Settings:
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
    #: Optional webhook for order/halt events (see tradebot.notify). None keeps
    #: notifications log-only.
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

    def build_allocator(self):
        """Instantiate the configured allocator, or None for legacy sizing.

        Imported lazily so merely loading config never pulls in pandas.
        """
        if self.allocation_name is None:
            return None
        from .allocation import build_allocator

        return build_allocator(self.allocation_name, self.allocation_params)

    def build_selector(self):
        """Instantiate the configured selector, or None for no membership gate."""
        if self.selector_name is None:
            return None
        from .selection import build_selector

        return build_selector(self.selector_name, self.selector_params)

    def build_universe(self):
        """Instantiate the configured universe source, or None for the static list."""
        if self.universe_name is None:
            return None
        from .universe import build_universe

        return build_universe(self.universe_name, self.universe_params)

    def build_notifier(self, link_signer=None):
        """Instantiate the configured notifier (log-only unless a channel is set).
        ``link_signer`` (``tradebot.autopilot.links``) arms the push's buttons."""
        from .notify import build_notifier

        return build_notifier(self.notify_webhook_url, self.notify_ntfy_topic,
                              self.notify_ntfy_server, public_url=self.notify_public_url,
                              link_signer=link_signer)

    def build_overlays(self) -> list:
        """Instantiate the configured overlay chain (empty list when unset)."""
        if not self.overlays:
            return []
        if self.allocation_name is None:
            raise ValueError(
                "portfolio.overlays requires an allocation scheme "
                "(set portfolio.allocation, e.g. `equal`)"
            )
        from .overlays import build_overlay

        return [build_overlay(o.get("name"), o.get("params")) for o in self.overlays]

    # --- loading -------------------------------------------------------------
    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        risk_raw = raw.get("risk", {}) or {}
        strat = raw.get("strategy", {}) or {}
        portfolio = raw.get("portfolio", {}) or {}
        return cls(
            mode=raw.get("mode", "paper"),
            symbols=list(raw.get("symbols", ["SPY"])),
            timeframe=raw.get("timeframe", "1day"),
            initial_cash=float(raw.get("initial_cash", 10_000.0)),
            poll_seconds=int(raw.get("poll_seconds", 300)),
            strategy_name=strat.get("name", raw.get("strategy_name", "sma_crossover")),
            strategy_params=strat.get("params", raw.get("strategy_params", {})) or {},
            allocation_name=portfolio.get("allocation"),
            allocation_params=portfolio.get("params", {}) or {},
            selector_name=(portfolio.get("selector", {}) or {}).get("name"),
            selector_params=(portfolio.get("selector", {}) or {}).get("params", {}) or {},
            universe_name=(raw.get("universe", {}) or {}).get("source"),
            universe_params=(raw.get("universe", {}) or {}).get("params", {}) or {},
            overlays=list(portfolio.get("overlays", []) or []),
            risk=product_risk(**risk_raw),
            notify_webhook_url=(raw.get("notify", {}) or {}).get("webhook_url"),
            notify_ntfy_topic=(raw.get("notify", {}) or {}).get("ntfy_topic"),
            notify_ntfy_server=(raw.get("notify", {}) or {}).get("ntfy_server"),
            notify_public_url=_public_url((raw.get("notify", {}) or {}).get("public_url")),
            db_path=raw.get("db_path", "tradebot.db"),
            commission=float(raw.get("commission", 0.0)),
            slippage_bps=float(raw.get("slippage_bps", 1.0)),
            market=raw.get("market", "us_equities"),
            # 0 reads as "no brief", the same as leaving it out.
            brief_minutes_before_open=(raw.get("autopilot", {}) or {}).get(
                "brief_minutes_before_open") or None,
        )


def _public_url(value: Any) -> Any:
    """No trailing slash, and empty means unset; a non-string is left for
    the Settings validation to refuse readably."""
    return (value.rstrip("/") or None) if isinstance(value, str) else value


from .config_resolve import DEFAULT_SYMBOLS, resolve_settings  # noqa: E402,F401 - re-exported
