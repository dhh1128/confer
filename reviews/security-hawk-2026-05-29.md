# Security Review: confer

**Date:** 2026-05-29
**Effort level:** deep
**Mode:** unattended (run_label 2026-05-29)
**Reviewed commit:** 3daa1274d26f8d781a7bdd9e9879d23ed0f19b66 (dirty working tree: yes — 13 changed/untracked paths, including the new `hooks.py` / `integrations.py` / `presence.py` modules and `scripts/release.py`, all reviewed)
**Context sources used:** `this.i` (full read of the daemon/IPC/auth/away-mode nodes), `AGENTS.md`, `README.md`, `pyproject.toml`, `uv.lock`, all of `src/confer/**`, `.github/workflows/*.yml`, `.github/dependabot.yml`, `.github/copilot-instructions.md`, `.githooks/pre-commit`, `.agent-bin/*`, `config.toml.example`, `scripts/release.py`, prior `reviews/devops-post-g3.md` and `reviews/ux-post-g3.md` (read only after forming my own model).

---

## Evidence Inventory

- Read every Python module under `src/confer/` including the untracked away-mode additions (`hooks.py`, `integrations.py`, `presence.py`) and `scripts/release.py`.
- Read the full IPC protocol (`protocol.py`), the daemon dispatch core (`daemon/core.py`), the pure router (`daemon/routing.py`), and the Discord boundary (`daemon/transport.py`).
- **CVE scan performed and clean.** `pip-audit` was not preinstalled, so I ran it via `uvx pip-audit` against confer's *actual* locked, non-dev dependency tree (`uv export --frozen --no-dev` → `aiohttp 3.13.5`, `discord-py 2.7.1`, `mcp 1.27.1`, `pydantic 2.13.4`, `starlette 1.1.0`, `uvicorn 0.48.0`, `httpx 0.28.1`, `anyio 4.13.0`, and transitives): **"No known vulnerabilities found."** (An initial `pip-audit` invocation audited the tool's own venv — disregarded; the reported result is the `-r exported-reqs` run.)
- Invisible/zero-width-Unicode scan over `src/`, `tests/`, `scripts/`: **clean** (no matches for the PUA / variation-selector / bidi-control ranges).
- Hardcoded-secret scan over `*.py`/`*.toml`/`*.yml`: **clean** — the only `discord_bot_token` references are field names and the `config.toml.example` placeholder (empty string). No token is logged anywhere (`grep` of all `log.*` calls confirms).
- **Trust-model context:** Per `this.i` (Central Daemon Architecture `dq7n3xpk`, IPC Protocol `kp5w2nfx`, Global Config `hq7x3npm`) and the DevOps review, confer is a **local, single-user, single-machine** tool. The trust boundary is "this user's processes on this host." The Origin platform's RFC-9421 / AID / nonce / cross-cell / DB-schema machinery is **Not Applicable** — confer is not an Origin microservice, has no HTTP service surface, no DB, and no network listener (the only socket is an AF_UNIX file). I evaluated it against the single-user-host threat model that `this.i` actually declares, not the Origin service model the persona assumes.
- Did **not** run the daemon against live Discord or execute the test suite (read-only review; runtime Gateway behavior unverified).

---

## Executive Summary

For what confer is — a personal, local MCP-to-Discord relay whose only IPC surface is a 0600 Unix socket — the security posture is sound: the socket is created under a `0o077` umask with an explicit `chmod 0600`, the Discord inbound path filters strictly on `message.author.id == confer_user_id`, no secret is ever logged, the locked dependency tree is CVE-clean, and the PyPI publish path uses OIDC trusted publishing (no static token to steal). The single most material gap is the **absence of `docs/threat-model.md`**, which is what lets the next reviewer mistake confer for a multi-tenant service and mis-scope the IPC surface. The two concrete code-level items worth attention are both defense-in-depth: the IPC socket falls back to a long-lived `~/.local/state` directory whose permissions are not re-asserted on every startup, and the config loader *warns but does not refuse* on a world-readable token file. Nothing here blocks the milestone.

---

## Top Findings

Ordered by bang-for-buck (highest risk reduction per unit of fix effort first).

