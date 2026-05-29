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

Copy [`config.toml.example`](config.toml.example) to `~/.config/confer/config.toml` and fill in:

- `discord_bot_token` — bot token from [discord.com/developers/applications](https://discord.com/developers/applications).
- `confer_user_id` — your Discord user snowflake (Settings → Advanced → enable Developer Mode, then right-click your name → Copy User ID).

```bash
mkdir -p ~/.config/confer
cp config.toml.example ~/.config/confer/config.toml
chmod 600 ~/.config/confer/config.toml
# Edit ~/.config/confer/config.toml with your real values.
```

The bot must share at least one guild with you for it to be able to DM you (Discord's permission rule). A private personal guild containing just you and the bot satisfies this; the guild stays empty — all messaging happens in DMs.

## Architecture

confer has two processes:

- **`confer-daemon`** — a long-lived singleton that holds the one Discord Gateway connection and listens on a Unix socket at `$XDG_RUNTIME_DIR/confer.sock` for connections from one-or-more MCP servers. It outlives any individual MCP server (and any individual Claude Code session), so pending state — open `ask` calls, queued check_messages — survives MCP server churn.
- **`confer-server`** — the MCP server, spawned by each Claude Code (or Cursor, etc.) session as a stdio child process. It's a thin shim: it auto-detects an agent label from `{repo}/{branch}`, connects to the daemon (auto-spawning it if it's not already running), and forwards tool calls. Multiple concurrent MCP servers all share the one daemon's Gateway connection.

### Running the MCP server

After configuration, point your MCP client (Claude Code, Cursor, etc.) at:

```bash
uv run confer-server
```

The MCP server will auto-spawn the daemon if it isn't already running. You don't need to start the daemon manually.

### Managing the daemon

```bash
confer-daemon            # run the daemon in the foreground (used by auto-spawn)
confer-daemon status     # show PID, uptime, gateway state, connected MCP servers, log tail
confer-daemon stop       # gracefully terminate the running daemon
```

Logs are written to `$XDG_STATE_HOME/confer/daemon.log` (default `~/.local/state/confer/daemon.log`), rotated at 10 MB with 3 archives kept.

## Tools exposed

All three MCP tools are implemented, plus a user-side `confer` CLI for answering from the laptop. Messages are threaded: each `ask`/`notify` gets a short base32 tag, and the user addresses a thread with `re <tag> …`.

| Tool | Signature | Behavior |
|------|-----------|----------|
| `notify` | `notify(message: str) -> str` | One-way DM to the configured user via the daemon's Discord Gateway. Returns `"sent at <ISO timestamp>"` (with a `(N messages waiting …)` hint if the agent has queued input) or `"<NOTIFY_FAILED: <reason>>"`. Sent as `[<tag>] <label>: <message>`; the auto-derived `repo/branch` label disambiguates concurrent agents, and the tag makes the notify a replyable thread. |
| `ask` | `ask(question, give_up_after_seconds=1800, on_timeout="use_best_judgment"\|"abort") -> str` | Blocks until the user replies (routed back by thread tag) or the give-up window elapses; bounded 1..86400s. Always returns a natural-language string — the reply, or a timeout directive per `on_timeout`. Never raises across the MCP boundary. |
| `check_messages` | `check_messages() -> str` | Drains the agent's queue of unsolicited input (broadcasts, replies to its notify threads, late replies), tagged by source. Consume-on-read. Returns a directive when empty. |

The `confer` CLI (`confer list`, `confer answer "re <tag> …"`) lets the user answer pending asks from the workstation without Discord. See `this.i` for the full design rationale (threading, tags, routing).

## Where things live

- [`this.i`](this.i) — source of truth for *why* design decisions were made (read this first if you want to understand the project).
- [`docs/methodology.md`](docs/methodology.md) — the intent-driven development discipline in force here.
- [`docs/intent-briefing.md`](docs/intent-briefing.md) — long-form reference for `this.i` format and the broader Intent Layer model.
- [`AGENTS.md`](AGENTS.md) — ground rules for AI assistants working in this repo.
