# mcp-garmin-connect

LLM-agnostic MCP server for Garmin Connect data, with optional provider demo agents.

This project exposes your Garmin Connect data as Model Context Protocol tools so any MCP-capable client can reason over your real training, recovery, sleep, stress, and activity data. It is not tied to Claude. Claude Desktop, Claude Code, Cursor, local agents, and provider-specific tool-calling demos can all sit on top of the same MCP server.

Provider integrations are intentionally demo agents, not part of the core Garmin server. They prove that provider API keys can drive the MCP tools through a small bridge.

## Status

Early v1 scaffold. The project is Windows CLI-first and clean-room inspired by [`Jack-Abyss/claude-garmin`](https://github.com/Jack-Abyss/claude-garmin), but does not copy its code.

## Install

```powershell
uv sync
Copy-Item .env.example .env
notepad .env
```

Set at least:

```env
GARMIN_EMAIL=you@example.com
GARMIN_PASSWORD=your-password
```

For optional provider demos:

```env
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

## CLI

```powershell
uv run garmin-mcp login
uv run garmin-mcp doctor
uv run garmin-mcp tools
uv run garmin-mcp serve --transport stdio
uv run garmin-mcp serve --transport http --host 127.0.0.1 --port 8765
uv run garmin-mcp ask "How is my recovery today?" --provider deepseek --allow-external-health-data
uv run garmin-mcp ask "How is my recovery today?" --provider openai --allow-external-health-data
uv run garmin-mcp ask "How is my recovery today?" --provider claude --allow-external-health-data
```

`ask` can send Garmin health/activity tool results to the selected LLM provider. The
`--allow-external-health-data` flag is intentionally required so this never happens by accident.

Provider API access may require a paid account or credits even if the provider's web app offers a free tier.

## Provider Matrix

| Provider | Env key | Default model | Notes |
|---|---|---|---|
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-v4-pro` | OpenAI-compatible Chat Completions API |
| OpenAI | `OPENAI_API_KEY` | `gpt-5` | OpenAI-compatible Chat Completions API |
| Claude | `ANTHROPIC_API_KEY` | `claude-sonnet-5` | Anthropic Messages API via `httpx` |

Override defaults with `--model`, or env vars such as `OPENAI_MODEL`, `ANTHROPIC_MODEL`, and `DEEPSEEK_MODEL`.

## MCP Tools

- `get_recovery`
- `get_sleep`
- `get_stress`
- `get_recent_activities`
- `get_activity_detail`
- `get_recent_load`
- `get_training_load`
- `get_fitness`
- `get_zones`
- `get_personal_records`
- `get_health_summary`
- `get_full_snapshot`
- `get_running_summary`
- `get_monthly_running_stats`

## MCP Prompts

- `recovery_check`
- `weekly_training_review`
- `activity_analysis`
- `race_plan_context`

## Garmin Disclaimer

This project uses the community `garminconnect` Python package and Garmin Connect endpoints. Garmin Connect is not a public API for individual open-source projects, and authentication or endpoint behavior may change without notice. Keep request volume low, use the data for personal workflows, and understand that live Garmin access may break when Garmin changes its services.

Your `.env` file and Garmin token cache stay local and are ignored by git.

## Client Setup

See [docs/clients](docs/clients/README.md) for MCP stdio/HTTP examples for Claude Desktop, Claude Code, Cursor, Continue, Hermes, and generic clients.

## Development

```powershell
uv sync --group dev
uv run ruff check .
uv run pytest
```

Optional live tests are gated by environment variables and should never run in CI by default:

```powershell
$env:GARMIN_LIVE_TEST = "1"
uv run pytest tests/live
```

## License

MIT

## Publish

Codex does not push this repo. To publish it yourself:

```powershell
git remote add origin https://github.com/<you>/mcp-garmin-connect.git
git push -u origin main
```
