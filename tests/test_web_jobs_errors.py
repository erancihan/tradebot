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


def test_a_subclass_of_an_expected_type_keeps_its_class():
    class DailyLimit(ValueError):
        pass

    assert _error_text(DailyLimit("halted for the day")) == "DailyLimit: halted for the day"


def test_a_registry_key_error_is_its_sentence_without_quotes():
    from tradebot.strategies.registry import build_strategy

    with pytest.raises(KeyError) as info:
        build_strategy("nope")
    text = _error_text(info.value)
    assert text.startswith("Unknown strategy 'nope'. Known: ")
    assert not text.startswith(("KeyError", '"'))
    assert _error_text(KeyError("close")) == "KeyError: 'close'"     # still the clue
