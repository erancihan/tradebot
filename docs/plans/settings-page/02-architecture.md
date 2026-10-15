# Architecture: settings page

## Fit
`Settings` already loads from YAML (`Settings.from_dict`). The page writes
the same YAML keys back. The web app holds `app.state.settings` and a
`settings_path`; a save rewrites the file and replaces the state object.
Secrets stay in the environment (`.env`), never in the YAML or the page.

## Endpoints
- `GET /settings`: page.
- `GET /api/settings`: the editable fields plus `credentials_present`,
  `config_path`, `config_exists`.
- `POST /api/settings`: full editable document; validates by building a
  `Settings` from it; writes `config.yaml` atomically (temp file + rename);
  reloads `app.state.settings`; stops a running autopilot loop and clears
  the cached runner so the next command rebuilds it with the new settings.
- `GET /api/setup`: `{config, credentials, bars}` each `{ok, hint}`; used by
  the Today setup card.

## Data
No new tables. `config.yaml` on disk. The YAML keeps comments only if the
file is written for the first time from `config.example.yaml`; a later save
writes a clean document (documented).

## Flow
Page loads `GET /api/settings` and `GET /api/strategies` (params for the
chosen strategy). Save posts the document; on 200 the page shows "saved"
and the Today page picks up the new symbols on the next refresh.

## External
None new. The `.env` file stays the place for `ALPACA_API_KEY` and
`ALPACA_API_SECRET`; the page shows whether they are present.
