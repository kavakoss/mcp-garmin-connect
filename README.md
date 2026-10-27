![mcp-garmin-connect](docs/assets/banner.svg)

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PyPI](https://img.shields.io/pypi/v/mcp-garmin-connect)](https://pypi.org/project/mcp-garmin-connect/)
[![MCP](https://img.shields.io/badge/MCP-compatible-6D28D9)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/kavakoss/mcp-garmin-connect/actions/workflows/ci.yml/badge.svg)](https://github.com/kavakoss/mcp-garmin-connect/actions/workflows/ci.yml)

**LLM-agnostic Garmin Connect MCP server** for training, recovery, sleep, stress, VO2 Max, race predictions, and running summaries.

Use the same local Garmin tools from any MCP client — Claude Desktop, Claude Code, Cursor, Continue, Hermes, opencode — or from provider-backed demo agents using DeepSeek, OpenAI, Claude, OpenRouter, or Gemini.

## See It In Action

![opencode checking Garmin recovery through mcp-garmin-connect](docs/assets/demo.gif)

Recorded with `garmin-mcp serve --demo`, which serves deterministic **fictional** sample data — no Garmin credentials and no real health data involved:

```bash
uvx mcp-garmin-connect serve --demo
```

## Works With Any MCP Harness

This server implements standard MCP over `stdio` and Streamable HTTP, so there is no harness-specific adapter to maintain. If your tool speaks MCP, it works:

| Harness | Connection |
|---|---|
| Claude Code / Claude Desktop | `mcpServers` stdio config |
| Codex CLI | MCP server config |
| Gemini CLI | MCP server config |
| Cursor, Windsurf, Zed, VS Code Copilot, Continue | MCP server settings (stdio or HTTP) |
| opencode | `mcp` block in `opencode.json` |
| Hermes | stdio or HTTP |
| Custom agents, web bots, scripts | Streamable HTTP at `http://127.0.0.1:8765/mcp` |

Any client that supports MCP over `stdio` or Streamable HTTP can use every tool and prompt in this server with no extra code.

## Why This Exists

Most fitness advice from LLMs is generic. This server lets an LLM inspect your real Garmin Connect data first, then answer with context from your activities, recovery markers, HRV, sleep, stress, VO2 Max, and running history.

The core server is provider-neutral. DeepSeek, OpenAI, Claude, OpenRouter, and Gemini integrations are optional demo bridges for clients that do not speak MCP directly.

## Two Garmin Backends

| | **personal** (official) | **unofficial** (email/password) |
|---|---|---|
| Auth | Self-serve API key → 24 h bearer token | Garmin SSO + cached tokens |
| Stability | Documented, rate-limit friendly | Breaks when SSO/Cloudflare changes |
| Raw `.FIT` download | ✅ | ❌ |
| Sleep/HRV/stress/body battery/RHR/weight/SpO2/steps | ✅ | ✅ |
| Training status/load, readiness, VO2 Max, race predictions, personal records | ❌ | ✅ |

`GARMIN_AUTH_MODE` picks the strategy:

- `auto` (default) — official Personal API when `GARMIN_PERSONAL_API_KEY` is set, else email/password.
- `personal` / `unofficial` — force one backend.
- `hybrid` — run **both**: wellness and raw-file reads go to the official API, Garmin-derived metrics go to email/password, with automatic fallback when a call fails. This is the only mode that returns derived metrics *and* raw `.FIT` files from one process. It needs both credential sets. Tools that need a metric the active backend cannot see return that field as `null` with an `errors` entry explaining why, instead of failing the whole call. Setup and endpoint mapping: [docs/personal-api.md](docs/personal-api.md).

## Features

- **Published on PyPI** — run it with `uvx mcp-garmin-connect`, no clone or manual install.
- **24 Garmin tools and 4 prompt templates** for training and recovery analysis.
- **Two Garmin backends, switchable or combined** — the official [Connect Personal API](docs/personal-api.md) (self-serve key, stable) and the unofficial email/password flow (wider metric coverage). `GARMIN_AUTH_MODE=auto` picks one; `hybrid` runs both and routes each call to the backend that owns the data.
- **Raw activity files** — `download_activity_file` fetches the original `.FIT` (ZIP) through the Personal API.
- **Demo mode** — `serve --demo` runs on fictional sample data with no credentials, for try-outs and recordings.
- **Local MCP server** over `stdio` or Streamable HTTP (`/mcp`).
- **Endpoint-level TTL cache with single-flight factories** — concurrent tool calls share one Garmin request instead of stampeding the API.
- **Global request concurrency cap** so parallel snapshots stay within a safe request rate.
- **Partial-error reporting** — composite tools include an `errors` array when an endpoint fails, instead of silently returning nulls.
- **Provider demo bridge** for `deepseek`, `openai`, `claude`, `openrouter`, and `gemini`.
- **Explicit opt-in** before Garmin health/activity data is sent to any external LLM provider.
- **Mocked test suite** plus optional live Garmin smoke tests.

## Quick Start

### Option A — published package (no clone needed)

```bash
uvx mcp-garmin-connect login
uvx mcp-garmin-connect serve --transport stdio
```

`uvx` runs the latest PyPI release in an isolated environment. Export `GARMIN_EMAIL` / `GARMIN_PASSWORD` (or keep a `.env` in the directory you launch it from) before the first `login`.

### Option B — from source

```bash
git clone https://github.com/kavakoss/mcp-garmin-connect
cd mcp-garmin-connect
uv sync
cp .env.example .env
```

Pick a backend in `.env`:

```env
# Official Personal API (recommended): create a key at
# https://connect.garmin.com/app/settings/personalApiToken
GARMIN_AUTH_MODE=personal
GARMIN_PERSONAL_API_KEY=your-key-here
```

or the unofficial email/password flow:

```env
GARMIN_AUTH_MODE=unofficial
GARMIN_EMAIL=you@example.com
GARMIN_PASSWORD=your-password
```

The unofficial flow needs a one-time interactive login (MFA supported); the
Personal API needs no login step:

```bash
uv run garmin-mcp login                  # unofficial backend only
uv run garmin-mcp personal-api --check   # official backend: token + sample per endpoint
uv run garmin-mcp doctor --live
```

List available MCP tools, then run the server:

```bash
uv run garmin-mcp tools
uv run garmin-mcp serve --transport stdio
```

HTTP transport:

```bash
uv run garmin-mcp serve --transport http --host 127.0.0.1 --port 8765
# clients connect to http://127.0.0.1:8765/mcp
```

> Windows (PowerShell) equivalents: `uv sync`, `Copy-Item .env.example .env`, `notepad .env`, then the same `uv run garmin-mcp ...` commands.

## MCP Client Setup

Generic `stdio` config using the published package (`uvx`):

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uvx",
      "args": ["mcp-garmin-connect", "serve", "--transport", "stdio"],
      "env": {
        "GARMIN_EMAIL": "you@example.com",
        "GARMIN_PASSWORD": "your-password"
      }
    }
  }
}
```

From a local checkout, replace `command`/`args` with:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/mcp-garmin-connect",
        "run",
        "garmin-mcp",
        "serve",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

With the local checkout, credentials are also read from the repo's `.env` file, so the `env` block is optional.

[opencode](https://opencode.ai) (`opencode.json`):

```json
{
  "mcp": {
    "garmin": {
      "type": "local",
      "command": [
        "uv",
        "--directory",
        "/path/to/mcp-garmin-connect",
        "run",
        "garmin-mcp",
        "serve",
        "--transport",
        "stdio"
      ],
      "enabled": true
    }
  }
}
```

Per-client examples (Claude Desktop, Claude Code, Cursor, Continue, Hermes, generic stdio/HTTP) live in [docs/clients](docs/clients/README.md).

## MCP Tools

| Tool | Purpose |
|---|---|
| `get_recovery` | Readiness, HRV, sleep, body battery, resting HR, training status if available |
| `get_sleep` | Sleep duration and sleep score trends |
| `get_resting_heart_rate` | Daily RHR with 7-day and 30-day trend summaries, up to 30 days |
| `get_stress` | Daily stress buckets and average stress |
| `get_recent_activities` | Recent normalized activity summaries |
| `get_activity_detail` | One activity with training effect fields |
| `get_activity_splits` | Per-lap splits with pace, HR, cadence, elevation and HR drift (on the Personal API, rebuilt from the sample stream) |
| `get_recent_load` | Volume by sport based on recent activities |
| `get_training_load` | Native Garmin Training Load when the device/account exposes it |
| `get_fitness` | VO2 Max, FTP, and race predictions |
| `get_zones` | Heart-rate zones and thresholds from Garmin user settings |
| `get_personal_records` | Garmin personal records |
| `get_running_summary` | Running summary with pace, HR, longest and fastest run |
| `get_monthly_running_stats` | Monthly running breakdown |
| `get_hrv_history` | Daily HRV (last-night + weekly average) with a baseline over a longer window |
| `get_body_battery_range` | Daily body battery: charged, drained, highest, lowest, end of day |
| `get_body_composition` | Weight, BMI, body fat/muscle/water from Garmin weight entries — **Personal API only** |
| `get_spo2` | Daily blood oxygen (SpO2) — **Personal API only** |
| `get_hydration` | Logged daily fluid intake in millilitres — **Personal API only** |
| `get_steps_history` | Daily steps versus goal — **Personal API only** |
| `get_fitness_age` | Garmin fitness age versus chronological age — **Personal API only** |
| `download_activity_file` | Original activity file (ZIP with the `.FIT`) written to disk — **Personal API only** |
| `get_health_summary` | Compact recovery, sleep, RHR, and stress snapshot |
| `get_full_snapshot` | Broad multi-section Garmin snapshot; each section carries `data_source` (and `source_detail` when a section needed both backends) |

## Activity windows

`get_recent_activities` accepts either a lookback (`days`) or an explicit window:

```jsonc
{ "days": 30 }                                          // newest 30 days
{ "start_date": "2026-08-01", "end_date": "2026-08-31" } // August 2026 only
```

Both dates are inclusive and `YYYY-MM-DD`; `end_date` defaults to today. Explicit dates win over `days` and make a **past** window queryable without pulling every newer activity first — the pager walks backwards and stops once it reaches `start_date`. The response then includes the resolved `window` so callers can see exactly what was queried. Invalid or reversed dates return an `error` field instead of silently returning everything.

## MCP Prompts

- `recovery_check`
- `weekly_training_review`
- `activity_analysis`
- `race_plan_context`

## Configuration

All settings come from environment variables (`.env` is loaded automatically).

| Variable | Default | Purpose |
|---|---|---|
| `GARMIN_AUTH_MODE` | `auto` | `auto`, `personal` (official API), `unofficial` (email/password) or `hybrid` (both, routed per endpoint) |
| `GARMIN_PERSONAL_API_KEY` | — | Personal API key from [Connect settings](https://connect.garmin.com/app/settings/personalApiToken) — enables the official backend |
| `GARMIN_PERSONAL_TOKEN_CACHE` | `~/.garminconnect/personal_api_token.json` | Where the 24 h bearer token is cached (mode `0600`) |
| `GARMIN_PERSONAL_BASE_URL` | `https://personal.connectapi.garmin.com` | Personal API host override |
| `GARMIN_PERSONAL_TIMEOUT_SECONDS` | `20` | HTTP timeout for Personal API calls |
| `GARMIN_EMAIL` | — | Garmin Connect account email (unofficial backend only) |
| `GARMIN_PASSWORD` | — | Garmin Connect password (unofficial backend only) |
| `GARMIN_TOKEN_STORE` | `~/.garminconnect` | Directory for the OAuth token cache |
| `GARMIN_CACHE_TTL_SECONDS` | `120` | TTL for cached Garmin endpoint responses |
| `GARMIN_MAX_CONCURRENCY` | `6` | Global cap on in-flight Garmin requests |
| `GARMIN_MAX_DAYS_HEALTH` | `30` | Max lookback for `get_sleep` / `get_resting_heart_rate` / `get_stress` / `get_health_summary` |
| `GARMIN_MAX_DAYS_ACTIVITIES` | `365` | Max lookback for activities, training load and running summaries |
| `GARMIN_MAX_ACTIVITY_LIMIT` | `200` | Max activities returned per call (history is paged automatically) |
| `GARMIN_DEMO` | unset | `1` serves fictional sample data (same as `serve --demo`) |

