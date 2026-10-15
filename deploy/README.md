# Keep tradebot-web running

The autopilot runs inside `tradebot-web`, so the server has to stay up on an
always-on machine (a home server, a Raspberry Pi, a small VPS). These files
start it at boot or login and restart it after a crash. Paper or dry-run only:
the web never trades a live account.

Every placeholder is spelled to stand out: `/PATH/TO/tradebot` (the checkout),
`YOUR_HOST` (the LAN IP or hostname the phone uses) and, on Linux, `YOUR_USER`.

## Before you enable anything

```bash
cd /PATH/TO/tradebot
make install-all && make web-build
```

Each flow below copies the config into place (on Linux it also hands the
directories to `YOUR_USER`), then runs `tradebot-web --check` as the user the
service runs as, never with `sudo`, before it enables the service. `--check`
creates the databases it opens: run with `sudo` it leaves them owned by root,
and the service cannot write them. `--check` loads and validates the config,
opens the database, prints the line the service logs at start, and exits 0.
Exit 1 says what is wrong. The line names the config file, the database, the
allowed hosts, whether the token and the Alpaca keys are set (never their
values) and the autopilot's stored mode.

## Linux (systemd)

```bash
sudo mkdir -p /etc/tradebot /var/lib/tradebot /PATH/TO/tradebot/data
sudo cp config.example.yaml /etc/tradebot/config.yaml
sudo install -m 600 /dev/null /etc/tradebot/env   # then add the three lines below
sudo chown -R YOUR_USER /etc/tradebot /var/lib/tradebot /PATH/TO/tradebot/data
sudo cp deploy/systemd/tradebot-web.service /etc/systemd/system/
sudo nano /etc/systemd/system/tradebot-web.service   # replace the placeholders
# as YOUR_USER, not with sudo:
.venv/bin/tradebot-web --check --config /etc/tradebot/config.yaml \
    --trading-db /var/lib/tradebot/tradebot.db --allow-host YOUR_HOST
sudo systemctl daemon-reload && sudo systemctl enable --now tradebot-web
journalctl -u tradebot-web -f                        # the startup line is here
```

`/etc/tradebot/env` holds `ALPACA_API_KEY=...`, `ALPACA_API_SECRET=...` and
`TRADEBOT_WEB_TOKEN=...` (paper keys; the token is what the phone signs in
with). `--check` from your shell does not read that file, so its line reports
the token and keys of your shell, not the service's. `/etc/tradebot` stays
writable because the Settings page saves the config there. The rest of the
file system is read-only to the service.

The service's database is `--trading-db`, which wins over the config's
`db_path` (without the flag or `TRADEBOT_DB`, `tradebot-web` uses `db_path`).
If you also run `tradebot run` on this machine, set
`db_path: /var/lib/tradebot/tradebot.db` in `/etc/tradebot/config.yaml` so both
share the watchlist and the parked trades.

## macOS (launchd)

```bash
cd /PATH/TO/tradebot && mkdir -p logs
cp config.example.yaml config.yaml
cp .env.example .env && chmod 600 .env    # keys, plus TRADEBOT_WEB_TOKEN=...
cp deploy/launchd/com.tradebot.web.plist ~/Library/LaunchAgents/
nano ~/Library/LaunchAgents/com.tradebot.web.plist   # replace the placeholders
.venv/bin/tradebot-web --check --config config.yaml --allow-host YOUR_HOST
launchctl load -w ~/Library/LaunchAgents/com.tradebot.web.plist
tail -f logs/tradebot-web.log
```

launchd cannot read an env file, so the secrets live in the `.env` in the
working directory, which `tradebot-web` reads at start (variables already set
win). The plist's `WorkingDirectory` is what makes it load: `tradebot-web`
looks for `.env` there and nowhere else. A LaunchAgent starts at login. Keep the Mac from sleeping, or the
autopilot sleeps with it.

## Update

```bash
cd /PATH/TO/tradebot && git pull && make install-all && make web-build
sudo systemctl restart tradebot-web        # macOS: launchctl kickstart -k gui/$(id -u)/com.tradebot.web
```

A restart keeps the config, the databases and the watchlist, and resumes the
autopilot in the mode it was left in (see "Keep it running" in the main
README).
