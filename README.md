# confer

[![CI](https://github.com/dhh1128/confer/actions/workflows/ci.yml/badge.svg)](https://github.com/dhh1128/confer/actions/workflows/ci.yml)

An MCP-mediated channel that lets AI coding agents notify the user on their phone (via Discord DM) when a long-running task finishes or input is needed, and receive a dictated reply.

## Quick start

Prerequisites:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`

From a fresh clone:

```bash
uv sync          # creates .venv, installs confer (editable) + dev dependencies
uv run pytest    # runs the test suite with branch coverage (target: 100%)
```

## Configuration

Copy `.env.example` to `.env` and fill in:

- `DISCORD_BOT_TOKEN` — bot token from [discord.com/developers/applications](https://discord.com/developers/applications).
- `CONFER_USER_ID` — your Discord user snowflake (Settings → Advanced → enable Developer Mode, then right-click your name → Copy User ID).

The bot must share at least one guild with you for it to be able to DM you (Discord's permission rule). A private personal guild containing just you and the bot satisfies this; the guild stays empty — all messaging happens in DMs.

## Running the server

After configuration:

```bash
uv run confer-server          # runs the MCP server on stdio (for use by an MCP client)
```

Point your MCP client (Claude Code, Cursor, etc.) at this command. The server initializes by connecting to the Discord Gateway and waits for the connection to be ready before accepting tool calls.

## Tools exposed

Phase 2A status — only `notify` is implemented; `ask` and `check_messages` are next.

| Tool | Signature | Behavior |
|------|-----------|----------|
| `notify` | `notify(message: str) -> str` | DMs `message` to the configured user. Returns `"sent at <ISO timestamp>"` on success or `"<NOTIFY_FAILED: <reason>>"` on failure (no retries). |

## Where things live

- [`this.i`](this.i) — source of truth for *why* design decisions were made (read this first if you want to understand the project).
- [`docs/methodology.md`](docs/methodology.md) — the intent-driven development discipline in force here.
- [`docs/intent-briefing.md`](docs/intent-briefing.md) — long-form reference for `this.i` format and the broader Intent Layer model.
- [`AGENTS.md`](AGENTS.md) — ground rules for AI assistants working in this repo.