Provider bridge variables (optional): `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, plus the matching `*_BASE_URL` and `*_MODEL` overrides.

## Field units

Garmin's raw payloads mix units, and some fields are named after a unit that Garmin does not actually use (see issue #3: `recoveryTime` is minutes, not hours). This table is the contract — if you add a field, add its row.

Daily arrays (`daily` on the sleep, stress, RHR, HRV and body-battery tools) are **newest-first** — index 0 is the most recent day. Sort client-side if you need chronological order.

| Field | Unit we expose | Garmin raw | Conversion |
|---|---|---|---|
| `duration` | `"h:mm:ss"` | `duration` (seconds) | formatted |
| `duration_min`, `duration_seconds` | minutes / seconds | `duration` (seconds) | `/60` |
| `distance_km`, `total_km`, `total_distance_km` | kilometres | `distance` (metres) | `/1000` |
| `pace_min_km`, `pace_seconds_per_km` | `"m:ss"` / s per km | `averageSpeed` (m/s) | derived |
| `hr_avg`, `hr_max`, `avg_hr`, `min_bpm`, `max_bpm`, `latest_bpm`, `*_avg_bpm` | bpm | `averageHR`, `maxHR`, `restingHeartRate` | – |
| `cadence_spm`, `avg_cadence` | steps per minute | `averageRunningCadenceInStepsPerMinute` | – |
| `avg_power_w`, `normalized_power_w`, `cycling_ftp_w` | watts | `avgPower`, `normPower`, `functionalThresholdPower` | – |
| `elevation_gain_m` | metres | `elevationGain` | assumed metres |
| `total_strokes` | count | `totalNumberOfStrokes` | – |
| `hours`, `avg_hours` | hours | `sleepTimeSeconds` (seconds) | `/3600` |
| `sleep_score`, `score`, `stress_avg`, `max_stress` | 0–100 | `sleepScores.overall`, `avgStressLevel` | – |
| `rest_minutes`, `low_minutes`, `medium_minutes`, `high_minutes`, `activity_minutes` | minutes | `*StressDuration` (seconds) | `/60` |
| `total_minutes`, `total_hours`, `total_duration_hours` | minutes / hours | `duration` (seconds) | derived |
| `last_night_avg_ms`, `weekly_avg_ms`, `hrv_weekly_avg` | milliseconds | `lastNightAvg`, `weeklyAvg`, `hrvWeeklyAverage` | – |
| `recovery_time_hours` | **hours** | `recoveryTime` (**minutes**) | `/60` (issue #3) |
| `body_battery_today.charged` | level | `charged` | – |
| `vo2_max_running`, `vo2_max_cycling` | ml/kg/min | `vo2MaxPreciseValue` | – |
| `race_predictions.*.seconds` | seconds | `time5K`, `time10K`, … | – |
| `drift_pct` | percent | computed from laps | – |
| `records[].value` | **mixed — read `value_unit`** | `value` | see below |
| `records[].value_unit` | `duration` \| `distance_m` \| `elevation_m` \| `watts` \| `steps` \| `days` | derived from the record label | – |

`recovery_time_hours` is only populated when the watch/account provides Training Readiness — a Forerunner 165, for example, returns no readiness data, so the whole `training_readiness` object is `null`. Other tools that lean on it degrade the same way rather than inventing numbers.

## How It Stays Fast And Quiet

- **Endpoint-level cache.** Sleeping, stress, RHR, and activity fetches are cached per day/limit and shared across every tool that needs them — a `get_full_snapshot` burst reuses the same responses instead of refetching.
- **Single-flight.** If two tool calls ask for the same missing key, only one hits Garmin; the other waits and reuses the result.
- **Failures are never cached.** A failed endpoint is retried on the next call.
- **Concurrency cap.** All outbound Garmin calls pass through one bounded semaphore (`GARMIN_MAX_CONCURRENCY`) so parallel sections cannot flood the API.
- **Visible partial failures.** When an optional endpoint fails, composite tools add an `errors` array (source + exception) to their output.

## Provider Demo Agents

Provider API access may require a paid account or credits even if the provider's web app has a free tier.

```env
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
OPENROUTER_API_KEY=sk-or-...
GEMINI_API_KEY=...
```

| Provider | Env key | Default model | API style |
|---|---|---|---|
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-v4-pro` | OpenAI-compatible Chat Completions |
| OpenAI | `OPENAI_API_KEY` | `gpt-5` | OpenAI Chat Completions |
| Claude | `ANTHROPIC_API_KEY` | `claude-sonnet-5` | Anthropic Messages API |
| OpenRouter | `OPENROUTER_API_KEY` | `google/gemini-3-flash-preview` | OpenAI-compatible Chat Completions |
| Gemini | `GEMINI_API_KEY` | `gemini-3.6-flash` | Gemini Generate Content API |

