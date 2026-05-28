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
        Pending Ask Lost On MCP Server Death.

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
        refined in Settings Via Pydantic Settings, 5qx2wkpn.)

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
        more as configuration grows.

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
        inside any plausible MCP-protocol startup tolerance.

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
      revisit-when: >
        confer is in regular use AND pending-ask loss has happened at least
        three times, OR the MCP standard / Claude Code adds session-persistence
        such that MCP servers can survive client restarts.

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
      revisit-when: >
        A proactive message that mattered has been lost to a restart at least
        once, OR confer is in use across long multi-session workflows where
        the loss surfaces as a recurring annoyance.

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
