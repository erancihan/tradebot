"""A job's error text is the sentence meant for the person, not a traceback head."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from tradebot.web.services.jobs.registry import _error_text  # noqa: E402


def test_an_expected_failure_is_its_own_sentence():
    assert _error_text(RuntimeError("no cached daily bars to search")) == (
        "no cached daily bars to search")
    assert _error_text(ValueError("give between 1 and 12 symbols")) == (
        "give between 1 and 12 symbols")


def test_an_unexpected_failure_keeps_its_class_as_the_clue():
    assert _error_text(KeyError("close")) == "KeyError: 'close'"
    assert _error_text(RuntimeError("")) == "RuntimeError: "
