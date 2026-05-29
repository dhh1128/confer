# DevOps / CI/CD Review: confer

**Date:** 2026-05-29
**Effort level:** medium
**Run label:** post-g3
**Mode:** unattended
**Context sources used:** `this.i` (Gateway/daemon/auto-spawn/crash nodes), `AGENTS.md`, `README.md`, `pyproject.toml`, `uv.lock` (presence), `.github/workflows/ci.yml`, `.github/workflows/copilot-review-gate.yml`, `.github/instructions/infra.instructions.md`, `.gitignore`, `.githooks/pre-commit`, `config.toml.example`, `src/confer/**` (config, paths, server, client, daemon/*). Verified action runtimes via raw action.yml fetch.

---

## Evidence Inventory

- Read all GitHub Actions workflow files and the infra instructions file.
- Verified `actions/checkout@v6` and `astral-sh/setup-uv@v7` both resolve to `using: node24` (no Node deprecation warning). Confirmed against upstream `action.yml`.
- Confirmed `uv.lock` is committed and CI runs `uv sync --frozen` (lockfile enforced).
- Confirmed no `.env`/secret/credential files are tracked.
- Confirmed no Dockerfile / docker-compose / helm / charts exist; per `this.i` (Auto-Spawn From MCP Server 7xj4mvqn, Central Daemon Architecture) this is a deliberately **local, single-user, single-machine** Python tool. K8s/Helm/Docker/Flyway/Prometheus checks are therefore Not Applicable, not gaps — and the persona's "no Dockerfile on a deployed service = CRITICAL" rule does not fire (this is not a deployed Origin service).
- Did not run the test suite or the daemon (read-only review; runtime Gateway behavior unverified).

---

## Executive Summary

Operational hygiene for what this is — a personal, local MCP-to-Discord daemon — is good: lockfile committed and enforced with `--frozen`, current action runtimes, a real `confer-daemon status` health command, rotating logs, atomic PID-file writes, restrictive 0600 socket/PID perms, and a documented crash-recovery posture (`this.i` nq7pxw4m accepts daemon-death state loss with a stated revisit condition). The meaningful gaps are all in **supply-chain control configuration on the GitHub Actions side**: no `permissions:` block on the CI workflow (inherits repo-default `GITHUB_TOKEN`), no Dependabot for actions/pip, third-party actions pinned to mutable tags rather than SHAs, and no secret-scanning / invisible-Unicode gate. None block the milestone; the highest bang-for-buck fix is adding a top-level least-privilege `permissions:` block plus Dependabot.

---

## Top Findings

### F1: CI workflow has no `permissions:` block — inherits default `GITHUB_TOKEN` scope
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Location:** `.github/workflows/ci.yml:1-8`
- **Finding:** `ci.yml` declares no `permissions:` key at workflow or job level. The job inherits the repository/org default `GITHUB_TOKEN` permission set, which on many repos is read-write. The test job needs only `contents: read`. `copilot-review-gate.yml` is better (it scopes `pull-requests: write`) but still sets that at the workflow top level rather than on the single job that needs it.
- **Operational consequence:** A compromised or malicious dependency executing during `uv sync`/`pytest` would run with whatever the default token grants — potentially write access to the repo. Least privilege is the platform's #1 supply-chain control (§8 priority order).
- **Recommendation:** Add `permissions: {contents: read}` at the top of `ci.yml`. In `copilot-review-gate.yml`, move `permissions: {pull-requests: write}` down to the `gate` job. Also set the repo default `GITHUB_TOKEN` to read-only in settings.

### F2: No Dependabot configuration — github-actions and pip ecosystems unmanaged
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Location:** `.github/` (no `dependabot.yml`)
- **Finding:** There is no `.github/dependabot.yml`. Neither the GitHub Actions versions nor the Python dependencies (`discord-py`, `mcp`, dev tools) receive automated update PRs or malware/advisory alerts.
- **Operational consequence:** Action and dependency drift goes unnoticed until something breaks or a CVE lands; the node20 deprecation class of problem (which AGENTS.md explicitly cares about) recurs silently. For a security-sensitive tool that holds a Discord bot token, an unpatched `discord-py`/`mcp` advisory is a real exposure.
- **Recommendation:** Add `.github/dependabot.yml` covering the `github-actions` and `pip` (uv/`pyproject.toml`) ecosystems, weekly. Pairs naturally with F3 (SHA-pinning needs Dependabot to stay current).

### F3: Third-party actions pinned to mutable tags, not commit SHAs
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Location:** `.github/workflows/ci.yml:13` (`actions/checkout@v6`), `:16` (`astral-sh/setup-uv@v7`)
- **Finding:** Actions are referenced by floating tag (`@v6`, `@v7`). Tags are mutable; a compromised upstream or retargeted tag would execute attacker-controlled code in CI. Runtimes are current (both `node24`, verified), so this is purely the mutability vector, not a deprecation problem.
- **Operational consequence:** Supply-chain compromise via tag retargeting. Lower likelihood for well-known first-party-ish actions, but the platform standard is full-SHA pinning with Dependabot bumps.
- **Recommendation:** Pin both to full commit SHAs with a trailing `# v6` / `# v7` comment, and let Dependabot (F2) bump them. AGENTS.md's "use latest stable" guidance is satisfied by SHA + Dependabot.

### F4: No secret-scanning / invisible-Unicode gate in CI
- **Severity:** LOW
- **Confidence:** LIKELY
- **Location:** repo-global (`.github/workflows/`, `.githooks/pre-commit`)
- **Finding:** The only pre-commit hook is the AgentPrep AI-certification gate; there is no `gitleaks`/`detect-secrets` step and no zero-width / PUA / bidi-control Unicode check in CI or hooks. The repo handles a Discord bot token (kept out of git via `.gitignore` + `config.toml` outside the repo — confirmed no secret files tracked), so the residual risk is an accidental future paste of a token into a tracked file, or concealed-code injection that standard linters miss.
- **Operational consequence:** A future accidental token commit or a concealed-Unicode payload would reach the remote unflagged. Cheap to prevent, expensive to remediate (token rotation + history rewrite).
- **Recommendation:** Add a lightweight CI step (`gitleaks detect` or `detect-secrets`) and an invisible-Unicode gate. GitHub push-protection/secret-scanning should also be enabled in repo settings (verify even though public).

### F5: Daemon log/state directory created with default perms; DM content world-readable on shared hosts
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Location:** `src/confer/daemon/__main__.py:24`, `src/confer/client.py:294` (`log_path.parent.mkdir(parents=True, exist_ok=True)`); log path `src/confer/paths.py:43-44`
- **Finding:** The socket and PID parent dirs are hardened to `0700` and the socket to `0600` (daemon/core.py:196-224 — good). But the log/state dir `~/.local/state/confer/` is created with the process umask (typically `0755`). The daemon logs DM bodies and user reply content (notify bodies, routing outcomes) there; the bot token itself is never logged (verified — transport.py logs exceptions, not the token). On a single-user machine this is harmless; on a shared host another local user could read message content.
- **Operational consequence:** Information disclosure of conversation/notification content (not the token) to other local users on multi-user machines. Matches the same threat the existing `config.toml` loose-perms warning (config.py:13-29) already guards against for the token.
- **Recommendation:** Create the state/log dir with `mode=0o700` (and `chmod(0o700)` an existing one), mirroring the socket-dir hardening already in `serve()`. Cheap, consistent with existing intent.

---

## Additional Patterns Noted

- **CI triggers are correct:** `ci.yml` runs on `push` to all branches and on `pull_request` — first-class gate, badge in README points at the right workflow with matching `name: CI`. No `needs:`-chain hazard (single job). No `workflow_run`/fork-safety surface to get wrong. This whole class of GitHub-Actions structural bugs is absent — good.
- **No lint/format step in CI** (`ruff`/`black`). The repo has no linter configured at all; adding `ruff check` would be cheap and catch style/error drift. LOW / optional.
- **No `architecture.md`:** AGENTS.md asks to propose creating one via `generate-arch-doc.md`. README has a solid Architecture section, so this is a documentation nicety, not an operational gap.
- **`uv python install 3.12` runs as a separate step** rather than relying on `setup-uv` pinning — works, but a `.python-version` is gitignored, so the Python version lives only in `pyproject.toml`'s `requires-python` (>=3.12) and the CI step. Fine for a personal tool.
- **Daemon-death state loss** is a known, recorded tension (`this.i` nq7pxw4m) with an explicit accept-risk + revisit condition (SQLite write-through). Correctly out of scope to re-litigate — flagged here only so the orchestrator sees it is already adjudicated in `this.i`.
- **Gateway auto-reconnect** is delegated to discord.py's `Client.connect()` (default `reconnect=True`), so transient Gateway drops self-heal; the daemon does not need its own backoff loop. Verified by reading transport.py:57.

---

## Residual Unknowns

- Repo-level GitHub settings (default `GITHUB_TOKEN` read/write, secret-scanning, push-protection, branch/tag rulesets) cannot be read from the working tree; F1/F4 assume the common defaults and should be confirmed in repo Settings.
- Runtime Gateway reconnection behavior and daemon crash recovery were not exercised (read-only review).

---

## Decisions Needed

- None blocking. The orchestrator should decide whether F1–F4 (supply-chain hardening) are worth applying now versus deferring, given this is an intentionally local single-user tool where the blast radius of CI compromise is smaller than for a deployed service.

---

## Findings manifest

```yaml
findings:
  - id: DEV-F1
    persona: devops-engineer
    title: CI workflow has no permissions block (inherits default GITHUB_TOKEN)
    severity: MEDIUM
    confidence: CONFIRMED
    location: .github/workflows/ci.yml:1-8
    dedupe_key: github-actions-overprivileged-token
    recommended_disposition: recommend-fix
    rationale: No top-level permissions; test job should be contents:read only. Cheapest highest-value supply-chain control.
    revisit_condition: null
    fix_effort: small
  - id: DEV-F2
    persona: devops-engineer
    title: No Dependabot config for github-actions and pip ecosystems
    severity: MEDIUM
    confidence: CONFIRMED
    location: .github/ (no dependabot.yml)
    dedupe_key: dependabot-missing
    recommended_disposition: recommend-fix
    rationale: Actions and Python deps (incl. discord-py/mcp) get no automated updates or advisory alerts; node20-style drift recurs silently.
    revisit_condition: null
    fix_effort: small
  - id: DEV-F3
    persona: devops-engineer
    title: Third-party actions pinned to mutable tags, not SHAs
    severity: LOW
    confidence: CONFIRMED
    location: .github/workflows/ci.yml:13,16
    dedupe_key: github-actions-unpinned
    recommended_disposition: recommend-fix
    rationale: checkout@v6 and setup-uv@v7 are floating tags; pin to SHA with Dependabot bumps. Runtimes already current (node24).
    revisit_condition: null
    fix_effort: small
  - id: DEV-F4
    persona: devops-engineer
    title: No secret-scanning or invisible-Unicode gate in CI/hooks
    severity: LOW
    confidence: LIKELY
    location: .github/workflows/, .githooks/pre-commit
    dedupe_key: secret-scanning-missing
    recommended_disposition: recommend-defer
    rationale: Repo holds a Discord bot token; no gitleaks/detect-secrets or zero-width/bidi Unicode check guards against future accidental token commit or concealed-code injection.
    revisit_condition: A token or secret is ever pasted into a tracked file, or the repo gains additional contributors.
    fix_effort: small
  - id: DEV-F5
    persona: devops-engineer
    title: Daemon log/state dir created with default perms; DM content readable by other local users
    severity: LOW
    confidence: CONFIRMED
    location: src/confer/daemon/__main__.py:24; src/confer/paths.py:43
    dedupe_key: daemon-logdir-exposed
    recommended_disposition: recommend-accept-risk
    rationale: Socket/PID dirs are 0700/0600 but state/log dir uses default umask; logs DM content (not the token). Harmless single-user, a disclosure vector on shared hosts. Mirror existing socket-dir hardening to fix.
    revisit_condition: confer is ever run on a multi-user/shared machine.
    fix_effort: small
```
