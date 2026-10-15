# Program Design: settings page

## Files
- `tradebot/config_io.py` (new, core): `settings_to_dict(settings) -> dict`
  (the YAML shape, editable keys only) and `write_settings(path, doc)`
  (atomic write). `Settings.from_dict` already parses.
- `tradebot/web/services/settings_service.py` (new): `editable(settings)`,
  `validate(doc) -> Settings`, `save(app_state, doc)`, `setup_status(...)`.
- `tradebot/web/routes/api/settings.py` (new): the three endpoints.
- `tradebot/web/routes/pages.py`: `GET /settings`.
- `tradebot/web/templates/pages/settings.html` (new),
  `components/setup_card.html` (new, included on Today).
- `frontend/src/components/settings.ts` (new): form state, strategy param
  fields from `/api/strategies`, save, error display.
- `tabbar.html`: Settings in the More sheet. Top nav gains Settings.
- `tests/test_config_io.py`, `tests/test_web_settings.py` (new).

## Types and signatures
```python
EDITABLE_KEYS = ("symbols", "timeframe", "poll_seconds", "initial_cash",
                 "strategy", "portfolio", "risk", "notify", "market",
                 "autopilot")
def settings_to_dict(settings: Settings) -> dict: ...
def write_settings(path: Path, doc: dict) -> None: ...
def validate(doc: dict) -> Settings: ...          # raises ValueError with a readable message
def setup_status(settings, settings_path, cache_dir) -> dict: ...
```

## Call stack
`POST /api/settings` -> `settings_service.save` -> `validate` ->
`write_settings` -> `app.state.settings = Settings.from_yaml(path)` ->
`autopilot_service.reset(app)` -> response `GET /api/settings` shape.

## Test plan
- `test_settings_round_trip_through_yaml_is_lossless_for_editable_keys`.
- `test_write_settings_is_atomic_and_never_contains_secrets`.
- `test_save_rejects_a_bad_strategy_name_with_a_readable_message`.
- `test_save_reloads_the_server_settings_and_resets_the_autopilot`.
- `test_mode_cannot_be_set_to_live_from_the_web` (422).
- `test_setup_status_reports_missing_config_credentials_and_bars`.
- `test_today_shows_the_setup_card_until_everything_is_ready`.

## Least confident decisions
1. A save rewrites `config.yaml` without comments. The example file keeps
   the documentation.
2. Secrets are read from `.env` only. The page never accepts a key.
3. `mode` is never editable from the web; `paper` is written when the file
   is created by the page.
