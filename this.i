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
            Tests in the integration tier (those gated behind the
            CONFER_INTEGRATION=1 env var and requiring a live Discord test
            bot) are not included in coverage measurement. The 100% branch
            target applies only to unit tests of production code with the
            discord.py boundary mocked.
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
        Signature: ask(question: str, timeout_seconds: int = 1800,
        on_timeout: Literal["use_best_judgment", "wait_forever", "abort"]
        = "use_best_judgment") -> str. Considered a single timeout-or-not
        flag: daniel was explicit that the timeout must not be a hard cap on
        human response time — different questions need different fallback
        behaviors. on_timeout is therefore a per-call policy: "what's the
        best refactor approach" tolerates use_best_judgment fallback; "should
        I drop this database table" must wait_forever. Three modes are the
        minimum that covers user-best-judgment, must-have-human-answer, and
        stop-and-surface-elsewhere. Default 30 min (1800s) was picked as a
        round number between "agent attention span" (~10 min) and "user
        away-from-desk" (~1 hour); revisable from experience.

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
        Timeout outcomes return sentinel strings ("<NO_RESPONSE_USE_BEST_JUDGMENT>"
        or "<NO_RESPONSE_ABORT>") rather than raising Python exceptions.
        Considered raising TimeoutError or a custom AskTimeoutError: forces
        the calling agent into try/except framing that the MCP protocol passes
        through as tool errors, which obscures the intentional "this is a
        normal outcome with a fallback policy" nature of the result. Sentinels
        keep the return type uniformly str and let the agent's natural-language
        reasoning handle the timeout case.

    Wait Forever Re-Pings = decision:
      id: hj7m4qbx
      why: >
        When on_timeout="wait_forever", the server treats timeout_seconds as
        a re-ping interval: every timeout_seconds without a reply, the bot
        sends a reminder DM ("still waiting on your input for: [question]").
        Considered no re-ping (silently wait): the user would have no surfacing
        on their phone after the initial notification, which defeats the
        purpose. Considered a fixed re-ping interval (e.g., every 30 min
        regardless): less ergonomic — the caller knows what cadence is
        appropriate per question. Tradeoff: notification spam if the caller
        sets timeout_seconds too low for a critical wait_forever question;
        the caller is responsible for picking sensible values.

    check_messages In-Memory State = decision:
      id: 5pq7n3kw
      why: >
        check_messages tracks the last-seen-message ID in MCP-server-process
        memory only, not in a persistent state file. Considered persisting to
        ~/.config/confer/state.json (XDG-conformant): would survive MCP server
        restarts but adds state-file management, race conditions when an ask
        reply and an unprompted message arrive close together, and ~30% more
        test surface. In-memory loses any proactive messages daniel sent while
        the MCP server was down, which is a real but recoverable cost (he
        re-sends, or the agent simply doesn't see it until the next session).
        In-memory picked for v1 to minimize state footprint; reopening with a
        persistent variant is a small refactor when warranted — see tension
        Proactive Messages Lost On Restart.

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
        Resolved by Central Daemon Architecture (dq7n3xpk). The daemon now
        outlives any individual MCP server; pending ask state is held in the
        daemon. When the originating MCP server dies, the ask remains pending
        in the daemon. If the user replies after the MCP server is gone, the
        daemon either (a) delivers the reply via check_messages to the next
        MCP server that connects with the same agent label, OR (b) drops the
        reply if no such MCP server returns within a retention window
        (default 1 hour, revisitable). The replacement failure mode — the
        DAEMON dying — is the lesser one (one long-lived process to monitor
        vs. dozens of ephemeral ones) and is captured separately as
        Daemon Death Loses Pending State (nq7pxw4m).
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
      revisit-when: >
        The first manual end-to-end smoke test of the daemon-backed notify
        succeeds (planned for phase 2B post-push). At that point, capture
        the exact sequence — create test bot, write config.toml, run
        confer-daemon, send a notify — as the first env-var-gated integration
        test under tests/integration/.

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

    # ─── PROMPT AUDIT HISTORY ────────────────────────────────────────────────

    Prompt Audit History = constraint:
      id: vp4nm7qx
      why: >
        Tracks last-run dates and finding summaries for adversarial-review
        personas, so gate ceremonies can identify overdue audits and
        recommend them before gate closes. Introduced at the phase 2B gate,
        after the first adversarial review. Cadence "every-3-phases" is a
        starting heuristic; adjust based on whether findings density grows
        or shrinks over time.
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
