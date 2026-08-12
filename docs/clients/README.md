# MCP Client Setup Examples

These examples show common ways to connect MCP clients to `mcp-garmin-connect`.
Client config formats change over time, so treat them as starting points and adapt
to your client version.

## Recommended: stdio

`stdio` is the safest local transport because it does not open a network port.

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\Users\\Jason\\Documents\\GitHub\\mcp-garmin",
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

## Optional: HTTP

Start the server:

```powershell
uv run garmin-mcp serve --transport http --host 127.0.0.1 --port 8765
```

Then point HTTP-capable clients at:

```text
http://127.0.0.1:8765/mcp
```

## Claude Desktop

Add the `garmin` entry under `mcpServers` in Claude Desktop's config file. Use
the stdio JSON above, then fully restart Claude Desktop.

## Claude Code

Use a local stdio MCP server entry. If configuring manually, use the same command
and args from the stdio example.

## Cursor

Add a custom MCP server using the stdio command. In some Cursor versions this
lives under MCP settings or a project-level MCP config.

## Continue

Use Continue's MCP configuration support and add the stdio command. Keep Garmin
credentials in this repo's local `.env`; do not paste them into client configs.

## Hermes

Use stdio unless you specifically need HTTP:

```yaml
mcp_servers:
  garmin:
    command: "uv"
    args:
      - "--directory"
      - "C:\\Users\\Jason\\Documents\\GitHub\\mcp-garmin"
      - "run"
      - "garmin-mcp"
      - "serve"
      - "--transport"
      - "stdio"
    enabled: true
```

Configure Hermes' LLM provider separately, for example DeepSeek, OpenAI, or
Claude. MCP provides Garmin tools; the LLM provider performs the reasoning.

## Generic Provider Demo

For clients without native MCP support, use the built-in bridge:

```powershell
uv run garmin-mcp ask "How is my recovery today?" --provider deepseek --allow-external-health-data
uv run garmin-mcp ask "How is my recovery today?" --provider openai --allow-external-health-data
uv run garmin-mcp ask "How is my recovery today?" --provider claude --allow-external-health-data
```

The `--allow-external-health-data` flag is required because tool results can send
Garmin health/activity data to the selected provider.
