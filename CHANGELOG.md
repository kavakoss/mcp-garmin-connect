# Changelog

## 0.3.0 — 2026-10-27

### Added
- **Official Garmin Connect Personal API backend.** Set `GARMIN_PERSONAL_API_KEY`
  (create one at <https://connect.garmin.com/app/settings/personalApiToken>) and
  `GARMIN_AUTH_MODE=auto|personal|unofficial`. Keys are exchanged for a 24-hour
  bearer token, cached at `~/.garminconnect/personal_api_token.json` (mode 0600),
  keyed by a hash of the API key, with one automatic refresh on `401`.
  See `docs/personal-api.md`.
- **`GARMIN_AUTH_MODE=hybrid`** runs both backends in one process: wellness and
  raw-file reads go to the official API, Garmin-derived metrics (training
  status/load, readiness, VO2 Max, race predictions, PRs) go to email/password,
  with automatic fallback when a read fails. Auth errors are never masked.
  `serve --auth-mode hybrid` overrides it for a single run.
- `get_full_snapshot` now tags each section with `data_source` (plus
  `source_detail` for mixed sections), lists `hybrid_fallbacks`, and exposes
  `auth_backend` / `section_sources`. Attribution survives the endpoint cache and
  the multi-threaded day loops, so a fallback is visible instead of silent.
- Six new tools, available on the Personal API backend: `get_body_composition`,
  `get_spo2`, `get_hydration`, `get_steps_history`, `get_fitness_age`, and
  `download_activity_file` (original `.FIT` inside a ZIP).
- `garmin-mcp personal-api --check | --refresh-token | --probe PATH` to validate
  the key, rotate the cached token, and dump raw endpoint payloads.
- `doctor` reports the active backend, key presence and token cache, plus
  `personal-api-live` with `--live`.

### Changed
- Metrics the official API does not expose (training status/load, readiness,
  VO2 Max, race predictions, personal records) now degrade to `null` with an
  explanatory `errors` entry instead of failing the whole call.
- README tool count corrected (it said 15 while 18 were registered) and the tool
  table now marks Personal-API-only tools.

### Notes
- Garmin strips some computed fields (VO2 Max, recovery time, performance
  condition) from files delivered through its API, so `download_activity_file`
  is not byte-identical to a manual Garmin Connect download.

## 0.2.0 — 2026-09-29

- `get_activity_splits` with per-lap pace, HR, cadence, elevation and HR drift.
- Offline demo mode (`serve --demo`) with fictional data.
- Paged activity history, configurable caps, `recovery_time_hours` unit fix (#3).
- Explicit `start_date`/`end_date` windows for activity queries.
- `get_hrv_history` and `get_body_battery_range` for longer trend windows.
