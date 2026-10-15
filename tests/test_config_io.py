"""config_io: Settings back to YAML, losslessly for what the web edits."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tradebot.config import Settings
from tradebot.config_io import EDITABLE_KEYS, editable, settings_to_dict, write_settings

ROOT = Path(__file__).resolve().parent.parent


def test_settings_round_trip_through_yaml_is_lossless_for_editable_keys(tmp_path):
    original = Settings.from_yaml(ROOT / "config.example.yaml")
    doc = settings_to_dict(original)
    write_settings(tmp_path / "config.yaml", doc)
    again = Settings.from_yaml(tmp_path / "config.yaml")
    assert editable(settings_to_dict(again)) == editable(doc)
    assert again == original


def test_round_trip_keeps_a_full_portfolio_block(tmp_path):
    original = Settings.from_dict({
        "symbols": ["SPY", "QQQ", "IWM"],
        "portfolio": {"selector": {"name": "momentum", "params": {"top_k": 2}},
                      "allocation": "inverse_vol", "params": {"window": 21},
                      "overlays": [{"name": "vol_target", "params": {"target_vol": 0.15}}]},
        "risk": {"stop_loss_pct": 0.05},
        "notify": {"ntfy_topic": "abc"},
        "autopilot": {"brief_minutes_before_open": 30},
        "universe": {"source": "alpaca_liquidity", "params": {"candidates": 50}},
    })
    write_settings(tmp_path / "c.yaml", settings_to_dict(original))
    assert Settings.from_yaml(tmp_path / "c.yaml") == original


def test_write_settings_is_atomic_and_never_contains_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "PKSECRETKEY")
    monkeypatch.setenv("ALPACA_API_SECRET", "very-secret-value")
    path = tmp_path / "config.yaml"
    path.write_text("old: true\n")
    write_settings(path, settings_to_dict(Settings()))
    text = path.read_text()
    assert "PKSECRETKEY" not in text and "very-secret-value" not in text
    assert text.startswith("# Written by the tradebot Settings page")
    assert list(tmp_path.iterdir()) == [path]          # no temp file left behind

    with pytest.raises(ValueError, match="secrets"):
        write_settings(path, {"symbols": ["SPY"], "api_secret": "x"})
    assert path.read_text() == text                    # the old file is untouched

    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr("tradebot.config_io.os.replace", boom)
    with pytest.raises(OSError):
        write_settings(path, {"symbols": ["QQQ"]})
    assert path.read_text() == text and list(tmp_path.iterdir()) == [path]


def test_unset_values_are_left_out_of_the_file(tmp_path):
    write_settings(tmp_path / "c.yaml", settings_to_dict(Settings()))
    raw = yaml.safe_load((tmp_path / "c.yaml").read_text())
    assert "portfolio" not in raw and "notify" not in raw and "autopilot" not in raw
    assert "stop_loss_pct" not in raw["risk"]


def test_editable_keys_never_include_the_mode():
    assert "mode" not in EDITABLE_KEYS and "db_path" not in EDITABLE_KEYS
