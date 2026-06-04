# confer

[![CI](https://github.com/dhh1128/confer/actions/workflows/ci.yml/badge.svg)](https://github.com/dhh1128/confer/actions/workflows/ci.yml)

An MCP-mediated channel that lets AI coding agents notify the user on their phone (via Discord DM) when a long-running task finishes or input is needed, and receive a dictated reply.

> **Just want to *use* confer?** This README is for contributors. To install it, point your agent at it, and use away mode, see **[docs/usage.md](docs/usage.md)**.

This page is for **developing** confer: getting from a fresh clone to a green test run, understanding the architecture, and knowing the conventions before you contribute.

## Quick start

Prerequisites:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`

From a fresh clone:

```bash
git clone https://github.com/dhh1128/confer
cd confer
uv sync          # creates .venv, installs confer (editable) + dev dependencies
uv run pytest    # runs the default suite with branch coverage (target: 100%)
```

A green `uv run pytest` is your confirmation the checkout is healthy. In this
layout the console scripts run through uv (`uv run confer-server`, `uv run confer`,
etc.) rather than directly on PATH.

## Architecture

confer has two processes:

- **`confer-daemon`** — a long-lived singleton that holds the one Discord Gateway connection and listens on a Unix socket at `$XDG_RUNTIME_DIR/confer.sock` for connections from one-or-more MCP servers. It outlives any individual MCP server (and any individual Claude Code session), so pending state — open `ask` calls, queued check_messages — survives MCP server churn.
- **`confer-server`** — the MCP server, spawned by each Claude Code (or Cursor, etc.) session as a stdio child process. It's a thin shim: it auto-detects an agent label from `{repo}/{branch}`, connects to the daemon (auto-spawning it if it's not already running), and forwards tool calls. Multiple concurrent MCP servers all share the one daemon's Gateway connection.

The user-visible tool contract (`notify` / `ask` / `check_messages`) is documented
in **[docs/usage.md → Tools exposed](docs/usage.md#tools-exposed)**; the *why*
behind the design lives in [`this.i`](this.i).

## Test tiers

The suite has four tiers. A plain `uv run pytest` runs the first two and is the gate that enforces 100% branch coverage; the other two hit real Discord, are coverage-exempt, and are opt-in so a normal run never needs credentials or a human.

| Tier | What it covers | How to run |
|------|----------------|------------|
| **Unit** (default) | All production logic with the discord.py boundary mocked. | `uv run pytest` |
| **Component** (default) | Real daemon + real `serve()` on a real socket talking to a real client, faking only the discord.py transport — proves the process/socket/routing wiring (including inbound DM → `ask`/`check_messages`) end to end, in CI. | `uv run pytest` |
| **Integration** | Live, automatable end-to-end paths against a real bot (notify success + failure, ask timeouts). Borrows your real config creds, spawns an isolated daemon. | `CONFER_INTEGRATION=1 uv run pytest --no-cov -m integration` |
| **Interactive** | Inbound paths that need a human acting in Discord (a reply routed back through `ask`, an unsolicited DM surfacing via `check_messages`). | `uv run pytest --interactive -s --no-cov -m interactive` |

Notes:

- The two opt-in tiers need a working `~/.config/confer/config.toml` (they reuse your real bot identity — see [docs/usage.md → Configuration](docs/usage.md#configuration)); each test skips, rather than fails, when its gate is absent.
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

## Contributing

confer is built with an intent-driven development discipline: the *why* behind
every design decision is recorded in [`this.i`](this.i) **before** the code that
implements it. Strict TDD is in force, with a 100% branch-coverage gate on the
default suite. Before making changes, read:

- [`this.i`](this.i) — source of truth for *why* design decisions were made (read this first if you want to understand the project).
- [`AGENTS.md`](AGENTS.md) — ground rules for working in this repo (human or AI); the authoritative instruction file.
- [`docs/methodology.md`](docs/methodology.md) — the intent-driven development discipline in force here, including the `this.i` update triggers.
- [`docs/intent-briefing.md`](docs/intent-briefing.md) — long-form reference for `this.i` format and the broader Intent Layer model.

## Where things live

- [`src/confer/`](src/confer) — the package: `daemon/` (the singleton: core, routing, transport), `server.py` (MCP shim), `client.py` (daemon IPC client), `cli.py`, `config.py`, `paths.py`, `hooks.py`, `presence.py`, `protocol.py`.
- [`tests/`](tests) — unit + component tiers run by default; [`tests/integration/`](tests/integration) holds the opt-in integration + interactive tiers.
- [`this.i`](this.i), [`docs/`](docs), [`AGENTS.md`](AGENTS.md) — intent, methodology, and contributor ground rules (see [Contributing](#contributing)).
- [`docs/usage.md`](docs/usage.md) — the operator guide (install, configure, run, away mode).
