# confer

[![CI](https://github.com/dhh1128/confer/actions/workflows/ci.yml/badge.svg)](https://github.com/dhh1128/confer/actions/workflows/ci.yml)

An MCP-mediated channel that lets AI coding agents notify the user on their phone (via Discord DM) when a long-running task finishes or input is needed, and receive a dictated reply.

## Install

If you just want to *run* confer (a second dev machine, or a friend you're sharing it with), you don't need to clone the repo or have write access to it — install it straight from the git URL.

Prerequisites:

- [uv](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A Discord bot token and your Discord user id, with the bot sharing at least one guild with you (see [Configuration](#configuration) for how to get these).

Install confer as a uv-managed tool:

```bash
uv tool install git+https://github.com/dhh1128/confer
```

This drops all three console scripts — `confer`, `confer-server`, and `confer-daemon` — onto your PATH in one managed environment. No clone, no editable checkout, no maintainer access required. (A PyPI publish is planned that will shorten this to `uv tool install confer`.)

Then configure and register in one step:

```bash
confer setup
```

`confer setup` scaffolds `~/.config/confer/config.toml` (mode `0600`), prompts for your Discord bot token and user id (or pass `--token` / `--user-id`), and registers the MCP server with Claude Code via `claude mcp add` (skip with `--no-register`). Re-run with `--force` to replace an existing config.

Prefer to do it by hand? See [Configuration](#configuration) for the config file, then register with your MCP client. For Claude Code, MCP servers register in `~/.claude.json` via `claude mcp add`:

```bash
claude mcp add confer -- confer-server
```

Other stdio MCP clients (Cursor, etc.) just point at the `confer-server` command, which is now on your PATH.

The MCP server auto-spawns the daemon (`confer-daemon`) the first time it's needed by resolving it on PATH — you never start the daemon manually.

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

After configuration, point your MCP client (Claude Code, Cursor, etc.) at the `confer-server` command. If you installed via `uv tool install` (see [Install](#install)), that's simply:

```bash
confer-server
```

From a source checkout, run it through uv instead:

```bash
uv run confer-server
```

Either way, the MCP server will auto-spawn the daemon if it isn't already running. You don't need to start the daemon manually.

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

## Development setup

If you're contributing to confer (rather than just running it), work from a clone instead of `uv tool install`.

Prerequisites:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`

From a fresh clone:

```bash
uv sync          # creates .venv, installs confer (editable) + dev dependencies
uv run pytest    # runs the test suite with branch coverage (target: 100%)
```

In this layout the console scripts are run through uv (`uv run confer-server`, `uv run confer`, etc.) rather than directly on PATH.

## Where things live

- [`this.i`](this.i) — source of truth for *why* design decisions were made (read this first if you want to understand the project).
- [`docs/methodology.md`](docs/methodology.md) — the intent-driven development discipline in force here.
- [`docs/intent-briefing.md`](docs/intent-briefing.md) — long-form reference for `this.i` format and the broader Intent Layer model.
- [`AGENTS.md`](AGENTS.md) — ground rules for AI assistants working in this repo.
