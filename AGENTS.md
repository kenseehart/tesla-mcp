# Agent onboarding — Tesla Fleet MCP

## Shared resources

Cross-project assets: **`/home/ken/ws/shared`**. Workspace index: **`/home/ken/ws/AGENTS.md`**.

## What this project is

MCP server for the [Tesla Fleet API](https://developer.tesla.com/docs/fleet-api) — **96 tools** for vehicle control, charging, climate, navigation, energy, fleet telemetry.

## Repo

- Path: **`/home/ken/ws/tesla`**
- GitHub: [kenseehart/tesla-mcp](https://github.com/kenseehart/tesla-mcp) — fork of [ysrdevs/tesla-mcp](https://github.com/ysrdevs/tesla-mcp)
- Remotes: `origin` → kenseehart fork, `upstream` → ysrdevs
- Entry points: `tesla_mcp.py` (OAuth, Claude.ai/mobile), `tesla_mcp_apikey.py` (API key)

## Quick start

```bash
cd /home/ken/ws/tesla
cp .env.example .env   # fill Tesla + OAuth credentials
uv sync
uv run tesla-fleet-mcp  # or python tesla_mcp.py
```

## MCP (Cursor)

Registered in `/home/ken/ws/.cursor/mcp.json` as `tesla`. Secrets in `.env` (never commit).

## Remote / phone

OAuth mode syncs to Claude mobile after deploy to my.hosting.com. See **`README.md`** — nginx + systemd sections.

## Key files

| File | Role |
|------|------|
| `tesla_mcp.py` | OAuth MCP server (port 8752) |
| `personal_auth.py` | OAuth helpers |
| `scripts/auth.py` | One-time token setup |

## Conventions

- FastMCP + httpx
- Destructive commands should confirm with user (built into tool descriptions)
