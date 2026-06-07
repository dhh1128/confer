# confer intent file
# Component: confer — MCP-mediated agent-to-human notification system via Discord
# Format: intent code — YAML nodes named as trees of key: value pairs.
#   goal:       — a desired outcome or quality attribute.
#   decision:   — an architectural choice between identified alternatives.
#   constraint: — a non-negotiable boundary condition.
#   deviation:  — an approved gap from a project standard (child of the standard).
#   tension:    — an open question or conflict; do not resolve silently.
#   Each node carries id: (opaque base32, 6-12 chars) and why: (rebuttal-surface rationale).
# Note: tightening is manual; IDs are assigned by hand; no propagation tooling.
# Seed: 2026-05-27 from initial speculative interview with daniel.
#       All decisions below are pre-implementation; no code exists yet.

Confer = goal:
  id: k7m3pq2x
  why: >
    Provide an MCP-mediated channel so AI coding agents can notify the user
    on their phone (via Discord DM) when a long-running task finishes or input
    is needed, and can receive the user's dictated reply. Built in-house rather
    than using Claude Code's experimental remote-notification feature because
    that feature requires Anthropic telemetry that violates daniel's employer's
    AI-safety policy. WSL2 environment rules out OS-native notification
    mechanisms on the workstation side, so an external channel is required
    anyway. Target: 2-3 min notification latency in the common case; tolerant
    of waits up to several hours when the user is away.

  children:

    # ─── METHODOLOGY ─────────────────────────────────────────────────────────

    Adopt Intent-Driven Methodology = decision:
      id: 4bzx7ndm
      why: >
        Adopt the intent-driven methodology from origin-platform (this.i,
        speculative interview, rebuttal-surface why fields, gate ceremony,
        adversarial review) over an ad-hoc README + commit-message
        documentation style. Even though confer is a small personal project,
        AI-assisted development is the primary mode of work and the methodology
        specifically addresses the comprehension-illusion failure mode that
        makes AI-generated code's rationale hard to reconstruct later. The
        overhead is moderate; the alternative is design rationale that drifts
        the moment the next session starts. The methodology brief and
        intent-briefing reference are imported into docs/ as evidence; the
        Java/Maven idioms in methodology.md are replaced with Python/pytest
        equivalents (see Stack Selection), and the Jira tech-debt integration
        from §8 is dropped (project does not use Jira).
      approved-by: daniel, 2026-05-27

    # ─── DESIGN STANCE ───────────────────────────────────────────────────────

    Productivity While Away = goal:
      id: pn4xvk2m
      why: >
        Confer's primary value is keeping AI coding agents productive while
        daniel is away from his workstation. The user→agent direction (notify,
        ask blocking on user input) is the load-bearing path. Daniel is
        responsive on phone via Discord when away, and at the laptop locally
        (outside confer's reach) when present. This goal narrows the design
        space: scenarios that fall outside it — preserving agent-conversation
        state across agent failure, real-time co-presence at the laptop,
        multi-user collaboration — are explicitly not in scope, and decisions
        should not pay complexity costs to support them. Recorded at the start
        of phase 2C as the parent intention from which several specific
        decisions derive (Asymmetric Robustness, Spokesperson Abstraction
        Principle, Minimal Agent Surface Operator Config, Natural Language
        Outcomes, Acknowledge Actionable State Changes).
      approved-by: daniel, 2026-05-28

    Asymmetric Robustness = decision:
      id: wq7knm3p
      why: >
        Stance derivative of Productivity While Away (pn4xvk2m). The daemon
        survives agent churn — dozens of MCP servers per day, started and
        killed without warning — while keeping the Discord side sane. The
        reverse direction is deliberately not symmetrical: the daemon does not
        preserve agent-conversation state across agent failure. If an agent
        dies with an outstanding ask, the user is told once and the question
        is dropped; daniel restarts the agent locally and either re-asks or
        proceeds without the missing answer. Considered preserving in-flight
        asks across MCP-server restarts (carry the question over to the next
        same-label agent via check_messages): rejected because the new agent
        process didn't ask the question and has no awaiter to resume, the
        preservation contradicts Productivity While Away (daniel is the
        fallback, not the daemon), and the complexity is real while the value
        is hypothetical. Operationalized in Orphan Ask Drop Policy (v4kn7mpq),
        ASK_CANCEL Protocol (3mq7pvxn), and Check Messages Queue Scaffolding
        (7nvpkqm3).
      approved-by: daniel, 2026-05-28

    Spokesperson Abstraction Principle = decision:
      id: vj4xqn7p
      why: >
        Stance derivative of Productivity While Away (pn4xvk2m). The
        MCP-facing surface treats confer as an opaque spokesperson that
        returns answers on the user's behalf. The MCP server makes no
        assumption about how the answer is produced — Discord today, a future
        policy engine, a secondary user-owned agent, a local CLI injection,
        or any other channel the daemon comes to support. Operationalized in
        (a) tool docstring framing (the agent is told it is asking confer,
        not "DMing the user"), (b) directive text on timeout (neutral "no
        answer was received within the requested window"), (c) daemon
        dispatcher input shape (replies arrive as (label, content) with no
        source-channel branding). Considered baking Discord-as-channel into
        the MCP layer for simplicity: rejected because any later channel
        would require revisiting every user-facing string and the protocol's
        mental model. The encapsulation cost is small now; unwinding the
        assumption later would be substantial.
      approved-by: daniel, 2026-05-28

    Minimal Agent Surface Operator Config = decision:
      id: mk7npq4x
      why: >
        Stance derivative of Productivity While Away (pn4xvk2m). The MCP tool
        surface exposes only the levers that meaningfully affect an agent's
        specific call — the question text, how long to wait, what fallback to
        apply on timeout. Cadence of re-pings, hard caps on wait duration,
        queue size bounds, retention windows, and similar concerns are
        operator-side and live in ~/.config/confer/config.toml. Considered
        exposing re-ping interval, wait cap, and queue behavior as MCP
        parameters: rejected because the agent does not have meaningful
        context to set these per call, every additional knob is one more
        thing the tool description has to teach, and operator-level tunables
        can be adjusted without redeploying agents. Bounds (e.g.,
        give_up_after_seconds ≤ 86400) are enforced at the API surface via
        Pydantic so the agent receives a clear schema error rather than a
        runtime sentinel.
      approved-by: daniel, 2026-05-28

    Natural Language Outcomes = decision:
      id: xj4nqv7m
      why: >
        Stance derivative of Productivity While Away (pn4xvk2m). Every string
        the agent receives from an ask or notify call reads as English the
        agent's reasoning naturally handles. No opaque sentinel tokens whose
        meaning the system prompt has to teach. Timeout outcomes, cancellation
        outcomes, and daemon-disconnection outcomes are natural-language
        directives in spokesperson voice ("No answer was received within the
        requested window. Follow your existing instructions or your best
        judgment about how to proceed."). Originally drafted as opaque
        sentinels (<NO_RESPONSE_USE_BEST_JUDGMENT>); revised because sentinels
        require special vocabulary the agent has to learn before the call can
        produce meaningful behavior, while directives are self-explanatory
        and cross the boundary as ordinary prose. Operationalizes Sentinel
        Returns Not Exceptions (nx2pj4wq).
      approved-by: daniel, 2026-05-28

    Acknowledge Actionable State Changes = decision:
      id: qn7pkm4v
      why: >
        Stance derivative of Productivity While Away (pn4xvk2m). Every
        transition that changes whether a question is answerable produces a
        brief Discord DM to the user: timeout (with disposition), cancellation
        (question withdrawn), agent disconnect (lost contact). Beyond these
        moments, Discord-side noise is minimized: re-pings are short, no
        unsolicited status updates, no decorative footers when only one ask
        is pending. Considered silent transitions (the user discovers state
        only on the next interaction): rejected because Productivity While
        Away makes the asynchronous Discord channel the user's only window
        into agent state — silent transitions strand the user mid-dictation.
        Considered chattier updates (periodic status DMs): rejected as noise
        without action-relevance. Operationalized in Ask Closing Notifications
        (pkn7mvq4), the re-ping behavior in Wait Behavior Re-Pings
        (hj7m4qbx), and the Reply Routing Footer (xqp4nv7m).
      approved-by: daniel, 2026-05-28

    # ─── STACK & STANDARDS ───────────────────────────────────────────────────

    Stack Selection = decision:
      id: w3f5qkc2
      why: >
        Python 3.12+ via uv (Astral) as project/environment manager; pytest
        as test runner; pytest-cov for coverage. Considered plain python -m
        venv + pip + requirements.txt: works, but more boilerplate and slower
        CI installs. Considered poetry: more mature but slower than uv, and
        uv's lockfile-first model is closer to modern Python practice.
        uv picked for: single-binary toolchain (no separate pip/venv/pyenv),
        ~10x faster install, reproducible lockfile by default. Python (vs Node
        or Go) because the MCP Python SDK is the most mature MCP server SDK
        and discord.py is the de facto Discord client in Python.

    100% Branch Coverage = constraint:
      id: 7hp2nqkb
      why: >
        All production code under coverage measurement must achieve 100%
        branch coverage (pytest --cov-branch). Considered statement-only
        coverage: cheaper but lets short-circuit evaluation and exception
        branches go untested, which is exactly where bugs hide. 100% is
        achievable on a small project and forces every branch into the test
        plan during the speculative interview phase. Approved deviations
        document explicit exceptions.

      children:

        Integration Tests Exempt = deviation:
          id: gjx4m7p2
          deviates-from: 7hp2nqkb
          scope: >
            Tests in the integration tier (gated behind the CONFER_INTEGRATION=1
            env var) AND the interactive tier (gated behind --interactive,
            Interactive Human-In-The-Loop Test Tier k4n7pqx2) are not included
            in coverage measurement. The 100% branch target applies only to
            unit tests of production code with the discord.py boundary mocked.
            Mechanics: --cov-fail-under=100 lives in addopts and so applies to
            every run; because a live test exercises only a sliver of code, the
            opt-in tiers are run with an explicit --no-cov flag (which reliably
            overrides addopts coverage) so the run exits 0 instead of tripping
            the gate. Programmatic auto-disable from a conftest hook was tried
            and abandoned — pytest-cov reads its options too early for a hook to
            override, and an explicit flag is more transparent anyway. The
            canonical coverage gate is the plain `uv run pytest` with neither
            opt-in active.
          why: >
            Integration tests against the live Discord API are non-reproducible
            (network dependency, real bot tokens, rate limits, eventual
            consistency on message arrival). Gating coverage on them would
            either make CI flaky or force them to always run, which is hostile
            to anyone (including future-daniel) without test credentials.
            Mocked unit tests can and must reach 100%.
          approved-by: daniel, 2026-05-27

    # ─── TRANSPORT & SERVER ARCHITECTURE ─────────────────────────────────────

    MCP Stdio Transport = decision:
      id: 5tnq3wkr
      why: >
        The MCP server runs as a stdio child process spawned by the MCP client
        (Claude Code, Cursor, etc.). Considered HTTP/SSE transport: required
        for multi-client or remote setups; confer is a personal local tool
        with no multi-client or remote-access requirement. Stdio matches the
        MCP SDK's default pattern and the agent client's process model —
        when the agent client exits, the server exits cleanly with it.

    Discord DM Channel = decision:
      id: 2vfp7mxq
      why: >
        The bot sends messages to the user via Discord DM, not via posts in
        a guild channel. Considered private guild + dedicated channel: gives
        nicer history UI (channel scrollback), but Discord's mobile client
        foregrounds DMs more prominently and dictation works identically in
        either context. DMs picked for: (1) single inbox for the user, (2)
        no channel-management ceremony, (3) the personal guild exists only
        to satisfy Discord's bot-DM permission rule (a bot can DM a user only
        if they share at least one guild) and otherwise stays empty.

    Persistent Gateway Connection = decision:
      id: bn4qj7wc
      why: >
        The MCP server opens one Discord Gateway websocket connection at
        startup and holds it for the entire process lifetime. Considered
        spin-up-per-ask: attractive for statelessness, but breaks down for
        long waits — daniel confirmed realistic timelines run to 3+ hours,
        which would impose repeated connect/identify handshake cost, idle
        disconnect handling, and rate-limit pressure per ask call. Persistent
        connection is what discord.py's Client class is built around and
        makes ask of any duration free of reconnection overhead. Tradeoff:
        if the MCP server process dies mid-ask, the connection closes and
        the pending reply has nowhere to go — see tension
        Pending Ask Lost On MCP Server Death. (The Gateway connection now
        lives in the daemon per Central Daemon Architecture, dq7n3xpk; this
        decision still describes the connection model, but its owning
        process changed.)

    Bot Token In .env = decision:
      id: pq3xnk5m
      why: >
        Discord bot token lives in a .env file in the repo root, loaded at
        server startup via python-dotenv. .env is in .gitignore. Considered
        OS keyring: cross-platform Python keyring library exists but adds a
        dependency and per-platform configuration friction (Windows Credential
        Manager vs macOS Keychain vs Linux Secret Service); not justified for
        a single-user personal tool. Considered shell env only: fragile —
        easy to forget when restarting the agent client. .env is the Python
        ecosystem default and survives shell restarts. (Library choice
        refined in Settings Via Pydantic Settings, 5qx2wkpn. SUPERSEDED in
        phase 2B by Global Config In ~/.config/confer/config.toml, hq7x3npm:
        the daemon is a global singleton, so per-project credentials no
        longer make sense.)

    Settings Via Pydantic Settings = decision:
      id: 5qx2wkpn
      why: >
        Configuration is loaded via pydantic-settings's BaseSettings, sourcing
        from a .env file at the repo root (built-in env_file support).
        Required fields for v1: discord_bot_token (str), confer_user_id
        (int — Discord snowflake). This refines the library choice that was
        speculative in Bot Token In .env (pq3xnk5m); the .env location and
        .gitignore treatment are unchanged. Considered plain python-dotenv:
        lighter (no pydantic dependency), but requires hand-written validation
        and produces less clear errors on missing or malformed env vars.
        Considered raw os.environ access: brittle. pydantic-settings gives
        required-field validation at startup (server fails to initialize with
        a clear message if a required var is missing), type coercion
        (CONFER_USER_ID parsed as int), and a self-documenting Settings class
        as the single source of truth for all configuration. The pydantic v2
        dependency (~3 MB) is acceptable for the value provided and pays off
        more as configuration grows. (SUPERSEDED in phase 2B by Global
        Config In ~/.config/confer/config.toml, hq7x3npm: with only one
        config-loading site in the daemon, stdlib tomllib + a dataclass is
        sufficient validation, and pydantic-settings is dropped from runtime
        deps.)

    DiscordTransport Class = decision:
      id: b6npq7wm
      why: >
        All Discord interaction is encapsulated in a single DiscordTransport
        class in src/confer/transport.py. Methods needed across the phases:
        connect(), wait_for_ready(), notify(message), and later ask(...) and
        check_messages(). Considered a flat functions-only API with a
        discord.py Client held in module state: stateless-looking but smuggles
        global state (cached DM channel, last-seen message id) into
        module-level variables, which fights testability. Considered
        subclassing discord.py's Client directly: tighter coupling, and
        exposes discord.py's full surface where we only want our own narrower
        one. Composition (DiscordTransport holds a discord.py Client
        internally and exposes only our intended methods) gives a single mock
        seam for unit tests and a clean place for transport-level state.
        (Class itself unchanged in phase 2B; relocated to the confer.daemon
        subpackage as part of the daemon split per Central Daemon
        Architecture, dq7n3xpk. The MCP server no longer constructs one
        directly — it talks to the daemon over IPC.)

    Init Blocks On Gateway Ready = decision:
      id: 4vfnx7pq
      why: >
        The MCP server's initialize handler establishes the Discord Gateway
        connection and waits for discord.py's on_ready event before returning.
        Tool calls thereafter assume the Gateway is connected and ready.
        Considered per-call readiness check + short wait: spreads the
        readiness concern across every tool implementation, and a tool can in
        principle be called before initialize completes depending on the MCP
        client's behavior. Considered fire-and-forget initialize that returns
        immediately and lazy-connects on first tool call: would surface
        connection failures as "notify failed" rather than "server failed to
        initialize," which obscures the actual problem and adds latency to
        the first tool call. Blocking initialize concentrates the
        connection-failure surface in one expected place (server startup) and
        lets tool implementations be straight-line. Acceptable cost: ~1-3s
        startup delay (typical Discord Gateway connect + ready time), well
        inside any plausible MCP-protocol startup tolerance. (In phase 2B
        this applies to daemon startup; the MCP server's lifespan now blocks
        on daemon-ready, which in turn blocks on Gateway-ready. First-agent-
        after-reboot pays daemon-spawn + Gateway-connect; subsequent agents
        see no Gateway-connect latency at all.)

    DM Channel Lazy Cached = decision:
      id: gjw3pq7n
      why: >
        DiscordTransport fetches the target user and creates the DM channel
        lazily on first send (fetch_user(confer_user_id) → User.create_dm() →
        DMChannel), then caches the DMChannel reference on the transport
        instance for all subsequent sends. Considered eager pre-create at
        startup: catches a bad CONFER_USER_ID earlier (during initialize) but
        adds startup latency and complicates the initialize handler with a
        second blocking step beyond Gateway-ready. Considered no caching
        (re-fetch user and recreate DM channel every send): wasted API calls
        and per-call latency for no benefit. Lazy+cache surfaces user-id
        misconfiguration on the first notify (clear failure sentinel return)
        without paying per-call fetch cost.

    HELLO Protocol Version = decision:
      id: 7pjkmqv4
      why: >
        HELLO carries a protocol_version field (integer, starts at 1). The
        daemon records the client's version on connect and rejects HELLOs
        with versions it does not support (currently: anything other than 1)
        via HELLO_ERR. Considered no versioning: works fine for v1, but as
        the protocol grows (ask, check_messages) a client and daemon running
        different versions (which is the steady state after `uv sync`
        upgrades the client without restarting the daemon) will see
        "unknown message kind" errors at the first new message — opaque to
        the user, surfaces as "agent suddenly broken." Versioning makes the
        skew explicit at HELLO time with a clear error pointing at the
        upgrade. Considered semver-style major.minor.patch: overkill; a
        single monotonically-incrementing integer is sufficient given the
        simple protocol and small surface. Recorded after DevOps Engineer
        adversarial review (2026-05-28) raised the skew gap.

    # ─── DAEMON ARCHITECTURE ─────────────────────────────────────────────────

    Central Daemon Architecture = decision:
      id: dq7n3xpk
      why: >
        All Discord interaction is centralized in a long-lived daemon process
        (confer-daemon); per-session MCP servers become thin IPC shims that
        talk to the daemon over a Unix socket. Considered keeping the original
        design (one Discord Gateway connection per MCP server, recorded in
        Persistent Gateway Connection, bn4qj7wc): broke down the moment daniel
        confirmed the multi-agent reality — dozens of Claude Code sessions per
        day, often concurrent, each spawning its own stdio MCP servers. Discord
        disconnects duplicate Gateway sessions for the same bot token, so
        concurrent MCP servers would fight for the Gateway. Considered the
        one-bot-per-agent workaround (Direction 1 in design discussion): daniel
        explicitly rejected it as unscalable past ~5-10 bots, when dozens of
        ephemeral sessions per day are the norm. The daemon multiplexes one
        Gateway connection across all connected MCP servers, holds pending-ask
        and check_messages state across MCP-server churn, and dispatches user
        replies to the right agent by label. This incidentally resolves the
        tensions Pending Ask Lost On MCP Server Death (3nx7pq4m) and Proactive
        Messages Lost On Restart (4pjq7vmx). Tradeoff: meaningfully more code
        (IPC protocol, daemon lifecycle, socket server, dispatcher) and a new
        single point of failure recorded as tension Daemon Death Loses Pending
        State (nq7pxw4m).

    Auto-Spawn From MCP Server = decision:
      id: 7xj4mvqn
      why: >
        Each MCP server's lifespan handler first attempts to connect to the
        daemon's Unix socket; on failure (socket missing, connection refused,
        or stale socket file), it spawns confer-daemon via
        subprocess.Popen(start_new_session=True) with stdout/stderr redirected
        to the daemon log file, then polls the socket for up to 10s waiting for
        the daemon to bind and report ready. Considered requiring the user to
        start the daemon manually (or via systemd --user): adds operational
        burden that daniel will inevitably forget given the pace of opening new
        sessions; the failure mode (every new agent silently broken until
        daemon is started) is hostile. Considered shipping a systemd unit file:
        defers the first-agent-after-reboot latency to login time, but adds
        platform coupling and setup friction; deferred until practice shows
        the ~3-4s first-agent cost (daemon Python import + Gateway connect) is
        actually annoying. Race protection across concurrent auto-spawns is
        free; see Singleton Via Socket Bind (bm4vpx7q).

    Singleton Via Socket Bind = decision:
      id: bm4vpx7q
      why: >
        Daemon-singleton enforcement uses the socket bind itself as the lock,
        not a separate PID-file lock. Startup sequence: (1) if the socket file
        already exists, attempt to connect; (2) connect succeeds → another
        daemon is running, exit 0 silently; (3) connect fails → unlink the
        stale socket file; (4) bind the socket with 0600 perms; (5) if bind
        fails with EADDRINUSE (lost a race against another concurrent
        starter), exit 0 silently. A PID file at ${XDG_RUNTIME_DIR}/confer.pid
        is written after successful bind, but only for the benefit of the
        `confer-daemon stop` and `status` subcommands — the socket bind is the
        actual mutual-exclusion mechanism. Considered a fcntl-based file lock
        on a separate pidfile: equivalent semantically but adds a second
        critical section to reason about. Socket-bind-as-lock means the
        critical section IS the thing that lets clients connect, which is the
        right level of indivisibility.

    IPC Protocol NDJSON Over Persistent Unix Socket = decision:
      id: kp5w2nfx
      why: >
        IPC framing is newline-delimited JSON (NDJSON) over a Unix socket at
        ${XDG_RUNTIME_DIR}/confer.sock (fallback
        ${XDG_STATE_HOME:-$HOME/.local/state}/confer/confer.sock), with the
        socket owned 0600 by the user. File permissions ARE the access control
        on a single-user system — no in-band auth token needed. Each MCP
        server holds one persistent bidirectional connection for its lifetime;
        either side can send at any time. MCP-server-initiated commands carry
        a UUID4 request_id; the daemon's response (or any daemon-pushed event
        derived from that command, e.g., an ASK_REPLY arriving from Discord
        for an outstanding ASK_BEGIN) echoes the same id so the MCP server's
        awaiter matches. Considered length-prefixed JSON: tighter wire format
        but more parsing code for no real benefit at this scale. Considered
        JSON-RPC 2.0: a thoughtful standard but adds notification/error
        ceremony we don't need. Considered MessagePack or protobuf: binary
        formats, debugging-hostile, overkill for human-volume traffic.
        Considered per-request short-lived connections: simpler semantically
        but precludes daemon-pushed events (ASK_REPLY, broadcast
        CHECK_MESSAGES). NDJSON over a persistent bidirectional connection is
        the standard pragmatic shape for single-host IPC in async Python.

    Global Config In ~/.config/confer/config.toml = decision:
      id: hq7x3npm
      why: >
        Daemon configuration moves from per-project .env to a user-global TOML
        file at ~/.config/confer/config.toml (XDG-conformant), loaded with
        stdlib tomllib. Required fields: discord_bot_token, confer_user_id.
        Supersedes Bot Token In .env (pq3xnk5m) and Settings Via Pydantic
        Settings (5qx2wkpn) — both were correct under the old per-MCP-server
        architecture where each process owned its own Discord Gateway
        connection and lived in a specific project directory. With the daemon
        being a global singleton serving agents across all projects with one
        bot identity, per-project credentials make no sense. TOML chosen over
        JSON for human-editability (no missing-comma headaches when daniel
        edits the file by hand) and over YAML for stdlib availability
        (tomllib is stdlib in Python 3.11+; PyYAML would be an external dep).
        pydantic-settings is dropped from runtime dependencies — there is now
        only one config-loading site (the daemon), and a small dataclass over
        tomllib.load is enough validation. .env in the repo no longer holds
        secrets; .env.example becomes obsolete and is removed.

    Config Path Override Via CONFER_CONFIG = decision:
      id: w3kq7nxp
      why: >
        default_config_path() consults the CONFER_CONFIG environment variable
        first and falls back to the XDG default
        ~/.config/confer/config.toml when it is unset or empty. Refines
        Global Config In ~/.config/confer/config.toml (hq7x3npm): the global
        default is still the one-and-only path a normal user ever needs, but
        a single env var lets a process be pointed at an alternate config
        without code changes. The motivating use is the integration test tier
        (Integration Tests Not Yet Implemented, 5nqx7pmw): the test copies the
        real bot credentials into a throwaway temp config and sets
        CONFER_CONFIG so the auto-spawned confer-daemon loads THAT file,
        leaving daniel's real ~/.config/confer/config.toml untouched. It is
        also generally useful for running a second bot identity, or for
        anyone who keeps dotfiles outside $HOME. Considered overloading the
        existing path argument to Settings.load (already supported, but the
        daemon entrypoint calls Settings.load() with no argument, so a test
        cannot reach it without an env-level hook). Considered a CLI flag on
        confer-daemon: more surface, and the auto-spawn path constructs the
        argv itself, so a flag would not survive the spawn — an env var is
        inherited by Popen for free. Empty string is treated as unset (not as
        a request to load a file literally named "") to avoid a confusing
        failure when the var is exported-but-blank.

    Auto-Derived Agent Labels = decision:
      id: gj7wnq4p
      why: >
        Each MCP server's identity is auto-derived at startup as
        {repo}/{branch}[#{disambiguator}] with no per-session configuration
        required: repo = basename of `git rev-parse --show-toplevel` (or
        basename of cwd if not a git repo); branch = current git branch (or
        the literal string 'detached' if on a detached HEAD); disambiguator
        = first 4 hex chars of hash(pid, start_timestamp_ns), appended only
        when the daemon detects a collision with another already-connected
        MCP server. The MCP server sends its preferred label in HELLO; the
        daemon assigns the final label (appending the disambiguator if needed)
        and returns it via HELLO_OK. Considered requiring an explicit
        CONFER_AGENT_LABEL env var: too much per-session friction at daniel's
        pace of opening dozens of sessions per day. Considered using PID alone:
        meaningful to the daemon but useless to the human reading Discord.
        Considered MCP-protocol-derived agent name (client name from MCP
        initialize): partially useful but doesn't distinguish concurrent
        sessions of the same client.

    Daemon CLI run stop status = decision:
      id: 5jpxnq7w
      why: >
        confer-daemon exposes three subcommands. Bare invocation
        (`confer-daemon`) runs the daemon in the foreground — used by the
        auto-spawn path with stdout/stderr piped to
        ~/.local/state/confer/daemon.log via RotatingFileHandler (10MB, keep
        3 archives). `confer-daemon stop` reads the PID file at
        ${XDG_RUNTIME_DIR}/confer.pid, sends SIGTERM, waits up to 5s for
        clean shutdown. `confer-daemon status` reports PID, uptime, Discord
        Gateway state (connected/disconnected/reconnecting), connected MCP
        servers and their assigned labels, count of pending asks, count of
        queued check_messages, and the last 20 log lines. Daemon never
        auto-shuts down — idle-timeout was considered and rejected because
        the first-agent-after-shutdown latency (Gateway reconnect ~2-3s) is
        more annoying than the ~50MB idle RAM cost of just running. An
        explicit `confer-daemon stop` exists for clean termination when the
        user wants it (e.g., before upgrade or reboot).

    Daemon Interaction Audit Log = decision:
      id: dg7vnq4x
      why: >
        The daemon emits one INFO line to daemon.log at every confer
        interaction lifecycle event: a notify sent (label, tag, ok/failed), an
        ask begun (label, tag, give_up, on_timeout), an inbound user message
        routed (the routing outcome — delivered/queued/broadcast/bounced/
        ambiguous/concierge), an ask resolved by timeout (label, tag,
        disposition), an ask withdrawn, an ask dropped on lost contact, and a
        check_messages drain (label, count). Motivated directly by Productivity
        While Away (the goal): the operator could not previously tell whether
        agents were USING confer at all — the only daemon-authored INFO line
        was "daemon listening", so the live log gave zero visibility into
        notify/ask/check traffic, and the human's impression of adoption was
        guesswork. An INFO audit trail makes adoption observable and lets the
        operator distinguish "agents aren't reaching out" from "agents reached
        out but I missed it." Chosen at INFO (not DEBUG) so it survives the
        default root level (INFO, set in __main__._configure_logging) without a
        config change, and INFO (not WARNING) because these are normal events,
        not problems — keeping them out of the WARNING band that should mean
        "something needs attention." Deliberately logs only metadata already
        present in confer-authored envelopes (labels, tags, counts,
        dispositions); message/question BODIES are NOT added beyond what DM
        relaying already writes, so this does not widen the log's sensitivity
        beyond Daemon Log And State Dir Perms (lp7nqkx4). One line per event,
        not per poll, so it cannot itself become log spam (contrast wq4n7pxv).
        Rejected a separate structured metrics/JSONL sink: overkill for a
        single-user tool whose operator reads the log by eye via
        `confer-daemon status`; plain INFO lines are greppable and already
        rotation-managed (5jpxnq7w).

    Orphan Ask Drop Policy = decision:
      id: v4kn7mpq
      why: >
        Derivative of Asymmetric Robustness (wq7knm3p). When an MCP server's
        socket closes with asks pending (and the close was NOT a graceful
        shutdown that already sent ASK_CANCEL — see 3mq7pvxn), the daemon
        drops each pending ask immediately. No retention window, no re-routing
        to the next same-label MCP server, no participation in routing for
        late replies. For each dropped ask, the daemon sends a one-time
        "Lost contact with the agent that asked: *{question}*" DM (see Ask
        Closing Notifications, pkn7mvq4). If the user replies after the drop,
        the reply falls to the no-pending-asks bounce path described in
        Check Messages Queue Scaffolding (7nvpkqm3). Considered the 1h
        retention window originally drafted in 3nx7pq4m's resolution:
        rejected per Productivity While Away (pn4xvk2m) — the daemon does
        not preserve agent state across agent failure; daniel restarts the
        agent locally and either re-asks or proceeds. Considered routing
        orphan replies into the check_messages queue for the next same-label
        agent: rejected as the same anti-goal. The "smart bounce" affordance
        (a bounce DM that names the dead question) is also dropped — its
        marginal user value does not justify retaining orphan dispatch-table
        entries.

    Check Messages Queue Scaffolding = decision:
      id: 7nvpkqm3
      why: >
        Derivative of Asymmetric Robustness (wq7knm3p) and Minimal Agent
        Surface Operator Config (mk7npq4x). The daemon holds a per-label
        deque of QueuedMessage; the check_messages MCP tool drains the
        calling client's queue and returns its contents (Check Messages
        Inbox Model, cm7vnpqx). Concrete scope:
          - dict[agent_label, collections.deque[QueuedMessage]] on the
            Daemon instance.
          - bounded at 100 entries per label, FIFO eviction on overflow
            with a single-line log warning.
          - QueuedMessage carries (timestamp, content, source,
            original_question). source enum: "late_reply" (user replies
            to a closed ask), "labeled_interjection" (user-prefixed message
            to a connected client with no pending ask, per 7kxpvnqj rule
            1), and "broadcast" (rule 4; copied to every connected client's
            queue when no label match and no asks).
          - Lost on daemon death (covered by tension nq7pxw4m).
        Originally drafted in phase 2C as scaffolding only (queue but no
        consumer, no broadcast). Phase 2D activates the consumer
        (check_messages tool) and broadcast (per Broadcast Semantics,
        bw4kqnxp). Considered dropping the queue entirely in 2C until 2D:
        rejected then because late_reply was a real edge case worth
        graceful handling even without a consumer; that early scaffolding
        landed clean and is now joined by its consumer in 2D.

    On Message Handler Wiring = decision:
      id: m4kpvn7q
      why: >
        DiscordTransport receives an on_user_message callback at
        construction: DiscordTransport(on_user_message=daemon
        ._dispatch_user_message). The callback is invoked from the
        transport's @client.event handler when a DM arrives from the
        configured confer_user_id. No module-level registry, no late binding
        via setter, no inheritance. Considered setter-based wiring
        (DiscordTransport().set_on_user_message(...)): rejected because the
        callback is constitutive of the transport's behavior, not a
        configurable add-on — constructing a transport without it would
        produce a half-built object. Considered subclassing discord.py's
        Client: rejected per DiscordTransport Class (b6npq7wm), which
        already mandates composition over inheritance for the same family
        of reasons. Derivative of Asymmetric Robustness (wq7knm3p) — the
        dependency-injection shape supports the daemon as the routing
        authority while keeping the transport testable in isolation.

    CLI Inject Tool = decision:
      id: ci7n4pvm
      why: >
        Resolves CLI Answer Injection Pending (7pvkn4qm). New top-level
        `confer` binary with two subcommands:

          confer list           # show pending asks the user can answer
          confer answer "text"  # apply Reply Routing Rules (7kxpvnqj) to
                                # the text and report the outcome

        Connects to the same Unix socket as the MCP client, but does NOT
        send HELLO — the CLI is not an MCP-spawned client and has no
        meaningful agent label. Two new protocol messages
        (Inject / InjectResult and ListAsks / ListAsksResult) are exempt
        from the hello_required rule per the STATUS precedent (xn7pqv4m
        excludes daemon-internal queries from registration).

        Daemon-side behavior: the Inject message's content is fed directly
        into the same _dispatch_user_message path that handles Discord
        DMs. The same RouteDecision union applies, so the CLI gets exactly
        the same routing semantics the user already learned for Discord. The
        InjectResult carries an outcome tag plus a human-readable detail
        string the CLI prints.

        Outcome set (corrected post-G3; review finding TST-F2): the daemon
        emits exactly delivered, queued_notify_reply, broadcast, bounced,
        ambiguous, concierge. (The pre-G3 draft of this node listed
        "queued_labeled" from the dropped label-addressing path, rt7nqp4m;
        that outcome no longer exists, and notify-reply queueing, nr4kpq7v,
        plus the concierge stub, cg7vnq4p, were never recorded here. The
        InjectResult.outcome Literal and this node are now reconciled to the
        emitted set, with a test enumerating every daemon-emitted outcome
        against the Literal so the contract cannot silently drift again.)
        CLI exit-code mapping: delivered / queued_notify_reply / broadcast
        exit 0 (the message reached an agent or a queue); bounced / ambiguous
        / concierge exit non-zero (nothing was delivered to an agent), so a
        script branching on `confer answer` exit status behaves correctly.

        Considered making the CLI HELLO with a special "cli/local" label:
        rejected because the CLI is not an entity that should appear in
        the routing graph as a candidate recipient — it's a user-side
        injector. The STATUS-style HELLO exemption is the right pattern.

        Considered embedding the inject capability inside `confer-daemon`
        (which already has a CLI for run/stop/status): rejected because
        daemon-control and user-injection are different audiences with
        different invocation cadences (one-shot user actions vs.
        operational lifecycle). Separate binaries keep each surface
        focused.

        Considered structured `confer answer <ask-id> "text"` with
        ask-id-as-argument: rejected because the user already has the
        Discord routing-rules vocabulary in their head (label prefix,
        numeric shortcut, single-ask shortcut). Reusing those rules in
        the CLI means zero additional cognitive load. The CLI's only
        novel surface is `confer list` to surface what asks exist when
        the user can't see the Discord side.

        Derivative of Spokesperson Abstraction Principle (vj4xqn7p) —
        the same routing engine accepts content from any channel — and
        Productivity While Away (pn4xvk2m) — keeps daniel productive
        when he returns to his laptop with a Discord notification he
        missed.

    Reply Routing Parser = decision:
      id: nqx7pmv4
      why: >
        The reply-routing rules from Reply Routing Rules (7kxpvnqj) are
        implemented as a pure function route_user_message(content: str,
        pending_asks: Sequence[PendingAsk]) -> RouteDecision living in
        src/confer/daemon/routing.py. RouteDecision is a small discriminated
        union: Deliver(label, content) | Bounce(reason) | Ambiguous
        (numbered_list). The daemon's _dispatch_user_message calls the
        function then acts on the result. Considered a method on the Daemon
        class: rejected because the routing logic is the most testable part
        of the dispatch path and benefits from being callable in isolation,
        without daemon scaffolding (sockets, asyncio tasks, transport
        mocks). Considered embedding the routing logic inline in
        _dispatch_user_message: rejected for the same testability reason.
        Tests exercise route_user_message directly with synthetic
        pending_asks lists.

        REVISED IN G3 by Tag Based Reply Routing (rt7nqp4m): the pure function
        gains the set of active threads (asks + notify-threads, each with its
        tag) and returns the widened RouteDecision union (tag-targeted deliver,
        notify-interjection enqueue, broadcast, bounce, ambiguous, plus a
        concierge-stub variant for a leading "."). The pure-function-in-
        routing.py shape and its isolation-testability rationale are unchanged.

    # ─── TOOL SURFACE ────────────────────────────────────────────────────────

    Three Tools = decision:
      id: 7gwx2qcr
      why: >
        The MCP server exposes exactly three tools: notify(message),
        ask(question, timeout_seconds, on_timeout), and check_messages().
        Considered just notify + ask: simpler, but fails to support the
        proactive-user-input case where daniel sends a message ("also consider
        X") between asks. Considered notify + ask + status + cancel + ...:
        speculative breadth without a justifying use case. Three tools cover
        the established use cases (fire-and-forget notify, blocking ask,
        polling for unsolicited messages) without over-design.

    ask Signature With on_timeout = decision:
      id: 4mhp7jqx
      why: >
        Signature: ask(question: str, give_up_after_seconds: int = 1800,
        on_timeout: Literal["use_best_judgment", "abort"]
        = "use_best_judgment") -> str. The give_up_after_seconds bound is
        enforced by Pydantic at the schema surface (1 ≤ x ≤ 86400, where
        86400 is the daemon's 24h operator-set ceiling per Minimal Agent
        Surface Operator Config, mk7npq4x). Two on_timeout modes; the third
        originally drafted (wait_forever / wait_max) was removed in 2C
        because its semantics ("re-ping until answered, capped somewhere")
        collapse cleanly to "set give_up_after_seconds = 86400 and let the
        universal re-ping cadence run" — no separate mode needed. The
        parameter was originally named timeout_seconds; renamed in 2C after
        recognizing the original name conflated two concepts (when the wait
        ends vs. how often to re-ping). The Fowler renaming discipline (§4
        of docs/methodology.md) demanded the rename. Considered a single
        timeout-or-not flag with no policy field: rejected because different
        questions need different fallback behaviors — "what's the best
        refactor approach" tolerates use_best_judgment, "should I drop this
        database table" must abort and surface state. Default 30 min (1800s)
        is a round number between agent attention span (~10 min) and user
        away-from-desk (~1 hour); revisable from experience. The directive
        strings returned on timeout are operationalized by Natural Language
        Outcomes (xj4nqv7m) and Sentinel Returns Not Exceptions (nx2pj4wq);
        the universal re-ping behavior is operationalized by Wait Behavior
        Re-Pings (hj7m4qbx).

    Next Message Wins For Reply = decision:
      id: vk3qn7fp
      why: >
        After ask sends a question, the next DM from the user (newer than
        the bot's question by Discord timestamp) is treated as the reply.
        Considered requiring Discord's native reply-to-message feature:
        unambiguous attribution but adds a tap on mobile, which fights the
        dictation use case (the whole point is friction-free voice input —
        a tap to invoke reply-mode then dictate is a worse UX than just
        holding-mic-and-talking in the DM). Next-message-wins is friction-free
        at the cost of attribution ambiguity when the user sends proactive
        messages between question and reply — see tension
        Reply Disambiguation When Proactive Arrives Mid-Ask.

    Sentinel Returns Not Exceptions = decision:
      id: nx2pj4wq
      why: >
        Timeout, cancellation, and daemon-disconnect outcomes are returned as
        natural-language directives in spokesperson voice (see Spokesperson
        Abstraction Principle, vj4xqn7p), not as raised exceptions and not as
        opaque sentinel tokens. The directive strings:
          - on_timeout="use_best_judgment": "No answer was received within the
            requested window. Follow your existing instructions or your best
            judgment about how to proceed."
          - on_timeout="abort": "No answer was received within the requested
            window. Stop work on this task and leave its state somewhere the
            user can pick up later (e.g., a WIP commit, a status file)."
          - daemon disconnect mid-ask: "Lost connection to confer; question
            not answered. Retry or proceed without the user's input."
          - ASK_CANCEL: no string returns — the agent's tool call is cancelled
            at the MCP layer and the agent isn't there to read it.
        Considered raising TimeoutError or a custom AskTimeoutError across the
        MCP boundary: rejected because exceptions surface as tool errors that
        obscure the "normal outcome with a fallback policy" nature of the
        result. Originally drafted as opaque sentinel tokens
        (<NO_RESPONSE_USE_BEST_JUDGMENT>, <NO_RESPONSE_ABORT>); revised in 2C
        per Natural Language Outcomes (xj4nqv7m) — sentinels require the
        agent's system prompt to teach the vocabulary, while directives are
        self-explanatory and cross the boundary as ordinary prose. The node
        name retains "Sentinel" as a legacy label; the values are now
        directives.

    Wait Behavior Re-Pings = decision:
      id: hj7m4qbx
      why: >
        All in-flight asks send a reminder DM at the daemon-configured
        re-ping cadence (default 900 seconds = 15 min, configurable via
        ask.re_ping_every_seconds in ~/.config/confer/config.toml). Universal
        across both on_timeout modes; not a per-mode behavior. Body text:
        "Still waiting on your answer to: *{question}*" (italics on the
        question). The footer composed by Reply Routing Footer (xqp4nv7m) is
        recomputed and re-attached per send because numeric shortcuts reflect
        the current pending-ask set. Skips any re-ping that would fire within
        60 seconds of the give_up_after_seconds deadline (avoids "still
        waiting" followed seconds later by "no answer received"). The
        86400-second cap on give_up_after_seconds (enforced by Pydantic per
        Minimal Agent Surface Operator Config, mk7npq4x) is the upper bound
        on how many re-pings can fire for any single ask. Implementation
        shape: per-ask asyncio.Task running an interval-sleep loop, stored
        alongside the _PendingAsk record, cancelled in order (re-ping task
        first, then dispatch-table entry removed, then client-facing Future
        resolved) so a re-ping cannot race a resolved ask. Re-ping send
        failures (DiscordException during transport.send) are non-fatal — the
        task logs and continues; the ask itself still resolves on reply or
        timeout per its own contract. Originally drafted as a per-mode
        behavior tied to a wait_forever mode at the caller-chosen interval;
        revised in 2C to a universal daemon-config concern per Minimal Agent
        Surface Operator Config (mk7npq4x) and Acknowledge Actionable State
        Changes (qn7pkm4v). Renamed from "Wait Forever Re-Pings" to reflect
        that re-pings are now universal, not wait_forever-specific.

        REVISED IN G3: the re-ping body adopts the "Re: {tag} — still waiting
        on your answer" anchoring of Threaded DM Conventions (dm5kqv7n), and
        the recomputed Reply Routing Footer is gone (the tag is printed inline
        instead). The per-ask asyncio.Task shape and skip-near-deadline rule
        are unchanged.

    check_messages In-Memory State = decision:
      id: 5pq7n3kw
      why: >
        Pre-daemon-architecture draft of check_messages state lived in the
        MCP server process; SUPERSEDED in phase 2B by Central Daemon
        Architecture (dq7n3xpk) and replaced in phase 2D by Check Messages
        Inbox Model (cm7vnpqx). State now lives in the daemon's
        per-label queue (Check Messages Queue Scaffolding, 7nvpkqm3) and is
        consume-on-read, not last-seen-ID-based. Kept in this.i for the
        historical thread; do not implement against this node.

    check_messages Inbox Model = decision:
      id: cm7vnpqx
      why: >
        Derivative of Productivity While Away (pn4xvk2m) and Asymmetric
        Robustness (wq7knm3p). check_messages reads the calling client's
        per-label queue, returns the queued messages as a formatted
        natural-language string (per Natural Language Outcomes, xj4nqv7m),
        and CLEARS the queue. Inbox semantics: each message is delivered
        to a given agent exactly once. Considered a stream model (timestamped
        view that ages out, agent re-reads with a since-cursor): rejected
        because proactive messages from the user are best modeled as
        instructions to act on once, not ambient context to re-poll. Inbox
        plus broadcast-copy (Broadcast Semantics, bw4kqnxp) gives multiple
        agents independent delivery of the same broadcast message — each
        consumes its own copy.

        Signature: check_messages() -> str. No parameters per Minimal Agent
        Surface Operator Config (mk7npq4x); the agent has no meaningful
        knob to dial per call. Empty-queue return is a short directive
        ("No messages from the user.") rather than an empty string, so the
        agent's reasoning has something concrete to act on without special-
        casing emptiness. Non-empty return formats messages with brief
        per-entry headers (timestamp + source kind) so the agent can tell
        a "broadcast" interjection from a "labeled_interjection" from a
        "late_reply." Considered returning structured data (list of dicts):
        rejected per Natural Language Outcomes — a single formatted string
        crosses the MCP boundary as ordinary prose the agent's reasoning
        handles directly.

        REVISED IN G3: queued entries now carry the originating thread tag,
        and the formatted output anchors each with "Re: {tag}" so the agent
        can correlate an interjection with the notify it answers. The source
        kinds become "broadcast", "notify_reply" (a tagged reply to one of the
        agent's notify-threads, per Notify Replyable Threads nr4kpq7v), and
        "late_reply"; "labeled_interjection" is retired with label-addressing
        (rt7nqp4m).

    Broadcast Semantics = decision:
      id: bw4kqnxp
      why: >
        Implements 7kxpvnqj rule (4) — when zero asks are pending anywhere
        and no label prefix matches a connected client, the user's DM is
        copied to EVERY connected MCP server's queue with source="broadcast".
        Each agent consumes its own copy via check_messages. When zero
        agents are connected, the daemon falls back to the 2C-era bounce
        DM (no holding-for-future-agents pool); preservation across "no
        agents connected" gaps is an explicit anti-goal of Asymmetric
        Robustness (wq7knm3p) — daniel restarts agents locally, then
        re-sends if a message mattered. Considered holding messages for
        the next-connected agent (a "broadcast pool" or default queue):
        rejected because it conflicts with Asymmetric Robustness and
        introduces a new state class with no clear retention rule. Also
        considered limiting broadcast to ONE agent (some heuristic — most
        recently connected, etc.): rejected because the routing prefix is
        the user's mechanism for narrowing to one agent (rule 1); without
        a prefix, broadcast-to-all is the safer interpretation of "this is
        a sweeping instruction."

        REVISED IN G3 by Tag Based Reply Routing (rt7nqp4m): broadcast (the
        zero-asks-pending, no-tag case) is retained exactly as described here.
        The label-prefixed targeted-interjection path below is DROPPED with
        label-addressing; the targeted-interjection need is now served by
        replying to a specific notify's tag (Notify Replyable Threads,
        nr4kpq7v) rather than by an agent-label prefix. The paragraph below is
        retained for history; read nr4kpq7v for the current targeted path.

        Phase 2D also activates the half of 7kxpvnqj rule (1) that 2C
        papered over: a label-prefix match against a CONNECTED CLIENT
        (not just an active ask) routes the message to that client's
        check_messages queue with source="labeled_interjection". This is
        what lets daniel address a specific agent that isn't currently
        asking anything ("confer: BTW use library X").

    notify Tool Signature = decision:
      id: m7nqxpk4
      why: >
        Signature: notify(message: str) -> str. Returns a descriptive success
        string ("sent at <ISO-8601 UTC timestamp>") on success and a sentinel
        string ("<NOTIFY_FAILED: <reason>>") on failure. Considered -> None
        with exceptions on failure: MCP passes exceptions through as tool
        errors that the calling agent must handle as error conditions rather
        than as informational results, which obscures the "I tried, here is
        what happened" nature of the outcome. Considered -> dict {sent_at,
        message_id, status}: structurally cleaner but overkill for a
        fire-and-forget tool — the agent rarely needs the message_id. String
        returns also keep the result class uniform with the sentinel pattern
        already established for ask timeouts (Sentinel Returns Not Exceptions,
        nx2pj4wq), letting the agent's natural-language reasoning handle both
        outcomes the same way.

    Notify Self-Description Policy = decision:
      id: 4kxp7qnj
      why: >
        Adversarial review by a fresh Claude Code session (recorded as G1 in
        docs/gaps.md, 2026-05-28) found that confer's MCP self-description
        was insufficient to guide an agent that lacked prior memory of the
        project. Specifically: no server-level instructions block,
        mechanics-first tool docstring with no when-to-use guidance, and
        zero description on the message parameter. Without these a fresh
        agent either over-uses notify as a generic "tell the user" channel
        or under-uses it because the purpose is not apparent from the
        schema. Resolved by three concrete changes:

        (1) FastMCP is constructed with instructions= containing ~10 lines
        of when-to-use and when-not-to-use guidance that lands in every
        client's system prompt.

        (2) notify's docstring is rewritten purpose-first ("Ping the user
        out-of-band via Discord DM"), referencing the instructions block
        for detail rather than restating mechanics first.

        (3) The message parameter gets an explicit
        Annotated[str, Field(description=...)] with a concrete example and
        a phone-friendly URL-preferred-over-file-path note (daniel reads
        notifications on mobile where workstation file paths are
        unreachable).

        Considered an MCP resource confer://usage-guide with long-form
        policy: deferred as overkill for a one-tool surface — see tension
        MCP Resource For Usage Guide Pending (7nqxw4pj). Considered
        renaming notify to a more specific verb (ping_user_offband,
        dm_user_async, alert_user): deferred because the rename touches
        the recorded Naming decision (qj4xm7pn) and description-plus-
        instructions is the cheaper, more direct lever — see tension
        Notify Tool Name Reconsideration Pending (3pqvn7mw). Post-fix
        acid test (a clean Claude in a worktree-isolated context given
        mixed-shape tasks) tracked in gaps.md as G2.

        G2 RESULT (2026-05-29): the acid test ran against the full
        notify/ask/check_messages surface — a confer-naive subagent given
        only this self-description scored 11/11 on tool discrimination
        (including don't-use-confer cases), validating the policy. It also
        surfaced two wording refinements, since applied: (a) a stale notify
        "USE when" bullet ("you hit a blocker that needs the user's input")
        was misleading now that ask exists — notify is one-way, so a
        reply-needed blocker is an ask; reworded to say notify is for things
        that do NOT need a reply. (b) on_timeout="abort" guidance, framed
        only around destructiveness, now also names "no safe default exists
        / cannot proceed without an answer" as an abort trigger. G2 is
        closed; the acid test is tracked as a recurring audit in Prompt
        Audit History (vp4nm7qx). The rename question (3pqvn7mw) is resolved
        against renaming on this evidence.

    notify Fail Fast = decision:
      id: 3kpwn7mj
      why: >
        On a Discord API failure (network error, HTTPException, NotFound),
        notify returns the failure sentinel immediately — no retries inside
        the transport. Considered retry-with-exponential-backoff (e.g., 3
        attempts with jitter): would mask transient network blips but adds
        complexity (interruption handling, jitter strategy, when-to-stop
        rules) for marginal value on a personal tool. Explicit retry by the
        calling agent (just call notify again) is more debuggable than
        implicit retry inside the transport, and the agent has better context
        for whether retrying makes sense for the specific message. If
        experience shows transient failures are common and agents do not
        retry well in practice, this decision is cheap to revisit.

    Notify Before Hello Rejected = decision:
      id: xn7pqv4m
      why: >
        When a client sends NOTIFY (or future ASK / CHECK_MESSAGES) before
        HELLO, the daemon rejects with Error(code="hello_required") and
        does not act on the message. Considered silently accepting and
        dispatching: simpler code, but with multi-agent reply routing
        (7kxpvnqj) the daemon needs the client's assigned label to attribute
        messages and route asks; without HELLO it does not know who is
        notifying. Considered accepting with an "anonymous" label: ambiguous
        in the Discord UI ("[anonymous] task done") and racy with future
        check_messages broadcast. Rejecting forces clients to identify
        themselves before doing work, which is a precondition for every
        downstream feature. STATUS (daemon-internal CLI query) is exempt —
        it has no agent identity and reading daemon state does not require
        registration. Surfaced by Testability Hawk adversarial review
        (2026-05-28); behavior was previously undeclared.

    Reply Routing Rules = decision:
      id: 7kxpvnqj
      why: >
        With Central Daemon Architecture (dq7n3xpk) and multiple concurrent
        MCP servers, the daemon must route user DMs to the right pending ask.
        Rules, applied in order:

        (1) Parse the first whitespace/punctuation-bounded token of the
            message. Treat it, case-insensitively, with hyphens and spaces
            interchangeable in the match, as a prefix. If it is a unique
            substring of an active label, route the rest of the message to
            that label's pending ask (if any) or to that label's
            check_messages queue (otherwise).

        (2) Reserved tokens '1', '2', '3', ... are number shortcuts: index
            (1-based) into the list of pending asks ordered newest-first.

        (3) When there is exactly one pending ask across all connected MCP
            servers, no prefix is required — the entire message is the reply
            (preserves the next-message-wins ergonomics of vk3qn7fp for the
            single-agent case).

        (4) When there are zero pending asks anywhere, the message is
            broadcast — every connected MCP server's check_messages queue
            receives it (supports interruptions like "stop, requirements
            changed").

        (5) When there are multiple pending asks and the user supplies an
            ambiguous or absent prefix, the bot DMs back a numbered list of
            pending asks ("Multiple asks waiting: [1] confer/feat-ask: ...,
            [2] myapp/main#a3f1: ...; reply with '1', '2', or a label
            prefix") and the original message is dropped. The user must
            re-send with disambiguation.

        Every ASK message includes a footer the bot appends — "(reply:
        feat-ask, 1, or just answer if I am the only one waiting)" — so
        daniel never has to memorize or look up labels. Considered Discord's
        native reply-to-message feature for routing: unambiguous but adds a
        mobile tap, fighting the dictation use case for the same reasons it
        was rejected in Next Message Wins For Reply (vk3qn7fp). Considered
        per-agent DM channels (one bot per agent): rejected as unscalable
        when daniel runs dozens of sessions per day. Reply Disambiguation
        When Proactive Arrives Mid-Ask (rk2nq7pm) remains open in the
        multi-agent context.

        Phase-2D staging notes: (a) Rule (4) broadcast is implemented in
        phase 2D per Broadcast Semantics (bw4kqnxp); the 2C-era "no agents
        asking" bounce DM now fires only when zero clients are connected.
        (b) The dispatch table consulted for routing contains only LIVE
        asks; orphaned asks are dropped immediately per Orphan Ask Drop
        Policy (v4kn7mpq) and do not participate in attribution. (c) Rule
        (1) matches labels of connected CLIENTS, not just labels of active
        asks; a label-prefixed message to a connected client with no
        pending ask enqueues with source="labeled_interjection" per
        Broadcast Semantics. (d) The footer mechanics described in this
        rule are implemented per Reply Routing Footer (xqp4nv7m).

        REVISED IN G3 by Tag Based Reply Routing (rt7nqp4m): rules (1)-(5)
        are reworked around thread tags. The numeric shortcut (rule 2) and
        label-prefix addressing (rule 1) are DROPPED; the per-message footer
        is removed (dm5kqv7n). Broadcast (rule 4), the single-ask shortcut
        (rule 3), and the ambiguity bounce (rule 5) survive, now keyed on
        awaiting ASK-threads. Read rt7nqp4m as the current ladder; this node
        is retained for the why behind broadcast and the rejected
        reply-to-message alternative.

    Ask Closing Notifications = decision:
      id: pkn7mvq4
      why: >
        Derivative of Acknowledge Actionable State Changes (qn7pkm4v). Every
        ask that resolves WITHOUT a user reply sends a brief Discord DM
        informing the user what disposition was chosen:
          - timeout (use_best_judgment): "**Time's up — agent will use its
            best judgment on:** *{question}*"
          - timeout (abort): "**Time's up — agent will stop and surface state
            for:** *{question}*"
          - cancellation (ASK_CANCEL): "**Question withdrawn:** *{question}*"
          - agent disconnect (orphan): "**Lost contact with the agent that
            asked:** *{question}*"
        Reply-resolved asks are silent (the user just sent the reply; they
        know). DMs are best-effort; send failures log but do not back-
        propagate to the agent. The text is framed in spokesperson voice
        (per Spokesperson Abstraction Principle, vj4xqn7p) — the daemon is
        reporting what it did on the agent's behalf, not what the user failed
        to do. Sequence inside the daemon when a timeout fires: (1) cancel
        the per-ask re-ping task, (2) remove the dispatch entry, (3) send
        ASK_TIMEOUT to the MCP server (agent unblocks first), (4) send the
        closing DM (courtesy, best-effort). Considered silent resolution
        (user discovers state only on the next interaction): rejected per
        Productivity While Away (pn4xvk2m) — the asynchronous Discord
        channel is the user's only window into agent state. Considered
        including timestamps, attempt counters, or durations in the DM body:
        rejected as noise.

        REVISED IN G3 (gaps.md F-A fix): the "reply-resolved is silent" rule
        carves out CLI-resolved asks. The rationale for silence — "the user
        just typed the answer, so they know" — holds only when the answer was
        typed on Discord. When an ask is resolved via the phase-3 `confer
        answer` CLI (CLI Inject Tool, ci7n4pvm), the Discord-side user did NOT
        type anything and would otherwise see the question DM sit open forever.
        So a CLI-resolved ask now sends a closing DM: "Re: {tag} — answered
        from the laptop." Discord-typed replies remain silent. All closing/
        disconnect/withdrawn DMs adopt the "Re: {tag} — ..." anchoring of
        Threaded DM Conventions (dm5kqv7n) instead of restating the full
        question.

    ASK_CANCEL Protocol = decision:
      id: 3mq7pvxn
      why: >
        Derivative of Acknowledge Actionable State Changes (qn7pkm4v) and
        Asymmetric Robustness (wq7knm3p). The protocol carries an
        ASK_CANCEL{request_id} message from MCP server to daemon. Daemon
        receipt is idempotent: lookup of pending_asks by request_id; if
        absent (already resolved by reply or timeout — race), no-op.
        Otherwise: cancel the per-ask re-ping task, remove the dispatch
        entry, send "Question withdrawn" closing DM (see Ask Closing
        Notifications, pkn7mvq4). No ack message; fire-and-forget. The MCP
        server emits ASK_CANCEL in two paths: (a) when its tool handler
        receives asyncio.CancelledError (typically from the agent client
        pressing ESC, propagated via the MCP cancellation notification), and
        (b) during graceful MCP-server shutdown — the lifespan handler
        enumerates pending asks and fires ASK_CANCEL for each before closing
        the socket. Ungraceful crashes (SIGKILL, OOM) fall to socket-close
        cleanup, which triggers Orphan Ask Drop Policy (v4kn7mpq) with "Lost
        contact" DMs. The asymmetry between cancel-DM and lost-contact-DM is
        informational: it tells the user whether the shutdown was
        intentional. Considered a single message kind for both clean-cancel
        and crash: rejected because the user-facing DM should differ.
        Considered a reason field on ASK_CANCEL: rejected because the daemon
        doesn't branch on it and the agent doesn't supply meaningful reasons
        via MCP cancellation.

    Reply Routing Footer = decision:
      id: xqp4nv7m
      why: >
        Derivative of Acknowledge Actionable State Changes (qn7pkm4v) and
        Minimal Agent Surface Operator Config (mk7npq4x). The footer the bot
        appends to ask DMs (per Reply Routing Rules, 7kxpvnqj) is composed
        daemon-side at send time, not transport-side, and is recomputed for
        every send — including each re-ping per Wait Behavior Re-Pings
        (hj7m4qbx) — because numeric shortcuts (per 7kxpvnqj rule 2) are
        1-based newest-first over the current pending-ask set and the right
        index drifts as asks come and go. Format when multiple asks are
        pending: "(reply: <comma-separated unique shortest prefix per
        label>, 1-N, or just answer if I'm the only one waiting)". When only
        one ask is pending, the footer is omitted entirely — the DM body is
        enough, and a footer that says "or just answer if I'm the only one
        waiting" while the single-ask shortcut is already trivially
        available is noise. Considered transport-side composition: rejected
        because the transport doesn't know the full pending-ask set; pushing
        the responsibility to the daemon avoids a callback the transport
        would otherwise need. Considered a static footer computed once at
        ask-time: rejected because re-ping context drifts as the pending
        set evolves. SUPERSEDED IN G3 by Threaded DM Conventions (dm5kqv7n):
        the appended footer is removed entirely; each DM now prints its own
        thread tag inline as the routing referent, so there is no separate
        footer to compose or recompute.

    # ─── THREADED CHANNEL (G3) ───────────────────────────────────────────────
    # Surfaced by end-to-end smoke testing 2026-05-29 (docs/gaps.md G3): with
    # several same-label question DMs visible in scrollback, daniel could not
    # tell confer which one he meant to answer. Resolved by a thread-tag model
    # with email-style "Re:" addressing. These decisions revise the routing and
    # footer decisions above (7kxpvnqj, xqp4nv7m) and the closing/re-ping text.

    Thread Tag Model = decision:
      id: tgq4n7px
      why: >
        Each ask and each notify is a "thread" — the unit of daniel's attention
        in the channel, finer-grained than an agent (a single agent may own
        several threads across its life; an 8-hour agent that needs help at
        hours 1, 4, 7 opens three threads). The daemon assigns every thread a
        random 4-char base32 tag (alphabet [a-z2-7], same as this.i node ids),
        unique among currently-active threads, regenerating on collision the
        way Auto-Derived Agent Labels (gj7wnq4p) disambiguates labels. The tag
        is a terse ADDRESSING REFERENT, not an editorial subject: daniel reads
        the full message to answer anyway, so a meaningful summary adds little
        over a short token he can put after "Re:". Considered agent-supplied
        subjects (email-subject-line analogy): rejected as overkill — the full
        message is always read, and a subject parameter would add agent-facing
        contract load, violating Minimal Agent Surface Operator Config
        (mk7npq4x). Daemon-assigned-always leaves the agent contract unchanged.
        Considered a monotonic counter (#1, #2): rejected because counters are
        ephemeral and collide with reply prose; opaque base32 reads as native
        to the system and is scrollback-stable.

    Threaded DM Conventions = decision:
      id: dm5kqv7n
      why: >
        Every confer DM anchors to its thread so the channel reads as the
        threaded conversation daniel actually has in mind. Question and notify
        DMs lead with tag and agent label: "[k3qp] confer/main: <body>".
        Follow-up DMs about an existing thread (closing notifications per
        pkn7mvq4, re-pings per hj7m4qbx) use email-style "Re:" anchoring:
        "Re: k3qp — time's up; agent will use its best judgment." SUPERSEDES
        Reply Routing Footer (xqp4nv7m): the inline per-message tag is the
        routing referent now, so the appended "(reply: ...)" footer is removed
        on every DM. Considered keeping a footer listing all open tags:
        rejected as redundant once each message prints its own tag, and noisy
        as the open set grows. Derivative of Acknowledge Actionable State
        Changes (qn7pkm4v) — the anchor is what lets daniel separate threads
        at a glance with minimal cognitive load.

    Tag Based Reply Routing = decision:
      id: rt7nqp4m
      why: >
        Rewrites the routing ladder of Reply Routing Rules (7kxpvnqj) around
        thread tags. Incoming user DM, in order:

        (1) TAG MATCH. Phone-tolerant: case-insensitive; stray punctuation
            (: , .) and spacing ignored; an optional leading reply marker (the
            letters "re", any case, optional trailing :/,). WITH the marker the
            next token matches an active tag by UNIQUE PREFIX ("re k3" hits
            k3qp if unique; >1 match -> ambiguity bounce). WITHOUT the marker
            only an EXACT full 4-char tag at the start counts ("k3qp answer is
            x") — a bare prefix with no marker is NOT a tag (too ambiguous
            against ordinary prose). Remainder is the reply content. Matched
            thread: an ask -> ASK_REPLY; a notify -> queued interjection (see
            Notify Replyable Threads, nr4kpq7v).

        (2) Else exactly one ASK awaiting -> that ask (next-message-wins,
            vk3qn7fp).

        (3) Else two+ asks awaiting -> ambiguity bounce listing awaiting asks
            with their tags.

        (4) Else no asks awaiting and >=1 agent connected -> broadcast to every
            connected agent's check_messages queue (the sweeping interject,
            "everyone stop").

        (5) Else (no agents connected) -> bounce.

        Only ASK-threads participate in steps 2-4; notify-threads are
        addressable by explicit tag only (step 1) and never suppress the
        single-ask shortcut or broadcast — else accumulated notifies would
        wreck the common case. DROPS two behaviors from 7kxpvnqj: the numeric
        shortcut (1,2,3 — superseded by scrollback-stable tags) and label-
        prefix addressing (a tag is a finer referent; broadcast covers
        "address everyone" and per-thread tags cover the rest, so addressing a
        whole agent by label earned no remaining use). Considered Discord
        native reply-to-message: rejected again per vk3qn7fp (mobile tap).
        Reduces but does not fully close Reply Disambiguation When Proactive
        Arrives Mid-Ask (rk2nq7pm).

    Notify Replyable Threads = decision:
      id: nr4kpq7v
      why: >
        A notify creates a replyable thread, not just a fire-and-forget ping.
        Replying to a notify's tag ("re m4qp roll it back") enqueues the reply
        into that agent's check_messages queue tagged with the thread, so the
        agent picks it up on its next check — the precise-target version of the
        interjection daniel wanted ("actually, roll it back" right after
        "deploy finished"). Notify tags are addressable only while the
        originating agent is connected; on disconnect the tag dies and a reply
        bounces (Asymmetric Robustness, wq7knm3p — no preservation across agent
        death). A modest per-agent cap on live notify tags keeps the prefix
        space sparse; oldest expires first. Considered keeping notify purely
        fire-and-forget: rejected because daniel explicitly wants to talk back
        to an unsolicited ping, and the room/memo metaphor makes any memo
        answerable. Considered persisting notify tags past disconnect: rejected
        per Asymmetric Robustness.

    Concierge Sigil Reservation = decision:
      id: cg7vnq4p
      why: >
        A leading "." on a user DM is reserved for daemon-directed (concierge)
        messages — addressing the daemon itself, not any agent. Checked BEFORE
        punctuation-stripping and before the routing ladder, so a "." message
        never broadcasts to agents. Phase G3 ships only a STUB: a "."-prefixed
        DM bounces with "concierge commands aren't available yet." The command
        set is deferred (see tension Direct Daemon Concierge Channel,
        dc7kqn4v). Reserving the sigil now prevents a future concierge feature
        from colliding with thread-replies/broadcast or retraining daniel's
        muscle memory. Chose "." over "!" because "." is on the phone's main
        keyboard with no shift / no punct-mode toggle (daniel types one-handed
        on mobile), and the *nix dotfile convention (hidden/system) is an apt
        analogy for "infrastructure, not content." Chose a plain-text sigil
        over Discord native slash commands because "/" triggers Discord's
        slash-command autocomplete UI on mobile and confer registers no
        application commands.

    Terse Reply Vocabulary = decision:
      id: tv4nqk7p
      why: >
        To minimize daniel's reply burden (thumb-typing on mobile), the server
        instructions block documents a small recommended shorthand vocabulary
        the agent should interpret: e.g. "stop" = halt and await further
        instructions; "go"/"bj" = use best judgment and run to completion
        without further check-ins. Replies pass through VERBATIM — there is no
        daemon-side expansion machinery. Considered daemon expansion (terse ->
        full directive before the agent sees it): rejected because it would
        make the daemon AUTHOR meaning on the user's behalf, cutting against
        Spokesperson Abstraction Principle (vj4xqn7p, the daemon is a conduit),
        and would add a vocabulary/config surface to maintain. Since the agent
        is an LLM that understands natural language, a documented shared
        shorthand gets the terseness without machinery, and daniel is never
        locked to the vocabulary — he can always dictate something longer.

    Pending-Message Piggyback Hint = decision:
      id: pb7nqm4x
      why: >
        Partial mitigation of Unsolicited Input Is Pull-Only (pl7nqx4v).
        confer cannot push into a running agent (MCP is client-pull), so
        unsolicited input (broadcast / notify_reply / late_reply) waits in the
        agent's check_messages queue until the agent checks. Two cheap,
        mechanical mitigations raise responsiveness without changing the pull
        model:

        (1) Piggyback hint. Every confer-authored response string the agent
            already receives carries a "(N message(s) waiting — call
            check_messages)" suffix when the agent's queue is non-empty. The
            count rides the wire as a pending_count field on AskReply and
            AskTimeout; for notify it is folded into the existing free-form
            NotifyResult.info string. The hint rides only on confer-authored
            strings, never polluting the user's verbatim ask reply: on a real
            reply the count is appended as a clearly bracketed "[confer: N
            ...]" meta-note, visually distinct from the user's words. Every
            notify/ask the agent already makes thus becomes a checkpoint with
            zero dependence on the agent remembering to poll.

        (2) Event-anchored check nudge. The server instructions recommend
            calling check_messages at points the agent can actually detect —
            after any long operation, at the top of each work iteration,
            before any irreversible action — NOT on a wall-clock cadence,
            because an agent has no reliable sense of elapsed time between
            tool calls.

        Considered delivering the queued messages inline in the piggyback
        (not just a count): rejected to preserve consume-on-read (cm7vnpqx)
        and avoid double-delivery — the hint nudges, check_messages drains.
        Considered a "every N minutes" instruction: rejected (unobservable to
        the agent). Near-real-time interruption via a harness hook and gating
        risky actions behind ask(on_timeout="abort") are recorded as further
        mitigations under pl7nqx4v.

    # ─── NAMING ──────────────────────────────────────────────────────────────

    Naming = decision:
      id: qj4xm7pn
      why: >
        Python package: confer (matches repo). MCP server module: confer.server.
        Tool function names: notify, ask, check_messages. Considered tell /
        prompt, ping / await_reply, say / question. notify and ask are the
        natural English verbs for the actions ("notify the user I'm done",
        "ask the user for clarification") and daniel proposed them in the
        original design discussion. check_messages is descriptive and avoids
        the awkward inbox metaphor (there is no inbox — there's a DM channel).

    # ─── TEST STRATEGY ───────────────────────────────────────────────────────

    Two-Layer Test Strategy = decision:
      id: 7vpm2qkx
      why: >
        Two test layers. (1) Unit: mock discord.py at the Client / DMChannel.send
        / Client.wait_for boundary; no network; 100% branch coverage target;
        runs in CI on every push and PR. (2) Integration: gated behind env var
        CONFER_INTEGRATION=1; uses a real Discord test bot DMing daniel
        directly; not coverage-counted (see deviation Integration Tests Exempt).
        Considered three layers (unit + slice + integration): slice tests would
        mock at a lower level (HTTP), but discord.py already abstracts that
        cleanly — slicing below discord.py adds friction without benefit.
        Considered no integration tests: would let breaking Discord API changes
        ship undetected. Two layers is the minimum that covers the threat model.

        Testability addendum (review finding TST-F1/F3): the daemon's timing
        layer (timeout + re-ping loops) takes injectable clock and sleep
        callables (default time.monotonic / asyncio.sleep). Unit tests drive
        the loops in isolation with a fake clock/sleep so the production
        constants (the 60s skip-near-deadline window, the re-ping cadence)
        are exercised deterministically instead of via fragile wall-clock
        margins that flake on a loaded runner. The skip-near-deadline
        decision is also a pure helper unit-tested across the 60s boundary.

    Component Tier Real Socket Fake Transport = decision:
      id: c7nq4xkp
      why: >
        A fourth tier — "component" — sits between unit and integration and,
        unlike them, is deterministic, network-free, human-free, runs in CI,
        and DOES count toward the 100% coverage gate (it exercises only our
        own code). It refines Two-Layer Test Strategy (7vpm2qkx) into a
        taxonomy of four: unit -> component -> integration -> interactive
        (k4n7pqx2). It exists to close a real seam the other tiers leave open:
        the unit tests run the real serve()+socket but against a MOCKED
        transport, and the DaemonClient unit tests run the real client against
        a HAND-ROLLED fake daemon — so the real client and the real
        serve()/IPC layer are each only ever tested against a fake
        counterpart, never against EACH OTHER across the actual unix socket.
        The component tier wires the real Daemon + real serve() on a real
        tmp-dir socket to a real DaemonClient over that socket, faking ONLY
        the discord.py transport via the existing `transport=` constructor
        seam (the same seam the unit tests already use — no production
        test-only backdoor is added). The fake transport additionally exposes
        an inject(content) method that calls the daemon's on_user_message
        callback, simulating an inbound Discord DM. This lets the tier cover,
        deterministically and in CI, the one path that otherwise needs a live
        human (interactive tier) or cannot be reached at all (integration,
        since the bot cannot DM itself): inbound message -> route -> IPC ->
        client, i.e. a reply returning through ask() (next-message-wins,
        rt7nqp4m) and an unsolicited DM surfacing via check_messages. This is
        NOT the "slice layer" rejected in 7vpm2qkx: that rejection was about
        mocking BELOW discord.py at the HTTP level (friction, no benefit);
        here the fake sits AT the discord.py boundary while everything below
        the transport — process wiring, socket, framing, routing — is real.
        The tiers are complementary: component proves our wiring is correct
        and stays correct (in CI, free); integration remains the only catch
        for real discord.py API drift; interactive remains the only proof of
        the real end-to-end Discord UX. Lives in tests/test_component.py
        (under tests/, NOT tests/integration/) precisely because it is gate-
        eligible and must run by default, unlike the two opt-in tiers.

    Interactive Human-In-The-Loop Test Tier = decision:
      id: k4n7pqx2
      why: >
        A third, explicitly-manual test tier sits beside the unit and
        integration tiers of Two-Layer Test Strategy (7vpm2qkx). Some
        behavior cannot be exercised without a human acting on real Discord:
        the inbound on_message -> route path (a reply that next-message-wins
        delivers back through ask, an unsolicited DM that broadcasts into
        check_messages). The integration tier can only drive OUTBOUND calls
        (notify, the ask question DM, the timeout machinery) because the bot
        only accepts DMs whose author.id matches the configured user, so it
        cannot feed itself. These interactive tests live under
        tests/integration/ marked `interactive` and are gated behind a
        dedicated pytest flag, --interactive, kept SEPARATE from the
        integration tier's CONFER_INTEGRATION=1 env gate so a normal (or even
        a normal integration) run never blocks waiting on a person. Run them
        with `uv run pytest --interactive -s --no-cov tests/integration/test_interactive.py`;
        each test prints an ACTION REQUIRED prompt (to /dev/tty so it shows
        through pytest capture) telling the operator exactly what to send in
        Discord, then waits up to 180s. They are exempt from coverage for the
        same reasons as the integration tier (Integration Tests Exempt,
        gjx4m7p2). HOW/WHEN TO RUN: manually, at milestones and before a
        release, whenever the daemon's routing, the transport's inbound
        handler, or the client's ask/check_messages paths change — they are
        the only automated proof that a real human's Discord message reaches
        the right agent. A pytest flag was chosen over a third env var
        because the operator types this one by hand at an interactive
        terminal (where a CLI flag is the natural idiom), whereas
        CONFER_INTEGRATION is also inherited by the spawned daemon subprocess
        (which the --interactive flag need not be).

    Integration Freshness Gate = decision:
      id: m4xq7npk
      why: >
        The integration tier (5nqx7pmw) only catches Discord / discord.py API
        drift (Mock Depth, 4vxn7pqm) on the runs where someone actually types
        CONFER_INTEGRATION=1 — realistically rare and easy to forget, so drift
        could ship silently. This gate forces periodic live verification while
        the code is actively evolving, WITHOUT putting live-Discord tests on
        the push/PR gate (the flakiness Two-Layer Test Strategy, 7vpm2qkx,
        explicitly warns against). Mechanism: a checked-in stamp file,
        tests/integration/last-verified.txt, holds the ISO date the
        integration tier last passed. A normal-suite test
        (tests/test_integration_freshness.py) fails when that date is older
        than MAX_AGE (62 days ≈ two months). The stamp is refreshed
        automatically: a pytest_sessionfinish hook in tests/conftest.py writes
        today's date whenever the integration tier actually ran AND the whole
        session had zero failures (so a flaky/failed integration run never
        refreshes it). scripts/stamp-integration.py is a manual escape hatch
        for the same write, to be run only right after a green integration run.
        SCOPE — the gate bites only a machine equipped to satisfy it: it skips
        when CI is set (a scheduled CI run cannot be told to "go run live
        Discord tests") and skips when no real confer config is present (a
        no-creds contributor literally cannot run the integration tier, so
        failing their `uv run pytest` would be hostile). For daniel, who always
        has a config and runs locally, it is live. Determinism deviation: this
        is deliberately a time-dependent test that will go red with the mere
        passage of the calendar and zero code change — unusual for a test
        suite, and it means re-running an old commit (e.g. under git bisect) on
        an equipped machine can fail on freshness alone. Accepted: it is a
        forcing function, not a correctness check, and the tight scope keeps
        the blast radius to the maintainer's live checkout. Considered and
        rejected: (a) a scheduled CI "drift-canary" workflow that stores a
        Discord test-bot token in GitHub secrets and runs the integration tier
        nightly — rejected for now because it pushes a real credential into
        GitHub infra (against the no-data-leaves-the-machine stance) and pings
        a real account on a cron, heavier than the problem warrants while the
        repo is small; this lighter local gate gives most of the benefit at no
        secret-exfiltration cost. (b) warn-only on staleness — rejected as too
        easy to ignore; a hard fail is the point. (c) enforcing on every
        non-CI machine regardless of creds — rejected as hostile to drive-by
        contributors. The stamp helper logic lives in tests/freshness.py (not
        under src/, so it is outside the 100% production-coverage gate); the
        freshness test itself adds no production branches.

    # ─── OPEN TENSIONS ───────────────────────────────────────────────────────

    Pending Ask Lost On MCP Server Death = tension:
      id: 3nx7pq4m
      nature: >
        When the MCP client (Claude Code) exits or crashes while an ask is
        pending, the MCP server child process dies with it, closing the
        Discord Gateway connection. The user may not know an ask was pending;
        if they reply, the reply has nowhere to go. The proper fix is a
        separate daemon process holding the Gateway, with the MCP server
        reduced to a thin IPC shim — meaningfully more code and an operational
        footprint (user must keep a daemon running, likely under systemd
        --user or similar). For v1, accepted as a known gap.
      resolution: >
        Resolved by Orphan Ask Drop Policy (v4kn7mpq) under Asymmetric
        Robustness (wq7knm3p). The daemon outlives any individual MCP server
        but does not attempt to preserve in-flight ask state across agent
        failure. On socket close, pending asks for the dead server are
        dropped immediately and the user is notified once via "Lost contact
        with the agent that asked: *{question}*." The original draft of this
        resolution (1h retention + check_messages routing for orphan replies)
        was reversed in 2C after the Productivity While Away framing
        (pn4xvk2m) clarified that preservation across agent death is an
        explicit anti-goal — daniel restarts the agent locally and either
        re-asks or proceeds. The remaining failure surface — the DAEMON
        dying — is captured separately as Daemon Death Loses Pending State
        (nq7pxw4m).
      resolved-by: dh, 2026-05-28

    Proactive Messages Lost On Restart = tension:
      id: 4pjq7vmx
      nature: >
        check_messages keeps its last-seen-message cursor in process memory.
        When the MCP server restarts, the cursor is gone. Two possible
        implementation choices on restart (return all recent unread, OR
        return nothing until a new message arrives); both make the
        check_messages contract fuzzy across restarts. For v1, accepted
        because MCP server restarts are infrequent and daniel can re-send if
        a particular proactive message matters.
      resolution: >
        Resolved by Central Daemon Architecture (dq7n3xpk). check_messages
        queues are now daemon-resident, indexed by agent label. MCP server
        restarts no longer lose the cursor — the daemon outlives them. The
        remaining failure case (daemon itself dies before any MCP server has
        dequeued) is captured as Daemon Death Loses Pending State
        (nq7pxw4m).
      resolved-by: dh, 2026-05-28

    Reply Disambiguation When Proactive Arrives Mid-Ask = tension:
      id: rk2nq7pm
      nature: >
        If daniel sends an unprompted message between the bot's ask question
        and his actual reply (e.g., "one sec" followed by the real answer),
        next-message-wins captures "one sec" as the reply and the real answer
        either becomes the next-message-wins for the next ask, or surfaces
        via check_messages depending on timing. No clean disambiguation
        without forcing reply-to-message (rejected in Next Message Wins For
        Reply for mobile-dictation friction). A heuristic detector (very
        short message + another within N seconds = treat second as reply)
        was considered but has a wrong-answer cost: incorrectly merging two
        independent messages corrupts the agent's understanding of intent.
      revisit-when: >
        Daniel has been surprised by this behavior at least twice in real
        use, OR a Discord mobile UX signal emerges that lets the user mark
        "this is the reply" without adding friction (e.g., a long-press
        gesture or a single-tap reply-mode toggle).

    Mock Depth At discord.py Boundary = tension:
      id: 4vxn7pqm
      nature: >
        Testability Hawk (adversarial review 2026-05-28) noted that the
        discord.py boundary mock is shallow — discord.NotFound and
        HTTPException are instantiated against MagicMock responses, but no
        test verifies that fetch_user / create_dm / Client.start signatures
        haven't shifted. A discord.py minor-version bump that renames an
        API would not be detected by the unit-test suite.
      resolution: >
        By design per Two-Layer Test Strategy (7vpm2qkx). Mock-based unit
        tests verify our code's logic, not discord.py's contract; integration
        tests against a real Discord bot are the catch for upstream API
        drift. The deviation Integration Tests Exempt (gjx4m7p2)
        acknowledges this layering and exempts integration tests from
        coverage. The remaining concern — that integration tests do not yet
        exist on disk — is captured separately as Integration Tests Not Yet
        Implemented (5nqx7pmw).
      resolved-by: dh, 2026-05-28

    Integration Tests Not Yet Implemented = tension:
      id: 5nqx7pmw
      nature: >
        Two-Layer Test Strategy (7vpm2qkx) and the Integration Tests Exempt
        deviation (gjx4m7p2) describe an integration test layer gated behind
        CONFER_INTEGRATION=1 that hits a real Discord test bot. No
        integration tests have actually been written; the "two-layer"
        strategy is currently one layer. Testability Hawk (2026-05-28)
        raised this; it is also the strict precondition for closing the
        Mock Depth tension (4vxn7pqm).
      resolution: >
        Resolved 2026-05-29. The first integration tier landed under
        tests/integration/ as a CONFER_INTEGRATION=1-gated notify smoke test
        (test_notify_smoke.py). It reuses the real bot credentials
        (Settings.load() of the operator's actual config), copies them into a
        throwaway temp config, and points the auto-spawned confer-daemon at
        that temp file via CONFER_CONFIG (Config Path Override Via
        CONFER_CONFIG, w3kq7nxp) with XDG_RUNTIME_DIR / XDG_STATE_HOME
        isolated to a tmp dir so the test daemon's socket/pid/log never
        collide with a real running daemon. The test asserts notify() returns
        the "sent at <timestamp>" success sentinel; because serve() binds its
        socket only AFTER wait_for_ready() (the Gateway is up before the
        client can connect), a successful notify also proves
        gateway_state == ready. The suite is SKIPPED (not failed) when the
        integration flag or real config is absent, keeping it out of the
        coverage gate per Integration Tests Exempt (gjx4m7p2) and out of the
        default CI gate per Two-Layer Test Strategy (7vpm2qkx). The
        "two-layer strategy is currently one layer" gap is now closed for the
        notify path. The ask round-trip stays manual — a human reply cannot
        be scripted — and Mock Depth (4vxn7pqm) is correspondingly narrowed
        to the ask/check_messages surface. Running this tier in CI as a
        scheduled upstream-API-drift canary (with Discord test-bot secrets)
        is deliberately deferred as a separate opt-in decision, since forcing
        it into the push/PR gate is exactly the flakiness Two-Layer Test
        Strategy warns against.
      resolved-by: dh, 2026-05-29

    NDJSON Input Size Unbounded = tension:
      id: 7pqkn4vx
      nature: >
        Security Hawk (adversarial review 2026-05-28) observed that the
        daemon's _handle_client read loop uses asyncio's default 64 KiB
        StreamReader line limit and does not catch LimitOverrunError.
        A malformed oversized NDJSON line tears down the offending client
        connection without sending an Error diagnostic. Not exploitable
        under the single-user threat model, and Discord enforces a 2000-char
        cap on outgoing messages so legitimate traffic is bounded.
      revisit-when: >
        A future tool argument starts approaching the 64 KiB boundary
        (e.g., agent passing a large code block to a future ask tool), OR
        the daemon gains multi-tenant exposure and a misbehaving client
        could plausibly send oversized lines. Likely fix: catch
        LimitOverrunError / IncompleteReadError in _handle_client, send
        Error(code="bad_message", message="line too long"), close cleanly.

    MCP Resource For Usage Guide Pending = tension:
      id: 7nqxw4pj
      nature: >
        Notify Self-Description Policy (4kxp7qnj) accepts that the server
        instructions block plus tool and parameter descriptions cover the
        single notify tool adequately. As ask (phase 2C) and check_messages
        (phase 2D) land, the cumulative policy surface — reply routing
        rules, on_timeout fallback modes, when to broadcast vs. dispatch,
        label-prefix conventions, the empty-personal-guild gotcha — may
        grow past what fits in ~10 lines of instructions text. An MCP
        resource confer://usage-guide would house long-form guidance the
        agent can fetch on demand without bloating every system prompt.
      revisit-when: >
        The cumulative confer policy across notify + ask + check_messages
        exceeds ~15 lines of instruction text, OR a clean-Claude acid test
        post-2D shows agents misusing ask / check_messages in ways the
        instructions block did not catch.

    Notify Tool Name Reconsideration Pending = tension:
      id: 3pqvn7mw
      nature: >
        Adversarial review (G1) noted that "notify" connotes generic
        "log/event" semantics in many programming contexts (Linux
        notify-send, JavaScript Notification API, syslog, etc.) and may
        prime an agent to over-use it as a generic "tell the user"
        channel rather than the deliberate out-of-band ping it is. A more
        specific name (ping_user_offband, dm_user_async, alert_user) might
        reduce misuse independent of description quality. Notify
        Self-Description Policy (4kxp7qnj) defers the rename in favor of
        fixing description and instructions first, on the theory that a
        renamed tool with a bad description is still misused but a
        well-named tool needs less rescuing.
      revisit-when: >
        A post-fix acid test (gaps.md G2) shows a fresh Claude misusing
        notify in ways that better description did not catch, OR daniel
        observes notify misuse in real multi-agent use over a 2-week
        window.
      resolution: >
        Resolved (rename NOT needed) by the G2 acid test, 2026-05-29. A
        confer-naive subagent given only the agent-facing self-description
        scored 11/11 on a mixed notify/ask/check_messages discrimination
        battery, including the don't-use-confer cases. No name-priming
        misuse of "notify" appeared — the agent did not over-reach it as a
        generic "tell the user" channel. The bet in Notify Self-Description
        Policy (4kxp7qnj) — fix description before considering a rename —
        is validated; "notify" stays. Reopen only if real multi-agent use
        surfaces name-driven misuse the description cannot correct.
      resolved-by: dh, 2026-05-29

    Async Polling Loop Flakiness Risk = tension:
      id: 3vxm7qnp
      nature: >
        Testability Hawk (2026-05-28) observed that test_serve_* tests in
        test_daemon_core.py poll with `await asyncio.sleep(0.01)` for up to
        200 iterations (2 s budget) to wait for the daemon to bind. Ran
        cleanly 3x in the review's flakiness probe, but the pattern is
        timing-dependent and could flake under high CI load.
      revisit-when: >
        A CI run intermittently fails one of the test_serve_* tests. Likely
        fix: expose an asyncio.Event on Daemon for "ready to accept
        connections," set it after socket bind, and replace polling with
        `await asyncio.wait_for(event.wait(), timeout=5)`.

    Daemon Death Loses Pending State = tension:
      id: nq7pxw4m
      nature: >
        With Central Daemon Architecture (dq7n3xpk), the daemon process is
        the single point of failure for all in-flight ask state and all
        unread check_messages queues. If the daemon crashes (segfault, OOM,
        SIGKILL, system reboot without graceful shutdown), every pending ask
        across all connected MCP servers is lost; every queued unread
        message is lost. This is strictly better than the per-MCP-server
        failure mode it replaces (Pending Ask Lost On MCP Server Death,
        3nx7pq4m, now resolved) — one long-lived process is monitorable in a
        way that dozens of ephemeral ones are not — but is still a real loss
        surface. For v1, accepted with no persistence layer; recovery is
        manual (user notices the daemon died, restarts it via auto-spawn on
        the next MCP server invocation, re-sends any in-flight asks).
      revisit-when: >
        A daemon-death event has actually cost real work at least once, OR
        the project is being used heavily enough that periodic daemon
        restarts (e.g., for upgrades) cause visible friction. The likely fix
        when revisited: a small SQLite-backed state file in
        ${XDG_STATE_HOME:-$HOME/.local/state}/confer/state.db that the
        daemon writes-through on every state change and reads on startup to
        recover.

    CLI Answer Injection Pending = tension:
      id: 7pvkn4qm
      nature: >
        daniel comes back to his laptop where an agent is blocked in an ask
        waiting for a Discord reply he didn't see. He cannot answer locally
        because Claude Code can't accept input on the agent's behalf while
        inside the tool call. The only paths today are (a) reply via Discord,
        or (b) Ctrl-C the agent (losing context, defeating Productivity While
        Away). A future "confer answer <pending-id> '...'" CLI would route
        through the daemon's existing (label, content) reply ingestion path
        — explicitly designed to be channel-agnostic per Spokesperson
        Abstraction Principle (vj4xqn7p) — and unblock the agent without
        losing context. Phase 2C does not build this; the principle exists
        only to keep the ingestion seam shaped to accept it later.
      resolution: >
        Resolved in phase 3 by CLI Inject Tool (ci7n4pvm) — ahead of the
        original revisit-when criteria because daniel asked for phase 3
        work and CLI was the strongest intent-aligned fit. The
        Spokesperson Abstraction seam designed in 2C absorbed the new
        channel cleanly: the daemon's _dispatch_user_message accepts
        (label, content) from any source, and the CLI sends the same
        routing-rule-compatible content as a Discord DM would.
      resolved-by: dh, 2026-05-29

    Direct Daemon Concierge Channel = tension:
      id: dc7kqn4v
      nature: >
        daniel wants to address the daemon directly, not only the agents it
        intermediates: read queries ("what threads are open?", "how much time
        is left to respond?", "which model is active on that agent?", "how long
        has this agent been running?") and bulk commands ("say no to every
        thread", "tell all agents to go to sleep"). This is a distinct design
        surface — a control/observability channel spanning both the Discord DM
        channel (via the reserved "." sigil, Concierge Sigil Reservation
        cg7vnq4p) and the `confer` CLI (a natural home for the same
        queries/commands alongside the existing confer-daemon status). It
        overlaps daemon STATUS but is richer and partly mutating. Deferred in
        G3 to a stub bounce; the sigil is reserved so the grammar has room.
      revisit-when: >
        daniel has felt the absence in real use (wanting to query or steer the
        fleet without per-thread replies), OR the number of concurrent agents
        grows enough that bulk operations ("sleep all", "no to all") become a
        frequent need. Likely shape: a small verb set parsed after the "."
        sigil, read verbs reusing daemon state already exposed to STATUS, plus
        a few guarded mutating verbs that fan out to agents' inboxes.

    Unsolicited Input Is Pull-Only = tension:
      id: pl7nqx4v
      nature: >
        ask delivers the user's reply by PUSH — the agent is blocked waiting,
        so the reply returns synchronously with no announcement (the channel's
        headline promise). But unsolicited input — broadcasts, notify_replies,
        late_replies — sits in the agent's check_messages queue until the
        agent chooses to call check_messages. Nothing can inject into a
        running agent: MCP is client-pull, so confer cannot interrupt an agent
        that is mid-inference or mid-tool-execution and not calling a confer
        tool. A head-down agent will not see "stop, wrong track" until its
        next checkpoint. This bumps against Productivity While Away (pn4xvk2m):
        agents stay steerable only to the degree they check in.
      mitigations: >
        (a) SHIPPED — Pending-Message Piggyback Hint (pb7nqm4x): notify/ask
        responses carry a pending-count hint, and the instructions nudge
        event-anchored checks. Turns every existing confer call into a
        checkpoint. (b) DEFERRED, near-real-time — a Claude Code Stop or
        PreToolUse hook that calls check_messages between turns, moving the
        cadence decision to the harness (client-specific; consistent with
        Spokesperson Abstraction since confer stays a conduit). (c) USAGE
        CONVENTION — gate risky/irreversible actions behind
        ask(on_timeout="abort"), which is already push, so the highest-stakes
        moments are interruptible by construction. Hard ceiling: none of these
        interrupt an agent mid-execution; the best achievable is "noticed at
        the next checkpoint," and the mitigations only shrink the gap between
        checkpoints or move cadence to the harness.
      revisit-when: >
        A busy agent misses a time-critical interjection in real use and it
        costs work, OR daniel wants near-real-time steering enough to wire the
        harness hook. Likely next step: ship a documented Claude Code hook
        recipe plus a check-cadence convention.

    Policy-Backed Spokesperson Substitution Pending = tension:
      id: vkqmn7p4
      nature: >
        Spokesperson Abstraction Principle (vj4xqn7p) keeps the protocol
        open to a future in which some asks are answered by a policy engine
        or a secondary agent without involving daniel at all (recurring
        approvals, time-of-day rules, project-scoped defaults, sensible
        no-ops for routine clarifications). Phase 2C does not build any of
        this; the principle exists only to prevent the MCP layer from baking
        in assumptions that would block such a future.
      revisit-when: >
        A concrete set of questions a policy could safely answer without
        daniel's involvement emerges from real use (e.g., a recurring
        approval pattern across many similar asks), OR a second user-side
        responder (secondary agent, scripted handler) becomes desired.

    # ─── AWAY MODE ───────────────────────────────────────────────────────────

    Presence-Aware Away Mode = goal:
      id: aw7nqkp4
      why: >
        When daniel leaves his desk, every running — and every later-opened —
        Claude Code session should switch from waiting silently at the terminal
        to reaching him through the confer tools (ask / notify / check_messages),
        and switch back when he returns. The cost he is unwilling to pay is
        re-explaining himself: he will not retype an away instruction in each
        session, nor copy/paste it across a dozen windows. So the bar is: one
        command, run from any window, flips the policy globally; returning to
        the keyboard flips it back automatically. This promotes confer from
        "tools an agent may choose to use" to "a presence mode the human
        toggles." Latency inherits Confer's 2-3 min target (k7m3pq2x). The
        feature is realized by the decisions below: presence storage
        (pf4nqkx7), a toggle surface (tg7nqkp4, superseded by the away/back/
        status surface av7nkp4x), Stop-hook enforcement (eh7nqkp4), auto-return
        on keyboard input (ar7nqkp4), and an explicit installer (ii7nqkp4).
        Extended with scheduled away transitions (sq7nkp4x) so daniel can
        pre-arm away mode for known-future meetings, with an activation notice
        (cs7nkp4x) confirming each transition.

    Presence As A Workstation File = decision:
      id: pf4nqkx7
      why: >
        Presence — "is daniel at THIS workstation?" — is stored as a small
        file in XDG_RUNTIME_DIR (confer.presence): file present (JSON with an
        optional note + since-timestamp) means away, file absent means present.
        Considered the riffed alternative of holding presence as daemon
        in-memory state behind new SetPresence/GetPresence IPC: rejected. The
        enforcement point (eh7nqkp4) is a GLOBAL Claude Code Stop hook that
        fires on every session-stop daniel ever makes, confer-related or not;
        putting a Unix-socket round-trip to a daemon that often is not running
        on that hot path adds latency and a failure mode to thousands of
        unrelated stops, whereas a file stat is microseconds with no
        dependency. Presence is also a workstation-locality fact, not a
        Discord/messaging fact, so the daemon (whose single job is multiplexing
        the Gateway, dq7n3xpk) is the wrong home for it. File-exists semantics
        are atomic, and "XDG_RUNTIME_DIR clears on reboot" gives the correct
        default (a reboot means you are back at the machine). The daemon needs
        no presence knowledge for this feature: the agent, nudged by the hook,
        decides to call ask/notify; the daemon relays exactly as it always has.
        Cross-session sharing — the "cool enhancement" daniel assumed isolation
        would forbid — falls out for free, because XDG_RUNTIME_DIR is per-user
        shared for the same reason the central daemon (dq7n3xpk) is shared;
        isolation was never the obstacle. A daemon flag can still be added
        later if the daemon itself ever needs presence-aware behavior.

        REFINED by Scheduled Away Transitions (sq7nkp4x): the presence file is
        no longer a single binary fact (present/away) but current-state PLUS a
        small bounded queue of future away activations. The robustness argument
        above is preserved intact — the ENFORCEMENT read ("am I effectively
        away right now?") is still a pure function of the file plus the clock
        (effective-away = sticky-away OR any pending activation whose time has
        arrived), so the global Stop hook still does a dependency-free file
        stat with no daemon round-trip. Only the optional activation NOTICE
        (cs7nkp4x) needs a running daemon, and that is explicitly best-effort.

    Toggle Surface confer away/back/status = decision:
      id: tg7nqkp4
      why: >
        SUPERSEDED by Away Back Status Command Surface (av7nkp4x), which keeps
        the file-writes-shared-state-from-any-window core of this decision but
        (1) replaces the binary `confer presence` reader with `confer status`
        (a reader is a distinct verb from the away/back mutators — say what you
        mean), (2) makes `status` CLI-ONLY (a slash command only exists inside
        a session, where you are by definition at the keyboard and already know
        you are present, so an in-Claude status query is meaningless), and (3)
        adds the scheduling forms (away in/at, back at/all) of sq7nkp4x. The
        original rationale retained below for lineage.

        The toggle is `confer` CLI subcommands — `confer away [--note]`,
        `confer back`, `confer presence` — that read/write the presence file
        (pf4nqkx7) directly and never touch the daemon. One command from any
        window (or `! confer away` inside a session) flips global state.
        `--note` lets daniel leave a hint ("back after lunch") that the Stop
        hook can surface to agents. For in-session ergonomics, ii7nqkp4 also
        installs `/away` and `/back` slash commands as thin wrappers that run
        the CLI. Considered making the slash commands the primary surface:
        rejected as primary because a slash command only injects prompt text
        into one session, which is exactly the per-window friction the goal
        (aw7nqkp4) forbids; the CLI writing shared file state is what makes
        one command global.

    Enforcement Via Stop Hook = decision:
      id: eh7nqkp4
      why: >
        Enforcement is a global Claude Code `Stop` hook (`confer hook stop`),
        because the daemon cannot make a Claude session do anything — only the
        Claude Code side can. When away, on a session trying to end its turn,
        the hook blocks the stop (exit 2 with the instruction on stderr, the
        mechanism Claude Code feeds back to the model) telling the agent to
        reach daniel via confer — ask for a decision, notify if only reporting
        — instead of idling at a terminal nobody is watching. Loop safety is
        two-layered: (a) honor stop_hook_active — never re-block a stop that is
        itself the continuation of a prior block; (b) inspect the transcript
        and do not block if the agent already used an mcp__confer__* tool since
        the last human turn (it already reached out). The hook FAILS OPEN on
        every uncertain path — present, unparseable transcript, missing file,
        any exception → allow the stop — so it can never wedge unrelated,
        non-confer sessions; an opt-in away mode that occasionally under-nudges
        is acceptable, one that can hang every session on this machine is not.
        Considered enforcement via injected CLAUDE.md/AGENTS.md text (static,
        un-toggleable, fades after compaction, soft) and via a per-session
        slash-command instruction (the tier-A approach — still per-window and
        soft): both kept only as manual fallbacks. The Stop hook is the one
        mechanism that is simultaneously global, dynamically toggleable, and
        deterministic.

    Auto-Return On Keyboard Input = decision:
      id: ar7nqkp4
      why: >
        A `UserPromptSubmit` hook (`confer hook prompt`) clears presence to
        "present" whenever daniel types a prompt in ANY session — if he is at a
        keyboard, he is back, everywhere. This is safe precisely because Discord
        replies arrive through the confer MCP path (an ask's return value or
        check_messages), never through Claude Code's prompt input, so answering
        from his phone does NOT trip the hook; only real terminal typing does.
        The hook is side-effect-only: it runs `confer back` and exits 0 so the
        prompt proceeds unchanged. `confer back` remains for explicitly ending
        away mode without typing into a session. Considered requiring an
        explicit `confer back` always: rejected as needless friction given the
        keyboard signal is unambiguous and free.

        REFINED by Scheduled Away Transitions (sq7nkp4x): with a schedule
        present, "typing == confer back" is made precise — a keyboard prompt
        clears the CURRENT away and any already-FIRED schedule entry, but does
        NOT cancel still-PENDING future activations. This is the invariant that
        makes prompt-first ordering safe: daniel can schedule `away at 1100`,
        then keep typing into sessions, and the 11:00 activation still fires.
        The UserPromptSubmit hook therefore performs the same operation as bare
        `confer back` (present-now, pending-survive), not a full schedule wipe
        (that is `confer back all`).

    Integrations Installed Explicitly = decision:
      id: ii7nqkp4
      why: >
        The Stop and UserPromptSubmit hooks and the `/away` `/back` slash
        commands are written into ~/.claude/settings.json and
        ~/.claude/commands by an explicit `confer install-hooks` step (also
        offered as `confer setup --integrations`), never silently — because it
        mutates daniel's GLOBAL Claude Code configuration, which is too invasive
        to do as a side effect. The writer is idempotent (re-running never
        duplicates an entry) and MERGES into existing settings rather than
        clobbering other hooks, and it resolves `confer` to an absolute path so
        the hook runs regardless of the hook process's PATH. This composes with
        confer setup Subcommand (st7nqkp4). Considered auto-installing during
        `confer setup`: rejected — global-harness mutation must be opt-in.

    Scheduled Away Transitions = decision:
      id: sq7nkp4x
      why: >
        Away mode gains a bounded schedule of FUTURE activations, so daniel can
        say in advance "go away at 11:00" and "go away at 14:00" (meetings he
        knows about hours ahead) without remembering to do it at the moment.
        This exists to kill a fragility he hit directly: the only way to enter
        away "around" a task was to toggle it AFTER prompting (because a
        keyboard prompt clears away, ar7nqkp4) — an order-dependent ritual that
        is easy to get wrong. A pre-scheduled activation removes the ordering
        problem entirely: schedule first, work freely, away lands on time.

        State model. Presence (pf4nqkx7) becomes: a current sticky-away flag
        (with optional note + since) PLUS a list of pending entries, each an
        activation epoch + optional note. EFFECTIVE-AWAY, the only thing the
        Stop hook (eh7nqkp4) cares about, is a pure function of file + clock:
        sticky-away is true, OR some pending entry's time has arrived. So the
        hot-path read stays a dependency-free file stat — the robustness
        property of pf4nqkx7 is deliberately preserved. When a pending entry's
        time arrives it is "fired": from that instant effective-away is true;
        the entry can then be retired into the sticky-away flag (carrying its
        note) the next time any writer touches the file, or simply remain in
        the list as an arrived entry — both yield the same effective-away, and
        the activation notice (cs7nkp4x) handles the user-visible signal.

        Time inputs (av7nkp4x covers the command words): `at <HHMM>` means that
        clock time today, or — if it has already passed — the same time
        TOMORROW. This single rule gives the 24h cap for free: tomorrow-at-an-
        earlier-clock-time is by definition under 24h out, and no input can
        name a moment more than 24h ahead. Deliberately NOT a general calendar:
        no dates, no recurrence, nothing beyond 24h, no persistence across a
        reboot (XDG_RUNTIME_DIR clears — consistent with pf4nqkx7's "reboot
        means present"). This is an ephemeral same-day/overnight convenience,
        not a standing away calendar — daniel explicitly does not want a
        permanent schedule.

        Cancellation semantics (the `back` verbs, surfaced in av7nkp4x):
        - bare `back` / typing a prompt: become present NOW. Clears sticky-away
          and discards any already-FIRED entry, but LEAVES pending future
          entries (the ar7nqkp4 invariant). So typing at 10:50 makes you
          present; an 11:00 entry still fires.
        - `back at <HHMM>`: cancel the one PENDING entry matching that time. If
          none matches (typo, or it already fired), say so explicitly and list
          what is pending — never a silent no-op.
        - `back all`: the big hammer — clear current away AND wipe the entire
          pending queue (clean slate).
        Considered making typing wipe the whole schedule (consistent with the
        old binary clear): rejected — it would re-introduce the exact ordering
        fragility this feature removes, since the task prompt would cancel the
        away you just scheduled.

    Away Back Status Command Surface = decision:
      id: av7nkp4x
      why: >
        The user-facing surface is two MUTATORS and one READER, named so each
        word says exactly what it does:
          away   (enter away)   — now | `in <min>` | `at <HHMM>` ; optional --note
          back   (leave/cancel) — now | `at <HHMM>` | `all`
          status (report)       — current state + the pending schedule
        `away` and `back` are imperatives that change state; `status` only
        reads. They are kept separate verbs precisely because overloading a
        mutator to also answer "what is my state?" muddies meaning — an earlier
        draft folded the query into `away when`, rejected for that reason.
        Immediate `away` is the `in 0` / activate-now case, so the existing
        zero-arg behavior is unchanged and backward compatible.

        Surface split by reachability: `/away` and `/back` are installed as
        slash commands (in-Claude) AND exist as CLI subcommands; `status` is
        CLI-ONLY. Rationale: a slash command only exists inside a Claude
        session, and if daniel is typing inside Claude he is at the keyboard
        and therefore present — an in-session status query is meaningless. He
        needs status exactly when he is AWAY from Claude, which is the terminal
        (`confer status`). So no `/status` slash command and no status.md is
        written by ii7nqkp4; the installer continues to emit only away.md and
        back.md. The slash commands remain thin wrappers that pass their
        arguments through to the CLI (so `/away at 1100` works), keeping the
        CLI the single source of behavior (tg7nqkp4 lineage).

        `confer status` output shows the current state on the first line
        (present, or away with note) followed by any scheduled activations with
        their times and notes; empty schedule prints just the current state.

    Away Activation Notice = decision:
      id: cs7nkp4x
      why: >
        When a scheduled away (sq7nkp4x) transitions from pending to active,
        daniel gets a Discord DM — "confer: Now in away mode" plus the entry's
        note if any — so he has positive confirmation it engaged. This is the
        signal he asked for, and the DM (not a terminal print) is the right
        channel because by activation time he has walked away from the keyboard;
        the phone is where he is looking. It also doubles as a free liveness
        check of the Discord path. Mechanism: a lightweight presence-watch task
        in the daemon polls the presence file on a coarse cadence (~15s, well
        inside the 2-3 min latency target k7m3pq2x) and, on observing a
        pending→active transition it has not yet announced, sends the DM and
        records that it announced it (in-memory). At-most-once is best-effort,
        not guaranteed (see deviation nd7nkp4x). Considered firing the DM from
        the CLI/hook write path instead of the daemon: rejected — the
        transition happens at a wall-clock TIME with nothing necessarily
        executing then (the whole point is daniel is not interacting), so only
        a running watcher can observe it; the CLI that SCHEDULED it exited
        minutes earlier.

      children:

        Activation Notice Requires Live Daemon = deviation:
          id: nd7nkp4x
          deviates-from: cs7nkp4x
          scope: >
            The pending→active activation DM (cs7nkp4x) is delivered only if
            the daemon is running at the activation time, and is at-most-once
            only within a single daemon lifetime — a daemon restart around the
            transition may drop the notice, or (less likely) re-announce once.
          why: >
            Unlike away ENFORCEMENT, which is a daemon-independent file stat on
            the Stop-hook hot path (pf4nqkx7 / sq7nkp4x) and so always works,
            the activation NOTICE is an active push that intrinsically needs a
            live watcher at a specific wall-clock moment. Guaranteeing it would
            require durable, restart-surviving delivery state and a wakeup
            mechanism — disproportionate for a convenience confirmation whose
            absence costs only that daniel does not get a "you are now away"
            buzz (away still correctly engages regardless). Accepted as
            best-effort; the enforcement guarantee is the one that matters and
            is unaffected.
          approved-by: daniel, 2026-05-29

    Away State Not Observable Mid-Turn = tension:
      id: ax7nqp4k
      nature: >
        A live experiment tried to have the agent PROBE whether away mode was
        active during its turn — via check_messages, the return value of a
        notify call, and listMcpResources — and could not. This is structurally
        impossible by current design, not a bug: away mode is enforced ONLY by
        the global Stop hook at turn-end (eh7nqkp4); there is no MCP tool or
        resource that exposes away-state, so listMcpResources returned empty and
        a successful notify does not reveal the mode. The agent behaved
        correctly and hedged honestly about not knowing. The consequence to
        record: any test, prompt, or workflow that assumes the agent can query
        away-state mid-turn cannot work against the current architecture — the
        only observable manifestation of away mode is the stop-time nudge
        itself. See the design fork (vk7nqp4x) for whether to change this; cross-
        reference eh7nqkp4.

    Queued Away Slash Command Never Fires And Is Unsafe = tension:
      id: bz7nkp4q
      nature: >
        In Claude Code, a slash command typed while the agent is mid-turn does
        not execute then — it sits in the input queue and fires only AFTER the
        turn completes. In the experiment the agent never completed its turn
        (long sleep plus probing, effectively stuck), so a `/away` typed to arm
        away mode stayed pending the entire ~4 minutes and never set away mode at
        all. This is Claude Code harness behavior, not a confer bug, but it means
        `/away` cannot be relied on to arm away mode while an agent is working.
        WORSE, it is a latent SAFETY hazard: a queued `/away` that finally
        dequeues AFTER daniel has typed a return prompt (which set him present
        via ar7nqkp4) would silently flip him back to away while he is actually
        present at the keyboard. This is strong motivation for arming away from
        an EXTERNAL shell (or via scheduled-away, sq7nkp4x) rather than an
        in-session slash command, and is direct evidence that the manual
        prompt-driven toggle ordering is inherently fragile. Cross-reference
        ar7nqkp4 and sq7nkp4x.

    Correct Manual Away-Test Procedure = tension:
      id: dm7nkp4r
      nature: >
        Recorded as intent so the experiment procedure is not re-derived wrongly
        next time. Because typing a prompt into the Claude session fires the
        UserPromptSubmit hook and clears presence to present (ar7nqkp4), you
        CANNOT arm-away-then-type-the-task — the task prompt would immediately
        cancel the away you just set. The only ordering that works with the
        current code is: (1) type the short task into the session — this must be
        the LAST keyboard action in that session; (2) let the agent start
        working; (3) from an EXTERNAL shell run `confer away` while the agent is
        mid-turn, where nothing clears it; (4) do not touch that session's
        keyboard again; (5) the agent finishes, tries to stop, and the Stop hook
        fires the nudge — THIS nudge is the entire observable behavior of away
        mode; (6) return deliberately via a prompt or `confer back`. A LONG
        teed-up task actually HIDES the effect, because the agent never tries to
        stop and so the Stop hook never fires. This fragility is exactly what
        scheduled-away (sq7nkp4x, whose "typing does not cancel a pending entry"
        invariant removes the ordering dependence) exists to eliminate.

    Should Away-State Be Made Agent-Visible = tension:
      id: vk7nqp4x
      nature: >
        OPEN DESIGN FORK — unresolved, for daniel to decide later, adjacent to
        the scheduled-away work. The experiment assumed away-state should be
        queryable by the agent; today it deliberately is not (ax7nqp4k). There
        are two legitimate paths.

        EXPOSE it: make away-state agent-visible — e.g. as an MCP resource, or
        folded into the check_messages return value, or surfaced in tool
        descriptions — so the agent can SEE the mode and proactively adapt
        (prefer ask/notify, batch its reporting differently, avoid idling)
        rather than only being reactively nudged at stop-time. Upside: the agent
        cooperates with the policy instead of being caught by the hook after the
        fact; mid-turn behavior can improve.

        KEEP it invisible (the current hook-only design, eh7nqkp4): away mode is
        a human-side POLICY enforced by the harness, not a fact the agent should
        reason about. Upside: making it agent-visible invites agents to reason
        about — and potentially around — the mode, adds MCP surface, and couples
        agent behavior to a workstation-locality fact (pf4nqkx7) the agent has
        no business depending on. The Stop hook already guarantees the behavior
        without the agent knowing why.

        Left UNRESOLVED on purpose. Cross-reference eh7nqkp4, ax7nqp4k, and
        sq7nkp4x.

    Stop Hook Re-Nudges After Agent Reaches Out = tension:
      id: lp7nkq4x
      nature: >
        Bug found during the 2026-05-29 shakedown. The Stop hook's "already
        reached out" loop guard (eh7nqkp4 layer b) is defeated essentially
        every time. _confer_tool_used_since_last_user scans the transcript for
        an mcp__confer__* tool_use AFTER the last line whose type == "user" —
        intending "since the last human turn". But in the Claude Code JSONL
        transcript a tool_RESULT is also recorded as a message with
        type == "user" (verified directly: an assistant tool_use line is
        followed by a type=="user" line carrying a tool_result content block).
        So the agent's own notify/ask produces a tool_result that advances the
        "last user" marker PAST the confer tool_use, the scan then finds no
        confer call after it, and the hook concludes "hasn't reached out" and
        nudges again — even though the agent just did. Observed: the agent sent
        a clean notify, then on stop was told to notify AGAIN. Blast radius is
        bounded (the stop_hook_active guard, layer a, still prevents an
        infinite loop), so the symptom is one redundant nudge / a double DM,
        not a hang — but it undermines the property that makes away mode
        pleasant rather than nagging.
      resolution: >
        Resolved 2026-05-29. The guard must key off the last GENUINE human
        prompt, not the last type=="user" line. A real human turn is a
        type=="user" message whose content is NOT composed solely of
        tool_result blocks (a human prompt carries text/other blocks; a
        tool-result envelope carries only tool_result). _confer_tool_used_since_
        last_user now finds the last such genuine-human message and scans after
        it, so an agent's own tool_result no longer resets the window. Unit
        tests reproduce the tool_result-as-user transcript shape across the
        boundary. Fail-open behavior (eh7nqkp4) is unchanged: any
        read/parse/shape ambiguity still returns True (treat as reached-out,
        do not block).
      resolved-by: dh, 2026-05-29

    Hook Logging Leaks To Stderr As Stop Hook Error = tension:
      id: hk7nqp4m
      nature: >
        Bug found during the 2026-05-29 shakedown. On WSL2, XDG_RUNTIME_DIR is
        exported but /run/user/<uid> is not writable, so paths.py emits a
        log.warning about falling back to XDG_STATE_HOME (correct, non-fatal
        behavior). But the `confer hook stop` entrypoint never configures
        logging, so Python's last-resort handler prints that WARNING to stderr
        — and the Stop hook ALSO uses stderr to deliver its nudge (exit 2 +
        stderr is the channel Claude Code feeds the model, eh7nqkp4). Claude
        Code merges the two and labels the whole thing "Stop hook error",
        making every hook invocation look like a failure when nothing failed;
        in the shakedown the away agent even forwarded the warning to daniel as
        a scary "diagnostic". The fallback itself is fine (pf4nqkx7 / paths.py);
        only the noise on the hook's stderr is the problem.
      resolution: >
        Resolved 2026-05-29. The `confer hook` entrypoint silences logging
        (raises the threshold above WARNING / attaches a null handler) before
        invoking the hook logic, so the hook process emits ONLY its intended
        stderr payload — the nudge text for stop, nothing for prompt. The
        XDG-fallback warning is still available on the daemon/CLI paths that DO
        configure logging; it is suppressed only on the hook hot path where its
        sole effect was to masquerade as an error.
      resolved-by: dh, 2026-05-29

    XDG Fallback Warning Floods The Daemon Log = tension:
      id: wq4n7pxv
      nature: >
        Follow-on to hk7nqp4m, found 2026-06-06 reviewing the live log. The
        XDG-fallback warning that hk7nqp4m deliberately KEPT on the
        logging-configured (daemon/CLI) paths is emitted by paths._xdg_runtime_
        dir() on EVERY call, and the activation-notice watcher
        (_presence_watch_loop, cs7nkp4x) calls read_presence() → presence_file()
        → _xdg_runtime_dir() every 15s for the daemon's whole lifetime. On WSL2
        (XDG_RUNTIME_DIR set but /run/user/<uid> not writable, pf4nqkx7) this
        means the same correct, non-fatal warning is written ~4x/min forever.
        Observed: 44,085 of 44,540 lines (99%, ~7MB over ~9 days) were this one
        warning. The fallback is fine; the per-call cadence is the defect. It
        defeats the operator's read-the-log workflow — `confer-daemon status`'s
        "last 20 log lines" (5jpxnq7w) showed nothing but this warning — and
        churns the RotatingFileHandler so real events age out of the kept
        window within hours.
      resolution: >
        Emit the XDG-fallback warning AT MOST ONCE per distinct
        XDG_RUNTIME_DIR value per process, via a module-level set of
        already-warned values in paths.py. First fallback for a given value
        warns (preserving hk7nqp4m's "still available on configured paths"
        intent — the diagnostic is not lost); subsequent calls for the same
        value are silent. Keyed by the value string (not a bare boolean) so a
        genuinely changing env across the process still surfaces once each.
        Rejected: (a) dropping the warning entirely — hk7nqp4m's intent was to
        KEEP it where logging is configured, only suppress it on the hook hot
        path; (b) moving the warning to daemon startup only — paths.py is the
        single chokepoint and has no startup hook, and the per-value dedup is
        simpler and also covers the CLI paths; (c) raising the presence-poll
        interval — treats the symptom (poll cadence) not the cause (warn
        cadence) and would slow activation notices (cs7nkp4x).
      resolved-by: dh, 2026-06-06

    # ─── DISTRIBUTION ────────────────────────────────────────────────────────

    Distribute Via uv tool install = decision:
      id: db7nqkx4
      why: >
        confer is distributed as a uv tool: `uv tool install confer` (or a
        git URL until PyPI publish) places all three console_scripts —
        confer, confer-server, confer-daemon — on PATH in one managed
        environment. This is what makes the existing architecture
        distribution-ready with zero new runtime code: the daemon auto-spawn
        (7xj4mvqn) PATH-resolves confer-daemon via shutil.which, and all
        runtime state is XDG-based (config at ~/.config/confer/config.toml,
        hq7x3npm), so nothing assumes a git checkout or `uv run`. Any user
        gets a working install with no clone and no maintainer access. uv is
        already the project's chosen toolchain (Stack Selection, w3f5qkc2),
        so this adds no new dependency. Considered and rejected: (a) a
        hand-rolled Python zipapp one-liner installer — reinvents what
        `uv tool install` already does, fights confer's genuinely native-ish
        dependency tree (discord.py, mcp), and yields only ONE entry point
        when the daemon model needs THREE durably on PATH; (b) uvx ephemeral
        (`uvx confer-server`), the trendy MCP-server pattern — it BREAKS
        confer specifically, because the ephemeral env is torn down and never
        installs confer-daemon durably on PATH, yet the daemon is a
        persistent singleton meant to OUTLIVE every MCP server (Central
        Daemon Architecture, dq7n3xpk), so auto-spawn cannot reliably resolve
        it; (c) pipx — works, but uv is already chosen. Tier-0 path is
        available immediately with no new infra:
        `uv tool install git+https://github.com/dhh1128/confer` unblocks a
        second dev machine and non-maintainer friends today, before any PyPI
        publish.

    PyPI Trusted Publishing = decision:
      id: pp4nqvx7
      why: >
        Tier 1: publish confer to PyPI via a GitHub Actions OIDC trusted
        publisher, so the install shortens to `uv tool install confer` (no
        git URL) and uvx-style discovery works for clients that want it,
        layered on Distribute Via uv tool install (db7nqkx4). Publishing is
        OUTWARD-FACING and IRREVERSIBLE — a released version or name cannot
        be cleanly retracted — so the actual publish, the PyPI-side
        trusted-publisher configuration, and confirming the `confer` name is
        available on PyPI are MANUAL steps left to daniel. Nothing in the
        repo auto-publishes without an explicit tagged release he creates;
        the workflow fires only on a tag he pushes deliberately.

    Automated PyPI Publishing Disabled Until Owner Authorizes = decision:
      id: pn7qvk4x
      why: >
        Supersedes the active wiring of PyPI Trusted Publishing (pp4nqvx7).
        On 2026-06-06 daniel stated he never authorized, requested, or
        configured any PyPI publishing and was surprised to find publish.yml
        present — so the prior node's reassurance that "nothing auto-publishes
        without a deliberate tag" was hollow: scripts/release.py pushes a v*
        tag as its normal final step, and publish.yml triggers on `push:
        tags: ["v*"]`, so a routine `release.py` run WOULD have set off a PyPI
        upload attempt. That coupling (release = bump+tag, tag = publish) made
        publishing an implicit side effect of versioning, which is exactly
        what daniel did not authorize. Resolution: the publish workflow is
        neutered by renaming it to publish.yml.disabled so GitHub will not
        load it for ANY event — there is no longer a code path from a tag (or
        anything else) to a PyPI upload. scripts/release.py is retained but is
        now purely a version-bump-and-tag tool; its docstring/output and the
        README/usage docs are corrected to stop claiming a tag publishes to
        PyPI. Re-enabling is a deliberate, owner-only act gated on ALL of:
        (a) daniel decides the code is mature enough to publish; (b) he claims
        an available PyPI project name (the bare `confer` name is already
        taken by an unrelated project, so a different name is required); (c)
        the one-time trusted-publisher + `pypi` environment setup is done; and
        (d) the deferred DevOps review findings on this path are addressed —
        SHA-pin pypa/gh-action-pypi-publish (was @release/v1, a mutable branch,
        review F1) and add a CI test gate before publish (review F2). Rejected
        deleting publish.yml outright: daniel may publish eventually, and the
        file (with its one-time-setup header) is the cheapest way to preserve
        that wiring for a future deliberate re-enable; .disabled is fully
        reversible with a single rename. Rejected leaving it on a
        workflow_dispatch-only trigger: a manual run could still attempt a
        publish, which is weaker than "absolutely neutered."

    confer setup Subcommand = decision:
      id: st7nqkp4
      why: >
        Tier 2: a `confer setup` CLI subcommand performs the post-install
        ceremony in one step — scaffold and chmod 600
        ~/.config/confer/config.toml (hq7x3npm), accept and validate the
        Discord bot token and confer_user_id, and optionally register the MCP
        server with Claude Code (`claude mcp add confer -- confer-server`).
        This is the genuinely valuable custom piece, and it is built as a
        confer subcommand ON TOP OF uv (db7nqkx4) — NOT as a separate zipapp
        installer (rejected for the same reasons recorded there). It replaces
        the current manual mkdir/cp/chmod/claude-mcp-add steps with a single
        guided command, reducing first-run friction without coupling confer
        to a bespoke installer.

    # ─── REVIEW-PANEL FINDINGS (post-G3, 2026-05-29) ─────────────────────────
    # The four-persona review-panel over confer@main surfaced these; the
    # recommend-fix items were fixed in code. The deferred / accept-risk items
    # are recorded here so they are tracked rather than lost.

    Local Inject Is Forgeable = tension:
      id: rv7knqp2
      nature: >
        Review SEC-F1. The CLI inject path (Inject / ListAsks) is HELLO-exempt
        and authenticated only by Unix-socket file permissions, so any local
        process that can open the socket can forge user messages to agents
        (reply to asks, broadcast).
      resolution: >
        Accepted within the recorded single-user threat model: IPC Protocol
        NDJSON Over Persistent Unix Socket (kp5w2nfx) makes file permissions
        (0600, user-owned) the access control by design — a hostile local
        process running as daniel already has full reach. No in-band auth
        token is added.
      revisit-when: >
        confer ever runs on a shared/multi-user host, or the socket is exposed
        beyond the owning user — at which point an in-band capability token on
        Inject/ListAsks (and HELLO) is warranted.
      resolved-by: dh, 2026-05-29

    Daemon Log And State Dir Perms = tension:
      id: lp7nqkx4
      nature: >
        Review DEV-F5. The daemon log and state directory are created with
        default umask perms, so DM content written to the log can be readable
        by other local users on a multi-user box.
      resolution: >
        Accepted within the single-user threat model (same basis as rv7knqp2
        / kp5w2nfx). The socket itself is already forced to 0600; the log/state
        dir perms are the lower-stakes sibling.
      revisit-when: >
        Shared-host deployment, OR the log is found to contain material more
        sensitive than already-sent DM text. Likely fix: create the state dir
        0700 and the log 0600 explicitly.
      resolved-by: dh, 2026-05-29

    DM Content Is A Prompt-Injection Surface = tension:
      id: pj7nqmx4
      nature: >
        Review SEC-F3. Discord DM content flows verbatim into agent context,
        gated only by author.id matching the configured user. A compromised or
        spoofed-content path could inject instructions an agent then acts on.
        This is largely inherent to the tool's purpose (relaying the user's
        words to the agent), but it is a real surface worth naming.
      revisit-when: >
        confer relays content from any source other than the single trusted
        user (policy engine, secondary agent, group channel — see vj4xqn7p /
        vkqmn7p4), at which point inbound content needs treating as untrusted
        data rather than trusted instructions.

    CI Actions Not SHA-Pinned = tension:
      id: aq4nvx7p
      nature: >
        Review SEC-F2. GitHub Actions in ci.yml / copilot-review-gate.yml are
        referenced by mutable tag (e.g. @v6, @v7), not pinned to a commit SHA,
        so a compromised or retagged upstream action could run in CI.
      revisit-when: >
        The repo handles anything more sensitive in CI than running tests, OR
        a supply-chain policy is adopted. Likely fix: pin each action to a
        full commit SHA with a version comment, and let dependabot (DEV-F2,
        now configured) bump the pins.
      resolution: >
        Resolved by Pin CI Actions To Commit SHAs (shp4nqx7), 2026-06-03. Every
        `uses:` in ci.yml and publish.yml is pinned to a full 40-hex commit SHA
        (resolved authoritatively via git ls-remote against the upstream repo)
        with a trailing `# vN` comment; persist-credentials: false is set on
        checkout; and the dependabot github-actions ecosystem entry is grouped
        so SHA+comment bumps arrive as one PR. (copilot-review-gate.yml has no
        `uses:` references — it shells out to gh/jq only — so nothing to pin
        there.)
      resolved-by: daniel, 2026-06-03

    No Secret-Scanning Gate = tension:
      id: ss4kqnv7
      nature: >
        Review DEV-F4. Neither CI nor the pre-commit hook scans for committed
        secrets or invisible-Unicode payloads, so an accidental token commit
        or a hidden-character injection would not be caught automatically —
        notable for a tool that holds a Discord bot token.
      partial-resolution: >
        The invisible-Unicode half is resolved by Invisible-Unicode CI Gate
        (uc7nqx4p), 2026-06-03: scripts/check_unicode.py runs as a CI job and
        rejects the GlassWorm / Trojan-Source character classes. The
        secret-scanning (gitleaks-or-equivalent) half remains OPEN.
      revisit-when: >
        A near-miss occurs, OR the project gains external contributors. Likely
        fix: a gitleaks (or equivalent) CI step and a pre-commit hook addition.

    Successful Reply Routing Is Silent = tension:
      id: sr4nqpv7
      nature: >
        Review UX-F1. Delivered / broadcast / notify-reply outcomes produce no
        Discord acknowledgement, so an away user can't tell their dictated
        reply landed (or landed on the right thread), in mild tension with
        Acknowledge Actionable State Changes (qn7pkm4v). The agent's follow-up
        action is a plausible implicit ack, so this is a product call, not an
        automatic fix.
      revisit-when: >
        A real away-from-keyboard session shows daniel re-sending or asking
        "did that go through?", OR a mis-prefixed reply silently hits the
        wrong thread. Likely fix: a brief reaction/ack DM on successful routing
        (weighed against the no-noise intent of qn7pkm4v).

    Expired Tag Reply Has No Bounce = tension:
      id: et7knqp4
      nature: >
        Review UX-F4. A "re <tag>" to an evicted/closed notify thread (per the
        per-label cap or post-disconnect drop in Notify Replyable Threads,
        nr4kpq7v) matches nothing and falls through to generic routing
        (broadcast / lone-ask) or the generic no-agents bounce; the user
        cannot distinguish an expired tag from a typo.
      revisit-when: >
        Notify-thread eviction or post-disconnect tag replies become common
        enough to confuse in practice. Likely fix: a thread-specific bounce
        ("that thread is no longer open") when a tag-shaped token matches no
        active thread.

    # ─── SUPPLY-CHAIN HARDENING (2026-06-03) ─────────────────────────────────
    # A portable supply-chain hardening pass against the dominant 2026 attack
    # classes: GlassWorm / Trojan-Source (invisible & bidi Unicode), mutable-tag
    # GitHub Actions (tj-actions / Megalodon), and PATH/binary hijack. Each fix
    # is minimal and non-breaking; the operational controls that need owner/admin
    # rights (branch protection, token scoping, secret-scanning push protection)
    # are recommended to daniel out-of-band, not applied here.

    Invisible-Unicode CI Gate = decision:
      id: uc7nqx4p
      why: >
        Add a stdlib-Python scanner (scripts/check_unicode.py) wired into CI as
        its own job that rejects ONLY the dangerous Unicode categories — bidi
        controls (U+202A–202E, U+2066–2069), directional marks (U+200E/200F/
        061C), zero-width / invisible code points (U+200B–200D, U+2060, U+FEFF,
        U+00AD), variation selectors (U+FE00–FE0F, U+E0100–E01EF), tag chars
        (U+E0000–E007F), and Private Use Areas. These defeat human review by
        rendering as nothing (GlassWorm) or reordering how source reads vs. how
        it executes (Trojan Source), so an automated gate is the only defense.
        A naive ASCII-only rule was REJECTED: confer's this.i and docs
        deliberately use em-dashes, arrows, and box-drawing rules, and the gate
        must not flag honest non-ASCII. Stdlib Python (zero new dependency, ships
        on GitHub runners) was chosen over an ESLint/cargo native lint because
        confer is Python and the same script doubles as a local/pre-commit check.
        Resolves the invisible-Unicode half of No Secret-Scanning Gate
        (ss4kqnv7); the secret-scanning (gitleaks) half stays open there. The
        scanner lives under scripts/ — outside the confer package — so it sits
        outside the 100% production-coverage gate (like tests/freshness.py), but
        carries its own test (tests/test_check_unicode.py) that plants a
        dangerous code point via chr() escapes (never a literal invisible
        character) and asserts honest glyphs pass.
      approved-by: daniel, 2026-06-03

    Pin CI Actions To Commit SHAs = decision:
      id: shp4nqx7
      why: >
        Pin every GitHub Actions `uses:` reference to a full 40-hex commit SHA
        with a trailing `# vN` comment, resolved authoritatively from upstream
        (git ls-remote / gh api — never from memory), rather than a mutable tag
        (@v6, @v7) or branch (@release/v1). A mutable tag/branch can be silently
        retargeted to malicious code (the tj-actions / Megalodon class); a SHA
        cannot. The pinned releases were also checked to run on the node24
        action runtime (checkout v6.0.3, setup-uv v7.6.0; gh-action-pypi-publish
        is a composite action), avoiding the deprecated-node20 warning. Set
        persist-credentials: false on checkout so the job's GITHUB_TOKEN is not
        left in the checkout's git config for later steps. The dependabot
        github-actions ecosystem entry is grouped (groups.actions.patterns
        ["*"]) so SHA+comment bumps arrive as a single PR and the pins stay
        current without manual drift. Resolves CI Actions Not SHA-Pinned
        (aq4nvx7p).
      approved-by: daniel, 2026-06-03

    Resolve External CLI Binaries To Absolute Paths = decision:
      id: bpr7nqx4
      why: >
        At each site that spawns an external CLI by bare name, resolve the name
        to an absolute path via shutil.which and invoke the resolved path.
        confer-daemon (_spawn_daemon) and claude (_register_with_claude) already
        resolved the path — _spawn_daemon even LOGGED it "so a PATH-shadow attack
        is visible in retrospect" — but then discarded it and re-spawned the bare
        name, so the binary actually exec'd could differ from the one resolved
        and logged (a PATH-hijack window, and the retrospect log was misleading).
        git (_detect_repo_and_branch) is resolved the same way for consistency.
        Where the name does not resolve, fall back to the bare name: an
        unresolvable name has nothing on PATH to substitute, and all three sites
        already degrade gracefully (daemon spawn fails as before, claude prints
        the manual command, git falls back to a detached label). No shell=True
        and no string-concatenated commands are introduced — every call stays
        argument-vector form. scripts/release.py (a maintainer-only local script
        that shells out to bare `git`) is intentionally left as-is: it is not
        runtime/shipped code and runs only in daniel's trusted shell.
      approved-by: daniel, 2026-06-03

    # ─── PROMPT AUDIT HISTORY ────────────────────────────────────────────────

    Prompt Audit History = constraint:
      id: vp4nm7qx
      why: >
        Tracks last-run dates and finding summaries for adversarial-review
        personas AND the self-description acid test, so gate ceremonies can
        identify overdue audits and recommend them before gate closes.
        Introduced at the phase 2B gate, after the first adversarial review.
        Cadence "every-3-phases" is a starting heuristic; adjust based on
        whether findings density grows or shrinks over time. The
        self-description acid test (self-description-acid-test below) is part
        of the component's testability strategy (a third tier beyond the
        unit + integration layers of Two-Layer Test Strategy, 7vpm2qkx): it
        is a qualitative, LLM-behavioral check that the agent-facing
        self-description drives correct tool usage — run it whenever the
        agent-facing surface changes (a new/renamed tool, a reworked
        instructions block) and at least every few phases regardless.
      children:
        security-hawk:
          id: 5pqnx7vk
          last-run: 2026-05-28
          phase: 2B
          finding-summary: >
            0 critical; 3 significant (socket TOCTOU + 0700 fallback dir,
            NDJSON line-length bound, fallback-dir perms); 3 minor (config
            file perms warning, confer-daemon PATH-resolution log, liveness-
            probe-vs-lock observation). Accept-recommended findings fixed
            in remediation commits; NDJSON line-length deferred as tension
            7pqkn4vx.
          recommended-cadence: every-3-phases
        devops-engineer:
          id: 7nqpvxm4
          last-run: 2026-05-28
          phase: 2B
          finding-summary: >
            2 critical (SIGTERM handler missing → cleanup unreachable on
            stop, PID file never validated against live process); 5
            significant (bind-before-PID race, gateway task fire-and-forget,
            wait_for_ready no timeout, Settings.load bare FileNotFoundError,
            uv.lock currency); 6 minor. All critical and accept-recommended
            significant fixed in remediation commits.
          recommended-cadence: every-3-phases
        testability-hawk:
          id: kpqxnm7v
          last-run: 2026-05-28
          phase: 2B
          finding-summary: >
            3 critical (CLI tests with unawaited coroutines, no concurrency
            tests despite phase being about concurrency, no integration
            tests on disk); 5 significant (settings-flow assertion missing,
            polling-loop flake risk, discord.py mock depth, time.time
            monkeypatch outside try, sleep(0) race-win); 4 minor + 8
            coverage-vs-correctness / hygiene observations. CLI tests
            fixed; thorough concurrency tests added; integration tests
            deferred as tension 5nqx7pmw; mock-depth rebutted as
            by-design tension 4vxn7pqm; significant items addressed per
            user direction. RuntimeWarning suppression explicitly NOT
            added — the warning is signal we want to keep.
          recommended-cadence: every-3-phases
        self-description-acid-test:
          id: sd7acidq
          last-run: 2026-05-29
          phase: G2
          finding-summary: >
            A confer-naive general-purpose subagent, given only the exact
            agent-facing self-description (server instructions + tool
            schemas) and an 11-scenario mixed battery, scored 11/11 on
            notify/ask/check_messages discrimination — including the
            don't-use-confer cases, the on_timeout stakes call, and the
            terse-reply vocabulary. No "notify" name-priming misuse (resolved
            tension 3pqvn7mw). Two wording refinements applied: stale
            notify-blocker bullet reworded (one-way vs reply-needed), and
            an "no safe default" abort trigger added to on_timeout guidance.
          recommended-cadence: on-agent-surface-change-or-every-3-phases