### F1: No threat model documents confer's actual (single-user-host) trust boundary
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Location:** `docs/` (no `threat-model.md`)
- **Finding:** `docs/` contains `gaps.md`, `intent-briefing.md`, and `methodology.md` but no threat model. confer's entire security argument rests on one implicit premise stated only in scattered `this.i` nodes: *"file permissions ARE the access control on a single-user system — no in-band auth token needed"* (`kp5w2nfx`). That premise is load-bearing for the whole IPC design — the daemon accepts `INJECT` and `LIST_ASKS` from any connecting process **without HELLO and without any authentication** (`core.py:353-360`), feeding injected content straight into `_dispatch_user_message`, which can deliver replies to a waiting agent and read the list of pending asks. That is correct *if and only if* the socket is reachable only by the one trusted user. With no written threat model, the next contributor (or reviewer) cannot see that the 0600 socket perms are the *entire* security boundary, and a future change that loosens socket perms, adds a TCP transport, or runs the daemon as a shared service would silently convert a non-issue into an auth bypass.
- **Exploit path:** Not directly exploitable today. The risk is erosion: a future maintainer, lacking the documented boundary, exposes the socket (e.g. a containerized multi-tenant deployment, or a `chmod` regression) and every connecting process can now inject answers to other agents' asks and enumerate pending questions — with no authentication to stop it.
- **Recommendation:** Add `docs/threat-model.md` naming: (1) the asset (the Discord bot token, and the integrity of agent↔user message routing); (2) the trust boundary (processes running as this user on this host); (3) the assumed attacker (another local user account, a malicious dependency running in-process, a compromised co-tenant if the host is ever shared); (4) the accepted risks (any same-UID process can inject via the socket — explicitly accepted on a single-user box). State the invariant "the socket's 0600 perms are the only access control" as a tripwire so any change that touches transport or perms re-opens this analysis.

