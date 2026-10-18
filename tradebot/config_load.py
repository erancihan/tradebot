"""Settings loading: the YAML file's nested shape into flat ``Settings`` fields.

Split from ``config.py`` so the dataclass reads as the list of knobs and the
safety gate; ``Settings.from_dict`` delegates here unchanged.
"""

from __future__ import annotations

from typing import Any

from .risk import product_risk


def settings_from_dict(cls, raw: dict[str, Any]):
    """Build ``cls`` (``Settings``) from the parsed YAML mapping."""
    risk_raw = raw.get("risk", {}) or {}
    strat = raw.get("strategy", {}) or {}
    portfolio = raw.get("portfolio", {}) or {}
    return cls(
        mode=raw.get("mode", "paper"),
        # Upper-case, as the broker reports them: `spy` must not read as off-list.
        symbols=[str(s).strip().upper() for s in raw.get("symbols", ["SPY"])],
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
        manage_unlisted=bool(raw.get("manage_unlisted", True)),
    )


def _public_url(value: Any) -> Any:
    """No trailing slash, and empty means unset; a non-string is left for
    the Settings validation to refuse readably."""
    return (value.rstrip("/") or None) if isinstance(value, str) else value
