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

## Away mode

When you leave your desk, you want every running (and later-opened) Claude Code session to reach you over Discord instead of silently waiting at a terminal — without retyping an instruction in each window. One command, run anywhere, flips that policy globally:

```bash
confer away              # leaving — agents now reach you via confer
confer away --note "back after lunch"
confer back              # back at the keyboard (also happens automatically — see below)
confer presence          # show current state
```

This is enforced by two Claude Code hooks, installed once into `~/.claude`:

```bash
confer install-hooks           # writes the hooks + /away /back slash commands
confer install-hooks --print   # dry run: show what it would change
confer setup --integrations    # or fold it into first-time setup
```

How it works:

- **Presence** is a small file in `$XDG_RUNTIME_DIR` (`confer away` writes it, `confer back` removes it). It's shared across all your sessions and cleared on reboot. No daemon needed.
- A **`Stop` hook** runs when a session would end its turn. If you're away and the agent hasn't already reached out via confer this turn, the hook tells it to use `ask`/`notify` instead of idling. It's loop-safe and **fails open** — anything uncertain (present, unreadable transcript, parse error) lets the session stop normally, so it never wedges an unrelated, non-confer session.
- A **`UserPromptSubmit` hook** clears away mode the moment you type a prompt in *any* session — if you're at a keyboard, you're back, everywhere. Discord replies come back through the confer tools (not the prompt box), so answering from your phone doesn't trip it.

The installer is idempotent and merges into your existing `settings.json` rather than overwriting it. See `this.i` (the AWAY MODE section) for the full rationale, including why presence is a workstation file rather than daemon state.

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

### Test tiers

The suite has four tiers. A plain `uv run pytest` runs the first two and is the gate that enforces 100% branch coverage; the other two hit real Discord, are coverage-exempt, and are opt-in so a normal run never needs credentials or a human.

| Tier | What it covers | How to run |
|------|----------------|------------|
| **Unit** (default) | All production logic with the discord.py boundary mocked. | `uv run pytest` |
| **Component** (default) | Real daemon + real `serve()` on a real socket talking to a real client, faking only the discord.py transport — proves the process/socket/routing wiring (including inbound DM → `ask`/`check_messages`) end to end, in CI. | `uv run pytest` |
| **Integration** | Live, automatable end-to-end paths against a real bot (notify success + failure, ask timeouts). Borrows your real config creds, spawns an isolated daemon. | `CONFER_INTEGRATION=1 uv run pytest --no-cov -m integration` |
| **Interactive** | Inbound paths that need a human acting in Discord (a reply routed back through `ask`, an unsolicited DM surfacing via `check_messages`). | `uv run pytest --interactive -s --no-cov -m interactive` |

Notes:

- Both opt-in tiers need a working `~/.config/confer/config.toml` (they reuse your real bot identity); each test skips, rather than fails, when its gate is absent.
- `--no-cov` is required for the opt-in tiers — a live test exercises only a sliver of the codebase, so the default `--cov-fail-under=100` would otherwise fail the run.
- Interactive tests run serially and each prints an `ACTION REQUIRED` prompt, then wait up to 180s for you to act in Discord — watch the terminal and respond to each as it appears.
- **Integration freshness gate.** Because the integration tier only catches Discord/discord.py API drift on the runs you remember to do, a default-suite test fails if the integration tier hasn't passed in the last ~2 months. It records the last green run in `tests/integration/last-verified.txt` (auto-refreshed when the integration tier passes; or run `python scripts/stamp-integration.py` by hand right after a green run, then commit it). The gate is scoped to a machine that can actually satisfy it — it skips under CI (`CI` env set) and when no real config is present — so it never ambushes contributors without Discord creds.
- See `this.i` (`7vpm2qkx`, `c7nq4xkp`, `5nqx7pmw`, `k4n7pqx2`, `m4xq7npk`, `gjx4m7p2`) for the full rationale behind the tiering.

## Releasing

Releases are cut with `scripts/release.py`, which bumps the version in `pyproject.toml`, runs the test suite, commits (signed off), and pushes a `v<x.y.z>` tag. That tag triggers [`publish.yml`](.github/workflows/publish.yml), which builds and publishes confer to PyPI via trusted publishing.

```bash
python scripts/release.py                       # patch bump, default message
python scripts/release.py --minor -m "new tool" # minor bump
python scripts/release.py --major -m "rewrite"  # major bump
python scripts/release.py --set 0.2.0 -m "..."  # set an explicit version
```

Before running, the script refuses to proceed unless you're on `main`, the working tree is clean, and local `main` is in sync with `origin/main`; it then runs `uv run pytest` (which enforces 100% branch coverage) and only tags if that passes. Running the command is the release authorization — there is no extra confirmation prompt.

**First release prerequisites (one-time, outward-facing — see [`publish.yml`](.github/workflows/publish.yml)):** confirm the `confer` name is available on PyPI, configure the PyPI trusted publisher for this repo + the `pypi` environment, and decide on a license (`pyproject.toml` has no `license` declared yet). The publish job will fail until these are done.

## Where things live

- [`this.i`](this.i) — source of truth for *why* design decisions were made (read this first if you want to understand the project).
- [`docs/methodology.md`](docs/methodology.md) — the intent-driven development discipline in force here.
- [`docs/intent-briefing.md`](docs/intent-briefing.md) — long-form reference for `this.i` format and the broader Intent Layer model.
- [`AGENTS.md`](AGENTS.md) — ground rules for AI assistants working in this repo.
