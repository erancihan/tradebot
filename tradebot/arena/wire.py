"""The child's reply, as plain JSON data the parent rebuilds and validates.

The child runs contestant code, so everything it sends is untrusted. It used
to send pickles, and unpickling a crafted ``__reduce__`` ran code in the
unsandboxed parent. Now the reply is one JSON line of strings, numbers, lists
and dicts, checked shape by shape here; anything else is a ``WireError`` and
that contestant is an ERROR. A contestant can still misreport its *own*
result: the boundary protects the parent, not the leaderboard's honesty.
"""

from __future__ import annotations

import json
import math

import pandas as pd

from ..backtest import BacktestResult
from ..models import Trade

#: Upper bounds on what the parent will accept, so a reply cannot exhaust it.
MAX_REPLY_BYTES = 64 * 1024 * 1024
_MAX_TEXT = 2000
_STATUSES = ("ok", "error")


class WireError(ValueError):
    """The child's reply is not the plain data the protocol allows."""


# --------------------------------------------------------------------------- #
# Child side: plain data out.
# --------------------------------------------------------------------------- #
def _iso(ts) -> str | None:
    return None if ts is None else pd.Timestamp(ts).isoformat()


def encode_result(result: BacktestResult) -> dict:
    curve = result.equity_curve
    return {
        "equity": [float(v) for v in curve.to_numpy()],
        "index": [pd.Timestamp(t).isoformat() for t in curve.index],
        "freq": getattr(curve.index, "freqstr", None),
        "trades": [[t.symbol, float(t.qty), float(t.entry_price), float(t.exit_price),
                    float(t.pnl), _iso(t.timestamp), _iso(t.entry_ts), t.side]
                   for t in result.trades],
        "initial_cash": float(result.initial_cash),
        "periods_per_year": float(result.periods_per_year),
    }


def encode_line(message: dict) -> bytes:
    return (json.dumps(message, allow_nan=True) + "\n").encode()


# --------------------------------------------------------------------------- #
# Parent side: validate, then rebuild.
# --------------------------------------------------------------------------- #
def _require(cond: bool, what: str) -> None:
    if not cond:
        raise WireError(what)


def _number(v) -> float:
    _require(isinstance(v, (int, float)) and not isinstance(v, bool), "not a number")
    try:
        return float(v)
    except OverflowError as exc:
        raise WireError("number out of range") from exc


def _text(v, limit: int = 256) -> str:
    _require(isinstance(v, str) and len(v) <= limit, "not a short string")
    return v


def _stamp(v) -> pd.Timestamp:
    try:
        return pd.Timestamp(_text(v, 64))
    except (TypeError, ValueError) as exc:
        raise WireError(f"bad timestamp: {exc}") from exc


def _trade(row) -> Trade:
    _require(isinstance(row, list) and len(row) == 8, "a trade is 8 fields")
    symbol, qty, entry, exit_, pnl, ts, entry_ts, side = row
    return Trade(symbol=_text(symbol, 32), qty=_number(qty), entry_price=_number(entry),
                 exit_price=_number(exit_), pnl=_number(pnl),
                 timestamp=_stamp(ts).to_pydatetime(),
                 entry_ts=None if entry_ts is None else _stamp(entry_ts).to_pydatetime(),
                 side=_text(side, 8))


def decode_result(data) -> BacktestResult:
    _require(isinstance(data, dict), "a result is an object")
    equity, index, trades = data.get("equity"), data.get("index"), data.get("trades")
    _require(isinstance(equity, list) and isinstance(index, list)
             and len(equity) == len(index) and len(equity) > 0, "equity and index")
    _require(isinstance(trades, list), "trades is a list")
    values = [_number(v) for v in equity]
    try:
        freq = data.get("freq")
        stamps = pd.DatetimeIndex([_stamp(t) for t in index],
                                  freq=None if freq is None else _text(freq, 16))
    except (TypeError, ValueError) as exc:   # mixed time zones, say
        raise WireError(f"bad index: {exc}") from exc
    initial = _number(data.get("initial_cash"))
    ppy = _number(data.get("periods_per_year"))
    _require(math.isfinite(initial) and initial > 0 and math.isfinite(ppy) and ppy > 0,
             "initial cash and periods per year are positive")
    return BacktestResult(equity_curve=pd.Series(values, index=stamps, name="equity"),
                          trades=[_trade(t) for t in trades], initial_cash=initial,
                          periods_per_year=ppy)


def decode_discovery(data) -> tuple[list[dict], list[tuple[str, str]]]:
    """Contestant metadata (name, kind, author, tags, family) and load errors."""
    _require(isinstance(data, dict), "discovery is an object")
    found, errors = data.get("contestants"), data.get("errors")
    _require(isinstance(found, list) and isinstance(errors, list), "two lists")
    metas = []
    for m in found:
        _require(isinstance(m, dict), "a contestant is an object")
        tags = m.get("tags")
        _require(isinstance(tags, list) and len(tags) <= 32, "tags")
        metas.append({"name": _text(m.get("name")),
                      "kind": _text(m.get("kind"), 16), "author": _text(m.get("author")),
                      "tags": tuple(_text(t, 64) for t in tags),
                      "family": _text(m.get("family"))})
    errs = [(_text(e[0], 4096), _text(e[1], _MAX_TEXT)) for e in errors
            if isinstance(e, list) and len(e) == 2]
    _require(len(errs) == len(errors), "a load error is [path, message]")
    return metas, errs


def decode_reply(line: bytes) -> dict:
    """The reply envelope: status, denied mechanisms, error text or a result."""
    try:
        msg = json.loads(line)
    except (ValueError, UnicodeDecodeError) as exc:
        raise WireError(f"not JSON: {exc}") from exc
    _require(isinstance(msg, dict) and msg.get("status") in _STATUSES, "status")
    denied = msg.get("denied", [])
    _require(isinstance(denied, list) and len(denied) <= 16, "denied")
    out = {"status": msg["status"], "denied": [_text(d, 64) for d in denied]}
    if msg["status"] == "error":
        error = msg.get("error")
        _require(isinstance(error, str), "error text")
        out["error"] = error[:_MAX_TEXT]
    else:
        out["result"] = msg.get("result")
    return out
