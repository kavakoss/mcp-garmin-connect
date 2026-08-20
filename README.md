# mcp-garmin-connect

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-compatible-6D28D9)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/kavakoss/mcp-garmin-connect/actions/workflows/ci.yml/badge.svg)](https://github.com/kavakoss/mcp-garmin-connect/actions/workflows/ci.yml)
[![Top Language](https://img.shields.io/github/languages/top/kavakoss/mcp-garmin-connect)](https://github.com/kavakoss/mcp-garmin-connect)

LLM-agnostic Garmin Connect MCP server for training, recovery, sleep, stress, VO2 Max, race predictions, and running summaries.

Use the same local Garmin tools from MCP clients such as Claude Desktop, Claude Code, Cursor, Continue, Hermes, or from provider-backed demo agents using DeepSeek, OpenAI, or Claude API.

## Why This Exists

Most fitness advice from LLMs is generic. This server lets an LLM inspect your real Garmin Connect data first, then answer with context from your activities, recovery markers, HRV, sleep, stress, VO2 Max, and running history.

The core server is provider-neutral. DeepSeek, OpenAI, and Claude integrations are optional demo bridges for clients that do not speak MCP directly.

## Features

- Local MCP server for Garmin Connect over `stdio` or Streamable HTTP.
- 14 Garmin tools and 4 prompt templates.
- Provider demo bridge for `deepseek`, `openai`, `claude`, `openrouter`, and `gemini`.
- Windows-first CLI, with cross-platform Python project structure.
- Explicit opt-in before Garmin health/activity data is sent to any external LLM provider.
- Mocked test suite plus optional live Garmin smoke tests.

## Languages And Stack

| Area | Technology |
|---|---|
| Main language | Python 3.11+ |
| Package manager | uv |
| MCP server | `mcp` Python SDK / FastMCP |
| Garmin access | `garminconnect` |
| Provider API calls | `httpx` |
| Tests | pytest |
| Linting | ruff |
| Client config examples | JSON, YAML, PowerShell |

## Quick Start

```powershell
uv sync
Copy-Item .env.example .env
notepad .env
```

Set Garmin credentials:

```env
GARMIN_EMAIL=you@example.com
GARMIN_PASSWORD=your-password
```

Authenticate once:

```powershell
uv run garmin-mcp login
uv run garmin-mcp doctor --live
```

List available MCP tools:

```powershell
uv run garmin-mcp tools
```

Run as a local MCP server:

```powershell
uv run garmin-mcp serve --transport stdio
```

Run as an HTTP MCP server:

```powershell
uv run garmin-mcp serve --transport http --host 127.0.0.1 --port 8765
```

HTTP clients can connect to:

```text
http://127.0.0.1:8765/mcp
```

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

Ask through a provider bridge:

```powershell
uv run garmin-mcp ask "How is my recovery today?" --provider deepseek --allow-external-health-data
uv run garmin-mcp ask "Summarize my running for 90 days." --provider openai --allow-external-health-data
uv run garmin-mcp ask "What should I focus on this week?" --provider claude --allow-external-health-data
uv run garmin-mcp ask "Summarize my monthly running." --provider openrouter --allow-external-health-data
uv run garmin-mcp ask "Check my fitness trend." --provider gemini --allow-external-health-data
```

The `--allow-external-health-data` flag is required because Garmin tool results can be sent to the selected provider.

## MCP Tools

| Tool | Purpose |
|---|---|
| `get_recovery` | Readiness, HRV, sleep, body battery, resting HR, training status if available |
| `get_sleep` | Sleep duration and sleep score trends |
| `get_resting_heart_rate` | Daily RHR with 7-day and 30-day trend summaries |
| `get_stress` | Daily stress buckets and average stress |
| `get_recent_activities` | Recent normalized activity summaries |
| `get_activity_detail` | One activity with training effect fields |
| `get_recent_load` | Volume by sport based on recent activities |
| `get_training_load` | Native Garmin Training Load when the device/account exposes it |
| `get_fitness` | VO2 Max, FTP, and race predictions |
| `get_zones` | Heart-rate and power zones when available |
| `get_personal_records` | Garmin personal records |
| `get_running_summary` | 90-day running summary with pace, HR, longest and fastest run |
| `get_monthly_running_stats` | Monthly running breakdown |
| `get_health_summary` | Compact recovery, sleep, RHR, and stress snapshot |
| `get_full_snapshot` | Broad multi-section Garmin snapshot |

## MCP Prompts

- `recovery_check`
- `weekly_training_review`
- `activity_analysis`
- `race_plan_context`

## Client Setup

See [docs/clients](docs/clients/README.md) for examples covering:

- Claude Desktop
- Claude Code
- Cursor
- Continue
- Hermes
- Generic stdio MCP clients
- Generic HTTP MCP clients

Minimal stdio config:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\mcp-garmin-connect",
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

## Testing

```powershell
uv run garmin-mcp doctor
uv run garmin-mcp doctor --live
uv run garmin-mcp tools
uv run ruff check .
uv run pytest
```

Optional live tests are gated and do not run in CI by default:

```powershell
$env:GARMIN_LIVE_TEST = "1"
uv run pytest tests/live
```

Current local validation target:

```text
ruff: All checks passed
pytest: all mocked tests pass, live test skipped unless enabled
```

## Privacy And Safety

Your `.env` file and Garmin token cache stay local and are ignored by git.

MCP clients that run locally can call Garmin tools without sending provider API keys to this project. Provider demo commands such as `garmin-mcp ask` can send Garmin health/activity results to the selected LLM provider, so the CLI requires `--allow-external-health-data`.

## Garmin Disclaimer

This project uses the community `garminconnect` Python package and Garmin Connect endpoints. Garmin Connect is not a public API for individual open-source projects, and authentication or endpoint behavior may change without notice.

Some metrics depend on Garmin device capabilities. For example, a device may expose VO2 Max and Training Effect but not native Garmin Training Load or Training Status.

## Star History

<a href="https://www.star-history.com/?repos=kavakoss%2Fmcp-garmin-connect&type=date&legend=top-left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=kavakoss/mcp-garmin-connect&type=date&theme=dark&legend=top-left&sealed_token=jWwCP1aKpJ82FKqcEEP2UnyXxxIF8WVj4b0NmJGkZDR5Iujd8WmJ43JHjxO4epA5RTFxdG-30WvZcDNhA31RsI3lKr8R1056ExLsKXwknwg1YhFvCGqR1PffqsTOp-s8HNBovtGPGdPAQIbXZEe0YHGaNj3JZ2eWrOBHcBgwa6MVkqHgHzkSMc6EM4En" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=kavakoss/mcp-garmin-connect&type=date&legend=top-left&sealed_token=jWwCP1aKpJ82FKqcEEP2UnyXxxIF8WVj4b0NmJGkZDR5Iujd8WmJ43JHjxO4epA5RTFxdG-30WvZcDNhA31RsI3lKr8R1056ExLsKXwknwg1YhFvCGqR1PffqsTOp-s8HNBovtGPGdPAQIbXZEe0YHGaNj3JZ2eWrOBHcBgwa6MVkqHgHzkSMc6EM4En" />
    <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=kavakoss/mcp-garmin-connect&type=date&legend=top-left&sealed_token=jWwCP1aKpJ82FKqcEEP2UnyXxxIF8WVj4b0NmJGkZDR5Iujd8WmJ43JHjxO4epA5RTFxdG-30WvZcDNhA31RsI3lKr8R1056ExLsKXwknwg1YhFvCGqR1PffqsTOp-s8HNBovtGPGdPAQIbXZEe0YHGaNj3JZ2eWrOBHcBgwa6MVkqHgHzkSMc6EM4En" />
  </picture>
</a>

## License

This project is licensed under the [MIT License](LICENSE).

## Publish

Codex does not push this repo. To publish it yourself:

```powershell
git remote add origin https://github.com/kavakoss/mcp-garmin-connect.git
git push -u origin main
```

---

Made by [kavakoss](https://github.com/kavakoss).

Inspired by [Jack-Abyss/claude-garmin](https://github.com/Jack-Abyss/claude-garmin), with a clean-room implementation focused on LLM-agnostic MCP usage.