```bash
uv run garmin-mcp ask "How is my recovery today?" --provider deepseek --allow-external-health-data
uv run garmin-mcp ask "Summarize my running for 90 days." --provider openai --allow-external-health-data
uv run garmin-mcp ask "What should I focus on this week?" --provider claude --allow-external-health-data
```

The `--allow-external-health-data` flag is required because Garmin tool results can be sent to the selected provider.

## Privacy And Safety

- Your `.env` file and Garmin token cache stay local and are ignored by git.
- MCP clients that run locally can call Garmin tools without sending provider API keys to this project.
- Provider demo commands such as `garmin-mcp ask` can send Garmin health/activity results to the selected LLM provider, so the CLI requires `--allow-external-health-data`.
- `get_zones` returns only zone/threshold fields from the Garmin profile, not the raw profile (gender, birth date, weight, and similar PII are trimmed).

## Testing

```bash
uv run garmin-mcp doctor
uv run garmin-mcp doctor --live
uv run garmin-mcp tools
uv run ruff check .
uv run pytest
```

CI runs on Linux (Python 3.11, 3.12, 3.13) and Windows (3.12). Optional live tests are gated and never run in CI:

```powershell
$env:GARMIN_LIVE_TEST = "1"
uv run pytest tests/live
```

## Troubleshooting

