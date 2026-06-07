# Using confer

This is the guide for **running** confer — installing it, pointing your AI coding
agent at it, and reaching your agents from your phone over Discord. If you want to
**develop or contribute to** confer, see [`README.md`](../README.md) instead.

confer is an MCP-mediated channel that lets AI coding agents notify you on your
phone (via Discord DM) when a long-running task finishes or needs input, and
receive a dictated reply.

## Install

You don't need to clone the repo or have write access to it — install it straight
from the git URL.

Prerequisites:

- [uv](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A Discord bot token and your Discord user id, with the bot sharing at least one guild with you (see [Configuration](#configuration) for how to get these).

Install confer as a uv-managed tool:

```bash
uv tool install git+https://github.com/dhh1128/confer
```

This drops all three console scripts — `confer`, `confer-server`, and
`confer-daemon` — onto your PATH in one managed environment. No clone, no editable
checkout, no maintainer access required. (PyPI publishing is currently disabled
and not owner-authorized — see `this.i` `pn7qvk4x`; install from the git URL or
a local checkout.)

Then configure and register in one step:

```bash
confer setup
```

`confer setup` scaffolds `~/.config/confer/config.toml` (mode `0600`), prompts for
your Discord bot token and user id (or pass `--token` / `--user-id`), and registers
the MCP server with Claude Code via `claude mcp add` (skip with `--no-register`).
Re-run with `--force` to replace an existing config.

Prefer to do it by hand? See [Configuration](#configuration) for the config file,
then register with your MCP client. For Claude Code, MCP servers register in
`~/.claude.json` via `claude mcp add`:

```bash
claude mcp add confer -- confer-server
```

Other stdio MCP clients (Cursor, etc.) just point at the `confer-server` command,
which is now on your PATH.

The MCP server auto-spawns the daemon (`confer-daemon`) the first time it's needed
by resolving it on PATH — you never start the daemon manually.

## Configuration

Copy [`config.toml.example`](../config.toml.example) to
`~/.config/confer/config.toml` and fill in:

- `discord_bot_token` — bot token from [discord.com/developers/applications](https://discord.com/developers/applications).
- `confer_user_id` — your Discord user snowflake (Settings → Advanced → enable Developer Mode, then right-click your name → Copy User ID).

```bash
mkdir -p ~/.config/confer
cp config.toml.example ~/.config/confer/config.toml
chmod 600 ~/.config/confer/config.toml
# Edit ~/.config/confer/config.toml with your real values.
```

The bot must share at least one guild with you for it to be able to DM you
(Discord's permission rule). A private personal guild containing just you and the
bot satisfies this; the guild stays empty — all messaging happens in DMs.

## Running the MCP server

After configuration, point your MCP client (Claude Code, Cursor, etc.) at the
`confer-server` command. If you installed via `uv tool install` (see
[Install](#install)), that's simply:

```bash
confer-server
```

The MCP server will auto-spawn the daemon if it isn't already running. You don't
need to start the daemon manually.

## Managing the daemon

```bash
confer-daemon            # run the daemon in the foreground (used by auto-spawn)
confer-daemon status     # show PID, uptime, gateway state, connected MCP servers, log tail
confer-daemon stop       # gracefully terminate the running daemon
```

Logs are written to `$XDG_STATE_HOME/confer/daemon.log` (default
`~/.local/state/confer/daemon.log`), rotated at 10 MB with 3 archives kept.

## Tools exposed

All three MCP tools are implemented, plus a user-side `confer` CLI for answering
from the laptop. Messages are threaded: each `ask`/`notify` gets a short base32
tag, and you address a thread with `re <tag> …`.

| Tool | Signature | Behavior |
|------|-----------|----------|
| `notify` | `notify(message: str) -> str` | One-way DM to the configured user via the daemon's Discord Gateway. Returns `"sent at <ISO timestamp>"` (with a `(N messages waiting …)` hint if the agent has queued input) or `"<NOTIFY_FAILED: <reason>>"`. Sent as `[<tag>] <label>: <message>`; the auto-derived `repo/branch` label disambiguates concurrent agents, and the tag makes the notify a replyable thread. |
| `ask` | `ask(question, give_up_after_seconds=1800, on_timeout="use_best_judgment"\|"abort") -> str` | Blocks until the user replies (routed back by thread tag) or the give-up window elapses; bounded 1..86400s. Always returns a natural-language string — the reply, or a timeout directive per `on_timeout`. Never raises across the MCP boundary. |
| `check_messages` | `check_messages() -> str` | Drains the agent's queue of unsolicited input (broadcasts, replies to its notify threads, late replies), tagged by source. Consume-on-read. Returns a directive when empty. |

The `confer` CLI (`confer list`, `confer answer "re <tag> …"`) lets you answer
pending asks from the workstation without Discord. See [`this.i`](../this.i) for the
full design rationale (threading, tags, routing).

## Away mode

When you leave your desk, you want every running (and later-opened) Claude Code
session to reach you over Discord instead of silently waiting at a terminal —
without retyping an instruction in each window. One command, run anywhere, flips
that policy globally:

```bash
confer away              # leaving now — agents reach you via confer
confer away --note "back after lunch"
confer back              # back at the keyboard (also happens automatically — see below)
confer status            # show current state + any scheduled aways
```

### Scheduling away in advance

You can arm away mode for a future time — handy when you know a meeting is
coming but want to keep working until then. A keyboard prompt makes you present
*now* but does **not** cancel a future scheduled away, so you can schedule first
and keep typing:

```bash
confer away in 5         # go away 5 minutes from now
confer away at 1100      # go away at 11:00 (24-hour; past time means tomorrow)
confer away at 1400 --note "design review"
```

Scheduling is ephemeral and capped at 24 hours ahead (a time already past today
is interpreted as tomorrow, which keeps everything within the window). It does
not survive a reboot. Manage the schedule with:

```bash
confer status            # list current state + every pending away
confer back at 1100      # cancel just the 11:00 scheduled away
confer back all          # clear current away AND every scheduled away
confer back              # become present now; future scheduled aways are kept
```

When a scheduled away activates, the daemon DMs you **"Now in away mode"** (with
your note) — your confirmation that it engaged. That confirmation needs the
daemon running at that moment; away *enforcement* itself does not (it's a file
the Stop hook reads), so away still engages even if the daemon is down — you
just won't get the buzz.

The same forms work as slash commands inside Claude Code: `/away at 1100`,
`/back all`, etc. (There is no `/status` — if you're typing in Claude you're at
the keyboard and already present; `confer status` is for checking from a
terminal while you're away.)

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

The installer is idempotent and merges into your existing `settings.json` rather
than overwriting it. See [`this.i`](../this.i) (the AWAY MODE section) for the full
rationale, including why presence is a workstation file rather than daemon state.
