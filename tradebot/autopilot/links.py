"""Signed approve/skip links for one pending batch: the phone push's buttons.

A link is a capability token: ``HMAC-SHA256(secret,
"{account}:{batch}:{verb}:{exp}")`` grants exactly one verb on exactly one
batch of one account (the engine's mode label) until ``exp`` (unix seconds). It
is the only credential the link endpoints check, so it is short-lived: twice
the poll interval, never less than thirty minutes. The same number spaces the
reminder pushes for a batch that waits unchanged (``approvals``), so a push's
buttons keep working until the next push arrives with fresh ones.

The secret is derived from ``TRADEBOT_WEB_TOKEN`` when one is set, so the web
server and a headless ``tradebot run --autopilot`` sign alike and links survive
a restart. Without a token it is random per process: links die with a restart,
and the next reminder push carries fresh ones.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from typing import Callable

TOKEN_ENV = "TRADEBOT_WEB_TOKEN"
VERBS = ("approve", "reject")
#: Never shorter than this, whatever the poll interval.
MIN_TTL_SECONDS = 1800
#: What ``signature`` emits; anything else is refused before comparing
#: (``compare_digest`` raises on a non-ASCII str).
_SIG = re.compile(r"[0-9a-f]{64}", re.ASCII)

#: Created once per process, at import: a link signed by this process is
#: verifiable only by this process.
_PROCESS_SECRET = secrets.token_bytes(32)


def link_secret(token: str | None) -> bytes:
    """The signing key: derived from the access token, else per-process random."""
    if token:
        return hmac.new(token.encode(), b"approval-links", hashlib.sha256).digest()
    return _PROCESS_SECRET


def env_secret() -> bytes:
    """``link_secret`` for the token in the environment (the CLI's path)."""
    return link_secret(os.getenv(TOKEN_ENV) or None)


def signature(secret: bytes, account: str, batch_id: int, verb: str, exp: int) -> str:
    msg = f"{account}:{int(batch_id)}:{verb}:{int(exp)}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def verify(secret: bytes, account: str, batch_id: int, verb: str, exp: int, sig: str,
           now: float | None = None) -> bool:
    """True only for an unexpired link signed for this account, batch and verb."""
    if verb not in VERBS:
        return False
    if (time.time() if now is None else now) > int(exp):
        return False
    if not isinstance(sig, str) or _SIG.fullmatch(sig) is None:
        return False
    return hmac.compare_digest(signature(secret, account, batch_id, verb, exp).encode(), sig.encode())


def ttl_seconds(poll_seconds: float) -> int:
    """A link's lifetime, and the reminder interval of an unchanged batch."""
    return max(int(2 * poll_seconds), MIN_TTL_SECONDS)


def link_signer(secret: bytes, account: str, poll_seconds: float,
                clock: Callable[[], float] = time.time) -> Callable[..., str]:
    """``signer(batch_id, verb, exp=None) -> "exp=...&sig=..."``, the query a link carries.

    ``account`` is the signing engine's mode label (``Autopilot.account``);
    the endpoint verifies with the web pilot's, so only that account's links act.
    Called when the batch is announced, right after the pass that made it, so
    "now + ttl" is the batch's creation plus the ttl. The autopilot passes the
    ``exp`` it computed for the push (the event's ``link_exp``): it keeps what
    each push showed under that expiry, so a tap is held to its own push.
    """
    ttl = ttl_seconds(poll_seconds)

    def sign(batch_id: int, verb: str, exp: int | None = None) -> str:
        if verb not in VERBS:
            raise ValueError(f"verb must be one of {VERBS}, got {verb!r}")
        exp = int(clock()) + ttl if exp is None else int(exp)
        return f"exp={exp}&sig={signature(secret, account, batch_id, verb, exp)}"

    return sign


class UsedLinks:
    """Single use: each signed link acts once per process.

    The push travels through the ntfy topic, so a link is replayable by
    anyone who saw it; a replay is refused instead of quietly re-running.
    The set lives in memory, by decision: after a restart a used link can act
    again until its ``exp``, bounded to its batch's lines still pending.
    Entries are dropped once their link has expired anyway, so the set stays
    the size of the links currently alive.
    """

    def __init__(self) -> None:
        self._used: dict[tuple[int, str, str], int] = {}
        self._lock = threading.Lock()

    def claim(self, batch_id: int, verb: str, exp: int, sig: str,
              now: float | None = None) -> bool:
        """True the first time; False for a replay."""
        key, now = (int(batch_id), verb, str(sig)), time.time() if now is None else now
        with self._lock:
            self._used = {k: e for k, e in self._used.items() if e >= now}
            if key in self._used:
                return False
            self._used[key] = int(exp)
            return True

    def release(self, batch_id: int, verb: str, sig: str) -> None:
        """Give a link back when it could not act (e.g. no engine yet)."""
        with self._lock:
            self._used.pop((int(batch_id), verb, str(sig)), None)