- **`Garmin rate-limited the request`** — lower `GARMIN_MAX_CONCURRENCY` (for example to `3`) and retry after a few minutes.
- **`Garmin authentication failed`** — check `GARMIN_EMAIL`/`GARMIN_PASSWORD`, then run `uv run garmin-mcp login` from a real terminal (MFA prompts need interactive input).
- **`Garmin rejected the Personal API key`** — keys expire after 30/90/180/365 days. Create a new one at <https://connect.garmin.com/app/settings/personalApiToken>, update `GARMIN_PERSONAL_API_KEY`, then `uv run garmin-mcp personal-api --check`.
- **`personal api required`** — that tool only exists on the official backend. Set `GARMIN_PERSONAL_API_KEY` and `GARMIN_AUTH_MODE=personal` (or `hybrid`).
- **A derived metric is `null` on the personal backend** — training status/load, readiness, VO2 Max, race predictions and personal records are not in Garmin's Personal API. Switch to `GARMIN_AUTH_MODE=unofficial` when you need them.
- **A tool returns `errors`** — the array names the endpoint that failed; the rest of the payload is still valid partial data.

## Garmin Disclaimer

This project uses the community `garminconnect` Python package and Garmin Connect endpoints. Garmin Connect is not a public API for individual open-source projects, and authentication or endpoint behavior may change without notice.

Some metrics depend on Garmin device capabilities. For example, a device may expose VO2 Max and Training Effect but not native Garmin Training Load or Training Status. Zone availability depends on what the Garmin user settings endpoint exposes for your account.

## License

This project is licensed under the [MIT License](LICENSE).

Made by [kavakoss](https://github.com/kavakoss). Inspired by [Jack-Abyss/claude-garmin](https://github.com/Jack-Abyss/claude-garmin), with a clean-room implementation focused on LLM-agnostic MCP usage.