### F2: IPC socket fallback dir permissions are not re-asserted on every daemon start
- **Severity:** LOW
- **Confidence:** LIKELY
- **Location:** `src/confer/daemon/core.py:208-239`, `src/confer/paths.py:15-37`
- **Finding:** The socket lives at `$XDG_RUNTIME_DIR/confer.sock`, but on WSL2 (confer's stated primary environment, `this.i` k7m3pq2x) `XDG_RUNTIME_DIR` is frequently unusable, so `paths.py` falls back to `~/.local/state/confer/confer.sock`. Unlike `/run/user/<uid>` (which the OS creates 0700 and wipes on logout), `~/.local/state/confer` is a **persistent** directory. `serve()` does `parent.mkdir(mode=0o700, …, exist_ok=True)` then `parent.chmod(0o700)` (core.py:211-216), so the parent is re-asserted to 0700 on each start — good. The socket itself is created under `umask(0o077)` and then `chmod(0o600)` (core.py:225-239) — also good. The residual gap: the `_xdg_state_home()` *grandparent* (`~/.local/state`) is never created or permission-checked by confer; if it pre-exists group/other-writable (umask-dependent, or inherited from a tarball restore), the 0700 on `confer/` still protects the socket, so impact is bounded. This is genuinely defense-in-depth, not a live hole — the 0700 on the immediate parent is the effective control and it *is* re-asserted.
- **Exploit path:** Requires another local user able to write to a mispermissioned `~/.local/state` AND win a race to pre-create `confer/` with loose perms before the daemon's `chmod`. On a single-user box, no second user exists; the path is theoretical. Flagged because the fallback turns an ephemeral, OS-managed socket dir into a long-lived one whose ancestry confer does not fully own.
- **Recommendation:** Optionally `os.stat` the resolved socket directory at bind time and refuse (or loudly warn) if it is group/other-accessible, mirroring the `_warn_if_loose_perms` pattern already used for the config file. Cheap, and it converts a silent assumption into an observable check.

### F3: Config loader warns but does not refuse a world-readable bot-token file
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Location:** `src/confer/config.py:13-29, 53`
- **Finding:** `_warn_if_loose_perms` logs a warning (to the daemon log, which the user rarely tails) when `config.toml` has any `0o077` bit set, but `Settings.load` proceeds to read the token regardless. The Discord bot token is a long-lived credential whose compromise lets an attacker DM the user as confer and read whatever the bot can see. The comment justifies non-refusal ("a typo locks the user out") — a reasonable tradeoff — but the warning lands in `daemon.log`, not on a TTY, so in the auto-spawn path (the normal path) the user never sees it. A token sitting at mode 0644 is silently trusted.
- **Exploit path:** A second local account (or a non-confer process running as a different user with read access via a loose-permission config) reads `~/.config/confer/config.toml` and exfiltrates the bot token, then impersonates confer to the user over Discord. Requires the config to already be mispermissioned and a second principal on the host — same single-user caveat as F2, so impact is bounded on the intended deployment.
- **Recommendation:** Keep loading (don't lock the user out), but (a) on the interactive `confer setup` path, `confer setup` already writes 0600 — good; (b) additionally surface the loose-perms warning to **stderr** when running interactively, and consider auto-`chmod 0600` the file on load (it is the user's own file) rather than only logging. At minimum, document the warning's existence so it is not missed in the log.

### F4: Discord inbound trust is correctly scoped — recorded as a verified non-finding
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Location:** `src/confer/daemon/transport.py:60-74`
- **Finding (positive/closeout):** `_handle_message` filters on `isinstance(message.channel, discord.DMChannel)` AND `message.author.id == self._user_id` before invoking the dispatch callback, and the privileged `message_content` intent is deliberately *not* requested (with a clear comment on why DMs still carry content). This is the right boundary: a third party who shares a guild with the bot cannot inject routing content, because guild messages and non-owner DMs are dropped. Callback exceptions are caught and logged, so a malformed inbound message cannot tear down the Gateway loop. I record this explicitly so a future reviewer does not re-flag "the bot processes arbitrary Discord input" — it does not. The one residual: content from the trusted user is routed verbatim into agent context (the `ask`/`check_messages` return strings); since the user is the trust root and the consumer is an LLM agent (not a shell/SQL sink), there is no injection sink to exploit. No action required.
- **Recommendation:** None. Documented as a deliberate, correct control.

### F5: Away-mode hook installer mutates global `~/.claude/settings.json` and registers a self-invoking command hook
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Location:** `src/confer/integrations.py:87-130`, `src/confer/hooks.py:71-94`
- **Finding:** `confer install-hooks` writes a `Stop` and `UserPromptSubmit` hook into the user's **global** `~/.claude/settings.json`, each running `"{confer_bin} hook stop|prompt"`. The installer correctly (a) merges rather than clobbers, (b) refuses to write if the existing JSON is corrupt (surfacing `JSONDecodeError` instead of overwriting, cli.py:237-243), and (c) resolves `confer_bin` to an absolute path so a later PATH change can't redirect the hook. The security-relevant property: the installed Stop hook executes on **every** Claude Code session globally (matcher `""`), reads each session's transcript file (`hooks.py:34`), and can block a turn with exit 2. The hook fails open on every uncertain path (unreadable transcript, parse error, missing presence) — verified in `run_stop_hook`. So a malicious or corrupted transcript cannot wedge a session, and the hook does not execute transcript content, only inspects it for `mcp__confer__*` tool_use markers. The residual concern is blast radius, not a code defect: a global hook that shells out to `confer` on every session means any future compromise of the `confer` binary on PATH gains a foothold in every Claude session. Because `confer_bin` is pinned to an absolute path at install time, a PATH-shadowing attack is already mitigated.
- **Exploit path:** No direct exploit. If the installed `confer` executable were later replaced (e.g. a malicious package update to the `confer` PyPI entry point), the global Stop hook would invoke the malicious code on every session start/stop. This is inherent to any global hook and is the strongest argument for OIDC trusted publishing (already in place — no publish token to steal) and dependency pinning (already in place — `uv.lock` + `--frozen`).
- **Recommendation:** Document, in the away-mode section of the threat model proposed in F1, that `install-hooks` grants `confer` global per-session execution, so the integrity of the installed `confer` binary is a trust dependency for *all* Claude sessions, not just confer-using ones. No code change required; the fail-open design and absolute-path pinning are correct.

---

## Additional Patterns Noted

- **Third-party actions pinned to mutable tags, not SHAs** (`astral-sh/setup-uv@v7` in ci.yml + publish.yml; `pypa/gh-action-pypi-publish@release/v1` in publish.yml). A compromised maintainer could retarget the tag (the tj-actions attack class). This is squarely the DevOps lane (already noted in `reviews/devops-post-g3.md`); raised here only for dedupe alignment under `github-actions-unpinned`. The `publish.yml` exposure is the more serious of the two because that job holds `id-token: write` (OIDC) — a retargeted `setup-uv` runs in the same job that can mint a PyPI publishing token. Worth a SHA pin specifically on the publish workflow.
- **No automated secret-scanning / invisible-Unicode pre-commit or CI gate.** The repo's pre-commit hook is the agentprep certification gate only; there is no `gitleaks`/`trufflehog` step and no non-printable-Unicode check. Low urgency for a single-maintainer repo that takes no external PRs today, but the moment confer accepts outside contributions this becomes a real gap (concealed-payload class). DevOps-adjacent; flagged for `secret-scanning-missing` dedupe.
- **`copilot-review-gate.yml` interpolates `${{ github.event.pull_request.title }}` via `env:` (safe pattern), not inline** — verified clean; no workflow script-injection. Trigger is `pull_request` (not `pull_request_target`), so untrusted PR code never runs with repo secrets. Good.
- **`config.toml.example` ships `confer_user_id = 0`** — a benign placeholder; `_cmd_setup` rejects non-positive snowflakes (cli.py:168). No issue.
- **`scripts/release.py` shells `git`/`uv` with fixed argv lists** (no `shell=True`, no user-string interpolation into commands). Clean.

---

## Residual Unknowns

- Runtime behavior of the live Discord Gateway path was not exercised (no bot token in this environment). The static read shows correct author filtering and fail-closed callback handling, but I could not confirm discord.py does not deliver DM events for users who do not share a guild — the author-ID check makes that moot regardless.
- Whether the host is ever genuinely single-user is an environmental assumption I cannot verify from the code; F2/F3/F5 impact all hinge on it. The threat model (F1) is the right place to ratify it.

---

## Decisions Needed

- **Ratify the single-user-host trust boundary in writing (F1).** This is the one decision that changes how every other finding is scored. If confer will only ever run on a personal workstation as one user, F2/F3 are accept-risk and F5 is documentation-only. If confer might ever run on a shared host or in a container, F2/F3 escalate and the HELLO-exempt INJECT path needs an auth token.
- **Decide whether `config.toml` loose perms should auto-chmod or hard-fail (F3)** vs. the current warn-and-proceed. The current choice is defensible; just make it deliberate.

---

```yaml
findings:
  - id: SEC-F1
    persona: security-hawk
    title: No threat model documents confer's single-user-host trust boundary
    severity: MEDIUM
    confidence: CONFIRMED
    location: docs/ (no threat-model.md)
    dedupe_key: threat-model-missing
    recommended_disposition: recommend-fix
    rationale: >
      The whole IPC design rests on an unwritten premise — 0600 socket perms
      are the only access control, and INJECT/LIST_ASKS are accepted with no
      auth. Without a written boundary, a future transport/perms change
      silently becomes an auth bypass.
    revisit_condition: null
    fix_effort: small
  - id: SEC-F2
    persona: security-hawk
    title: IPC socket fallback dir (~/.local/state) perms not fully owned/re-asserted
    severity: LOW
    confidence: LIKELY
    location: src/confer/daemon/core.py:208-239
    dedupe_key: ipc-socket-exposed
    recommended_disposition: recommend-defer
    rationale: >
      WSL2 fallback makes the socket dir persistent rather than OS-managed.
      The immediate parent is re-chmod'd 0700 each start (effective control),
      but the grandparent is unowned by confer. Bounded on a single-user box.
    revisit_condition: confer runs on a shared/multi-user host or in a container
    fix_effort: small
  - id: SEC-F3
    persona: security-hawk
    title: Config loader warns but does not refuse a world-readable bot-token file
    severity: LOW
    confidence: CONFIRMED
    location: src/confer/config.py:13-29
    dedupe_key: bot-token-exposed
    recommended_disposition: recommend-defer
    rationale: >
      Loose-perms warning lands in daemon.log (unseen on the auto-spawn path),
      and load proceeds anyway. Token compromise needs a second principal on
      the host — bounded on a single-user box, but the warning is effectively
      invisible.
    revisit_condition: confer runs on a shared host, or setup grows a non-0600 path
    fix_effort: small
  - id: SEC-F4
    persona: security-hawk
    title: Discord inbound trust correctly scoped (verified non-finding)
    severity: LOW
    confidence: CONFIRMED
    location: src/confer/daemon/transport.py:60-74
    dedupe_key: discord-inbound-safe
    recommended_disposition: recommend-accept-risk
    rationale: >
      DM-only + author-ID==confer_user_id filtering plus deliberate omission of
      the privileged message_content intent correctly excludes third-party
      input. Recorded so it is not re-flagged. No action.
    revisit_condition: null
    fix_effort: small
  - id: SEC-F5
    persona: security-hawk
    title: Away-mode installer grants confer global per-session hook execution
    severity: LOW
    confidence: CONFIRMED
    location: src/confer/integrations.py:87-130
    dedupe_key: claude-hooks-exposed
    recommended_disposition: recommend-accept-risk
    rationale: >
      Global Stop/UserPromptSubmit hooks run `confer` on every Claude session.
      Installer merges-not-clobbers, refuses corrupt JSON, pins an absolute bin
      path, and fails open on every uncertain path — correct. Residual is blast
      radius (confer binary integrity becomes a global trust dep), not a defect.
    revisit_condition: confer binary distribution gains an untrusted update channel
    fix_effort: small
```
