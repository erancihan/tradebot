"""Signed approve/skip links: one batch, one verb, short-lived."""

from __future__ import annotations

import subprocess
import sys

import pytest

from tradebot.autopilot import links
from tradebot.autopilot.links import (MIN_TTL_SECONDS, link_secret, link_signer, signature,
                                      ttl_seconds, verify)

SECRET = link_secret("a-token")


def _parts(query: str) -> tuple[int, str]:
    fields = dict(p.split("=", 1) for p in query.split("&"))
    return int(fields["exp"]), fields["sig"]


def test_a_signed_link_verifies_for_its_batch_and_verb():
    sign = link_signer(SECRET, poll_seconds=300, clock=lambda: 1_000_000)
    exp, sig = _parts(sign(7, "approve"))
    assert exp == 1_000_000 + 600
    assert verify(SECRET, 7, "approve", exp, sig, now=1_000_000)
    assert len(sig) == 64 and int(sig, 16) >= 0


def test_an_expired_link_is_rejected():
    sign = link_signer(SECRET, poll_seconds=300, clock=lambda: 1_000_000)
    exp, sig = _parts(sign(7, "approve"))
    assert verify(SECRET, 7, "approve", exp, sig, now=exp)
    assert not verify(SECRET, 7, "approve", exp, sig, now=exp + 1)


@pytest.mark.parametrize("batch_id, verb, delta", [
    (8, "approve", 0),          # another batch
    (7, "reject", 0),           # another verb
    (7, "approve", 60),         # a stretched expiry
    (7, "delete", 0),           # not a verb at all
])
def test_a_tampered_link_is_rejected(batch_id, verb, delta):
    exp = 2_000_000_000
    sig = signature(SECRET, 7, "approve", exp)
    assert not verify(SECRET, batch_id, verb, exp + delta, sig, now=0)


def test_another_secret_does_not_verify():
    exp = 2_000_000_000
    sig = signature(SECRET, 7, "approve", exp)
    assert not verify(link_secret("other-token"), 7, "approve", exp, sig, now=0)
    assert not verify(link_secret(None), 7, "approve", exp, sig, now=0)


def test_ttl_is_twice_the_poll_never_under_ten_minutes():
    assert ttl_seconds(10) == MIN_TTL_SECONDS == 600
    assert ttl_seconds(900) == 1800


def test_the_signer_refuses_an_unknown_verb():
    with pytest.raises(ValueError):
        link_signer(SECRET, 300)(1, "delete")


_PRINT_SECRET = ("import sys; from tradebot.autopilot.links import link_secret; "
                 "print(link_secret(sys.argv[1] or None).hex())")


def _secret_in_another_process(token: str) -> str:
    out = subprocess.run([sys.executable, "-c", _PRINT_SECRET, token],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_the_token_secret_is_stable_across_processes():
    assert _secret_in_another_process("a-token") == SECRET.hex()


def test_without_a_token_the_secret_is_random_per_process():
    here = link_secret(None)
    assert here == link_secret(None) == links._PROCESS_SECRET     # stable in-process
    assert len(here) == 32
    assert _secret_in_another_process("") != here.hex()
    assert here != SECRET


def test_env_secret_reads_the_web_token(monkeypatch):
    monkeypatch.setenv("TRADEBOT_WEB_TOKEN", "a-token")
    assert links.env_secret() == SECRET
    monkeypatch.delenv("TRADEBOT_WEB_TOKEN")
    assert links.env_secret() == links._PROCESS_SECRET
