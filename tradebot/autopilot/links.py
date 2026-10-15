"""Signed approve/skip links for one pending batch: the phone push's buttons.

A link is a capability token: ``HMAC-SHA256(secret, "{batch}:{verb}:{exp}")``
grants exactly one verb on exactly one batch until ``exp`` (unix seconds). It
is the only credential the link endpoints check, so it is short-lived: twice
the poll interval (a pending batch expires at the next pass anyway), never
less than ten minutes so a slow tap still lands.

The secret is derived from ``TRADEBOT_WEB_TOKEN`` when one is set, so the web
server and a headless ``tradebot run --autopilot`` sign alike and links survive
a restart. Without a token it is random per process: links die with a restart,
which is fine because a restart's next pass expires the batch too.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from typing import Callable

TOKEN_ENV = "TRADEBOT_WEB_TOKEN"
VERBS = ("approve", "reject")
#: Never shorter than this, whatever the poll interval.
MIN_TTL_SECONDS = 600

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


def signature(secret: bytes, batch_id: int, verb: str, exp: int) -> str:
    msg = f"{int(batch_id)}:{verb}:{int(exp)}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def verify(secret: bytes, batch_id: int, verb: str, exp: int, sig: str,
           now: float | None = None) -> bool:
    """True only for an unexpired link signed for this batch and this verb."""
    if verb not in VERBS:
        return False
    if (time.time() if now is None else now) > int(exp):
        return False
    return hmac.compare_digest(signature(secret, batch_id, verb, exp), str(sig))


def ttl_seconds(poll_seconds: float) -> int:
    return max(int(2 * poll_seconds), MIN_TTL_SECONDS)


def link_signer(secret: bytes, poll_seconds: float,
                clock: Callable[[], float] = time.time) -> Callable[[int, str], str]:
    """``signer(batch_id, verb) -> "exp=...&sig=..."``, the query a link carries.

    Called when the batch is announced, right after the pass that made it, so
    "now + ttl" is the batch's creation plus the ttl.
    """
    ttl = ttl_seconds(poll_seconds)

    def sign(batch_id: int, verb: str) -> str:
        if verb not in VERBS:
            raise ValueError(f"verb must be one of {VERBS}, got {verb!r}")
        exp = int(clock()) + ttl
        return f"exp={exp}&sig={signature(secret, batch_id, verb, exp)}"

    return sign


class UsedLinks:
    """Single use: each signed link acts once per process.

    The push travels through the ntfy topic, so a link is replayable by
    anyone who saw it; a replay is refused instead of quietly re-running.
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
