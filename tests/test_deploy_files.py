"""The service files in deploy/ parse, start tradebot-web, and keep their
placeholders obvious (no one's real path or host is committed)."""

from __future__ import annotations

import configparser
import plistlib
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def _unit() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str            # systemd keys are case-sensitive
    parser.read_string((DEPLOY / "systemd" / "tradebot-web.service").read_text())
    return parser


def test_the_systemd_unit_restarts_tradebot_web_with_its_env_file():
    service = _unit()["Service"]
    assert service["ExecStart"].startswith("/PATH/TO/tradebot/.venv/bin/tradebot-web ")
    assert "--config /etc/tradebot/config.yaml" in service["ExecStart"]
    assert "--allow-host YOUR_HOST" in service["ExecStart"]
    assert service["EnvironmentFile"] == "/etc/tradebot/env"
    assert service["WorkingDirectory"] == "/PATH/TO/tradebot"
    assert service["User"] == "YOUR_USER"
    assert service["Restart"] == "always" and service["RestartSec"] == "10"


def test_the_systemd_unit_is_hardened_but_can_write_its_data():
    service = _unit()["Service"]
    assert service["NoNewPrivileges"] == "true" and service["PrivateTmp"] == "true"
    assert service["ProtectSystem"] == "strict"
    writable = service["ReadWritePaths"].split()
    # The databases, the config the Settings page saves, and the bar cache.
    assert {"/var/lib/tradebot", "/etc/tradebot", "/PATH/TO/tradebot/data"} <= set(writable)
    for flag in ("--trading-db", "--arena-db", "--season-db"):
        assert f"{flag} /var/lib/tradebot/" in service["ExecStart"]


def test_the_launchd_plist_keeps_tradebot_web_alive_from_the_checkout():
    with (DEPLOY / "launchd" / "com.tradebot.web.plist").open("rb") as fh:
        plist = plistlib.load(fh)
    assert plist["Label"] == "com.tradebot.web"
    args = plist["ProgramArguments"]
    assert args[0] == "/PATH/TO/tradebot/.venv/bin/tradebot-web"
    assert args[args.index("--allow-host") + 1] == "YOUR_HOST"
    # The .env holding the secrets is read from the checkout's root.
    assert plist["WorkingDirectory"] == "/PATH/TO/tradebot"
    assert plist["KeepAlive"] is True and plist["RunAtLoad"] is True
    assert "EnvironmentVariables" not in plist         # secrets stay in .env


def test_the_deploy_readme_says_to_check_before_enabling():
    text = (DEPLOY / "README.md").read_text()
    assert "tradebot-web --check" in text
    assert text.index("--check") < text.index("systemctl daemon-reload")


def test_check_runs_after_the_chown_as_the_service_user():
    text = (DEPLOY / "README.md").read_text()
    linux = text[text.index("## Linux (systemd)"):text.index("## macOS (launchd)")]
    mac = text[text.index("## macOS (launchd)"):]
    chown = next(line for line in linux.splitlines() if "chown -R" in line)
    assert "/PATH/TO/tradebot/data" in chown.split()        # the bar cache too
    assert linux.index("chown -R") < linux.index("tradebot-web --check")
    assert mac.index("cp .env.example") < mac.index("tradebot-web --check")
    for flow in (linux, mac):
        check = next(line for line in flow.splitlines() if "tradebot-web --check" in line)
        assert not check.lstrip().startswith("sudo")        # as YOUR_USER, not root
    assert "root" in text and "with `sudo`" in text
