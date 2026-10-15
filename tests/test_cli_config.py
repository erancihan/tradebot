"""`tradebot` resolves its settings exactly as `tradebot-web` does."""

from __future__ import annotations

import pytest

from tradebot.cli import build_parser, main


@pytest.mark.parametrize("command", ["backtest", "run", "status", "universe"])
def test_config_is_optional(command):
    args = build_parser().parse_args([command])
    assert args.config is None


def test_run_names_the_config_it_used(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        f"symbols: [SPY]\ndb_path: {tmp_path / 't.db'}\n")
    assert main(["run", "--replay", "--replay-periods", "60"]) == 0
    captured = capsys.readouterr()
    assert "tradebot run: config=config.yaml" in captured.err
    assert "config=" not in captured.out


def test_status_says_defaults_without_a_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET"):
        monkeypatch.delenv(key, raising=False)
    assert main(["status"]) == 2
    assert "tradebot status: config=defaults" in capsys.readouterr().err


def test_universe_stdout_stays_pipeable_and_names_the_missing_config(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["universe"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""       # the startup line goes to stderr
    assert "tradebot universe: config=defaults" in captured.err
    assert "No config file found" in captured.err
    assert "config.yaml" in captured.err
