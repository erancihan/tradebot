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

from .risk import RiskConfig

LIVE_CONFIRM_ENV = "TRADEBOT_LIVE_CONFIRM"
LIVE_CONFIRM_VALUE = "I_UNDERSTAND"
VALID_MODES = ("backtest", "paper", "live")


def _maybe_load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


@dataclass
class AlpacaCredentials:
    api_key: str
    api_secret: str
    feed: str = "iex"

    @classmethod
    def from_env(cls) -> "AlpacaCredentials | None":
        _maybe_load_dotenv()
        key = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_API_SECRET")
        if not key or not secret:
            return None
        return cls(api_key=key, api_secret=secret, feed=os.getenv("ALPACA_DATA_FEED", "iex"))


@dataclass
class Settings:
    mode: str = "paper"
    symbols: list[str] = field(default_factory=lambda: ["SPY"])
    timeframe: str = "1day"
    initial_cash: float = 10_000.0          # used by backtest
    poll_seconds: int = 300                 # live loop cadence
    strategy_name: str = "sma_crossover"
    strategy_params: dict[str, Any] = field(default_factory=dict)
    risk: RiskConfig = field(default_factory=RiskConfig)
    db_path: str = "tradebot.db"
    commission: float = 0.0
    slippage_bps: float = 1.0

    def __post_init__(self) -> None:
        if self.mode not in VALID_MODES:
            raise ValueError(f"mode must be one of {VALID_MODES}, got {self.mode!r}")
        if not self.symbols:
            raise ValueError("At least one symbol is required")

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
        risk_raw = raw.get("risk", {}) or {}
        strat = raw.get("strategy", {}) or {}
        return cls(
            mode=raw.get("mode", "paper"),
            symbols=list(raw.get("symbols", ["SPY"])),
            timeframe=raw.get("timeframe", "1day"),
            initial_cash=float(raw.get("initial_cash", 10_000.0)),
            poll_seconds=int(raw.get("poll_seconds", 300)),
            strategy_name=strat.get("name", raw.get("strategy_name", "sma_crossover")),
            strategy_params=strat.get("params", raw.get("strategy_params", {})) or {},
            risk=RiskConfig(**risk_raw),
            db_path=raw.get("db_path", "tradebot.db"),
            commission=float(raw.get("commission", 0.0)),
            slippage_bps=float(raw.get("slippage_bps", 1.0)),
        )
