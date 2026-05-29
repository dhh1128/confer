# DevOps / CI/CD Review: confer

**Date:** 2026-05-29
**Effort level:** medium
**Run label:** 2026-05-29
**Mode:** unattended
**Reviewed commit:** 3daa127 (HEAD — "implement install"; dirty working tree: hooks.py, integrations.py, presence.py, scripts/release.py untracked; README.md, cli.py, paths.py, test files, this.i modified)
**Context sources used:** `this.i` (all deferred tensions from prior review; new install/setup/away-mode decisions), `AGENTS.md`, `README.md`, `pyproject.toml`, `uv.lock` (presence), `.github/workflows/ci.yml`, `.github/workflows/publish.yml`, `.github/workflows/copilot-review-gate.yml`, `.github/dependabot.yml`, `.gitignore`, `.githooks/pre-commit`, `config.toml.example`, `src/confer/cli.py`, `src/confer/daemon/__main__.py`, `src/confer/daemon/core.py`, `src/confer/paths.py`, `src/confer/integrations.py`, `scripts/release.py`. Verified action runtimes via raw action.yml fetch for `actions/checkout@v6`, `astral-sh/setup-uv@v7`, `pypa/gh-action-pypi-publish@release/v1`. Prior review dispositions from `this.i` tensions `aq4nvx7p` (SHA pinning deferred), `ss4kqnv7` (secret-scanning deferred), `lp7nqkx4` (log dir perms accepted).

---

## Evidence Inventory

- Read all GitHub Actions workflow files (ci.yml, publish.yml, copilot-review-gate.yml) and the infra instructions file.
- Verified action runtimes: `actions/checkout@v6` → `node24` (confirmed); `astral-sh/setup-uv@v7` → `node24` (confirmed); `pypa/gh-action-pypi-publish@release/v1` → `composite` (no runtime warning, but the reference is a **mutable branch head**, not a tag or SHA).
- Confirmed `uv.lock` is committed and CI runs `uv sync --frozen` (lockfile enforced).
- Confirmed no `.env`/secret/credential files are tracked.
- Confirmed DEV-F1 (ci.yml permissions) and DEV-F2 (Dependabot) from the prior review are fixed in commit 54c6ddd.
- Confirmed prior deferred/accepted findings are recorded in `this.i` (`aq4nvx7p`, `ss4kqnv7`, `lp7nqkx4`) — not re-litigated here.
- Observed working tree has significant uncommitted WIP: `hooks.py`, `integrations.py`, `presence.py`, `scripts/release.py` untracked; `cli.py`, `README.md`, `paths.py`, and test files modified. HEAD is self-consistent (the committed cli.py does not import the untracked modules), but the away-mode feature is partially implemented and not yet committed.
- No Dockerfile / docker-compose / helm / charts — confirmed deliberate per `this.i` (local, single-user tool). Kubernetes/Docker/Flyway/Prometheus checks remain Not Applicable.
- Did not run the test suite or the daemon (read-only review; runtime behavior unverified).

---

## Executive Summary

The most urgent new finding is in `publish.yml` (added in the "implement install" commit): `pypa/gh-action-pypi-publish@release/v1` references a **mutable branch**, not a tag or SHA. Any commit pushed to that branch by pypa executes immediately in the publish pipeline. A second, related gap: the publish workflow has no `needs:` link to the CI job — when a tag is pushed via `scripts/release.py`, tests run locally but never run in CI before the package is uploaded to PyPI. These two issues are the only new recommend-fix findings; all prior CRITICAL/HIGH findings were resolved or properly deferred in `this.i`. Overall CI hygiene is materially improved since the prior review.

---

## Top Findings

Ordered by bang-for-buck (highest operational risk reduction per unit of fix effort, first).

### F1: `pypa/gh-action-pypi-publish` pinned to a mutable branch reference
- **Severity:** HIGH
- **Confidence:** CONFIRMED
- **Location:** `.github/workflows/publish.yml:37`
- **Finding:** The publish action is referenced as `pypa/gh-action-pypi-publish@release/v1`. `release/v1` is a **branch**, not a tag or commit SHA. Any commit pushed to that branch by the upstream repo would execute in the next publish run without any review gate in this repo. This is more mutable than even a floating tag: branch heads move with every upstream push, while tags typically move only on deliberate action.
- **Operational consequence:** Supply-chain compromise via branch-head retargeting. A malicious or erroneous commit on `pypa/gh-action-pypi-publish@release/v1` executes in the next `v*` tag push from this repo — i.e., in the same job that holds `id-token: write` for PyPI trusted publishing. The blast radius is a published compromised package or credential exfiltration.
- **Recommendation:** Pin to the latest commit SHA of the `release/v1` branch:
  ```yaml
  uses: pypa/gh-action-pypi-publish@cef221092ed1  # release/v1
  ```
  Add Dependabot (`github-actions` ecosystem is already configured) to bump the SHA as pypa advances the branch. The composite runtime carries no node20 deprecation warning.

### F2: Publish workflow has no CI test gate — tests bypass CI on tag push
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Location:** `.github/workflows/publish.yml:1-38`, `.github/workflows/ci.yml:3-5`
- **Finding:** `ci.yml` triggers on `push: branches: ["**"]` and `pull_request` — but **not on tag pushes**. `publish.yml` triggers on `push: tags: ["v*"]`. When `scripts/release.py` pushes a `v*` tag, the publish job runs without any CI test job having run on that exact SHA in CI. The release script runs `uv run pytest` locally before tagging, which is a compensating control, but it is a process discipline, not a structural gate — a typo in the release command or a checkout without local test execution bypasses it.
- **Operational consequence:** A broken package can be published to PyPI without CI having run. This is especially relevant as the codebase grows and the release script is the only gate between "pushed tag" and "PyPI publish."
- **Recommendation:** Add a test job to `publish.yml` that runs before the publish job, with `needs: [test]` on the publish job. Alternatively, add `tags: ["v*"]` to `ci.yml`'s push trigger and add `needs: [CI]` (the CI workflow's `test` job) to `publish.yml`'s publish job using `workflow_run`. The simplest fix is an inline test step in `publish.yml`:
  ```yaml
  jobs:
    test:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v6
        - uses: astral-sh/setup-uv@v7
          with: {enable-cache: true}
        - run: uv python install 3.12
        - run: uv sync --frozen
        - run: uv run pytest
    publish:
      needs: [test]
      runs-on: ubuntu-latest
      environment: pypi
      permissions:
        id-token: write
      steps: ...
  ```

### F3: `publish.yml` actions also use mutable tags (consistency gap, Dependabot partial cover)
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Location:** `.github/workflows/publish.yml:28-29` (`actions/checkout@v6`, `astral-sh/setup-uv@v7`)
- **Finding:** Both `ci.yml` and `publish.yml` use `@v6`/`@v7` floating tags. The prior review (DEV-F3) flagged this for `ci.yml` and it was deferred in `this.i` as `aq4nvx7p`. `publish.yml` was added after that tension was recorded — it inherits the same tag style. Both action runtimes are `node24` (no deprecation warning). Dependabot for `github-actions` is configured and will surface version bumps, though it bumps to new tags rather than SHAs.
- **Operational consequence:** Same tag-retargeting vector as `aq4nvx7p`, now also on the publish path. Lower likelihood for these first-party actions; the real risk is the `pypa` action (F1).
- **Recommendation:** Respect the prior deferred decision `aq4nvx7p` for `ci.yml`; extend the same disposition to `publish.yml` or SHA-pin at the same time when `aq4nvx7p` is revisited. Do not treat this as independently blocking.

### F4: Uncommitted WIP — away-mode feature partially implemented in working tree
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Location:** `src/confer/hooks.py` (untracked), `src/confer/integrations.py` (untracked), `src/confer/presence.py` (untracked), `scripts/release.py` (untracked), plus modifications to `src/confer/cli.py`, `src/confer/paths.py`, `README.md`, test files, `this.i`
- **Finding:** The working tree contains ~534 lines of production code across four new source files plus significant modifications to existing files, none of which are committed. HEAD's `cli.py` does not import the untracked modules (HEAD is self-consistent), but the away-mode feature documented in the uncommitted README diff is not yet in a committed state. If the working tree were lost (disk failure, accidental `git checkout -- .`), the away-mode implementation would be gone.
- **Operational consequence:** WIP loss risk. The away-mode feature is substantially written (hooks.py, integrations.py, presence.py, tests) but exists only in the working tree. A `git checkout -- .` or disk event would lose it.
- **Recommendation:** Stage and commit the away-mode feature (or push to a branch) as soon as tests pass. The `scripts/release.py` script requires a clean working tree before tagging anyway — this WIP will block the next release unless committed.

### F5: `publish.yml` — workflow-level permissions could be tightened
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Location:** `.github/workflows/publish.yml:17-18`
- **Finding:** The publish workflow has `permissions: contents: read` at the top level and `permissions: id-token: write` at the job level. The `id-token: write` is correctly scoped to the publish job only. The top-level `contents: read` is correct (minimal). This is actually well-structured; the finding is minor: the `contents: read` at the top level could be replaced with `permissions: {}` (deny-all) to force explicit per-job grants, making it obvious that no job inherits any permission implicitly. Current state is fine — this is a style preference.
- **Operational consequence:** No practical difference given the single-job workflow. A second job added later would inherit `contents: read` implicitly, which is benign but less obviously intentional.
- **Recommendation:** Optionally change the top-level to `permissions: {}` and add `contents: read` to the publish job alongside `id-token: write`. Not urgent — the current structure is correct.

---

## Additional Patterns Noted

- **DEV-F1 (prior): FIXED.** `ci.yml` now has `permissions: contents: read` at the workflow top level. The comment on line 9-10 even cites the prior review finding — good traceability.
- **DEV-F2 (prior): FIXED.** `.github/dependabot.yml` now covers `github-actions` and `pip` ecosystems with weekly cadence and appropriate labels. Comment cites the review finding.
- **DEV-F3 (prior): DEFERRED** in `this.i` as `aq4nvx7p` (SHA pinning deferred; Dependabot bumps mitigate). Respected — not re-litigated.
- **DEV-F4 (prior): DEFERRED** in `this.i` as `ss4kqnv7` (no secret-scanning gate). Respected.
- **DEV-F5 (prior): ACCEPTED** in `this.i` as `lp7nqkx4` (log dir perms on single-user machine). Respected.
- **`copilot-review-gate.yml` reviewed.** Permissions (`pull-requests: write`) are correctly scoped at the workflow top level. No node20 actions referenced (no `uses:` at all in the runner steps — uses only `run:` and `env:`). The `GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}` usage is standard. No issues.
- **`ci.yml` triggers confirmed correct.** Runs on `push` to all branches and `pull_request`. The `name: CI` field matches the README badge. Consistent with the prior review.
- **`uv sync --frozen` in CI** enforces the lockfile. `uv.lock` is committed. The Python ecosystem lockfile discipline is solid.
- **`scripts/release.py` runs `uv run pytest` before pushing.** The local test gate is well-implemented. The structural gap (F2 above) is that CI doesn't run on the tag itself, not that tests aren't run at all.
- **No Kubernetes/Helm/Docker/Flyway/Prometheus gaps** — confirmed deliberate scope (local single-user tool per `this.i` k7m3pq2x, Central Daemon Architecture dq7n3xpk). Not applicable.
- **Daemon operational health unchanged and solid.** `confer-daemon status`, rotating logs at 0700 parent + 0600 socket, PID-file liveness check, SIGTERM-then-wait shutdown — all confirmed in `daemon/__main__.py` and `daemon/core.py`. No regressions from the new feature work.
- **No `architecture.md`.** AGENTS.md recommends creating one via `generate-arch-doc.md`. README's Architecture section is thorough for the current scope; this is documentation hygiene only.

---

## Residual Unknowns

- PyPI trusted-publishing one-time setup (OIDC publisher registration + `pypi` environment creation in GitHub) is undone per the comment in `publish.yml:3-10`. The workflow will fail with a permission error until this is done. Not a workflow defect — it is documented as a prerequisite.
- Runtime behavior of the away-mode hooks (`hooks.py`, `integrations.py`, `presence.py`) not assessed — these are untracked WIP and not yet in the committed tree.
- Repo-level GitHub settings (default `GITHUB_TOKEN` scope, secret-scanning, branch/tag rulesets) cannot be verified from the working tree.

---

## Decisions Needed

- **F1 (HIGH):** Should `pypa/gh-action-pypi-publish` be pinned to the current branch SHA (`cef221092ed1`) before the first `v*` tag push? The fix is a one-line change. Recommend resolving before the first PyPI release, which `publish.yml` is positioned to trigger.
- **F2 (MEDIUM):** Add an inline test job to `publish.yml` (or add `tags: ["v*"]` to CI triggers) so tests run in CI before publish? The release script's local test run is a viable compensating control for a personal project — this is a quality/confidence call.
- **F4 (LOW):** Commit or branch the away-mode WIP to protect it from accidental loss.

---

## Findings manifest

```yaml
findings:
  - id: OPS-F1
    persona: devops-engineer
    title: pypa/gh-action-pypi-publish pinned to mutable branch reference (release/v1)
    severity: HIGH
    confidence: CONFIRMED
    location: .github/workflows/publish.yml:37
    dedupe_key: github-actions-unpinned-publish
    recommended_disposition: recommend-fix
    rationale: Branch ref is more mutable than a tag; any pypa push to release/v1 executes immediately in the publish job that holds id-token:write for PyPI OIDC. Pin to SHA before first release.
    revisit_condition: null
    fix_effort: small
  - id: OPS-F2
    persona: devops-engineer
    title: Publish workflow has no CI test gate on tag push
    severity: MEDIUM
    confidence: CONFIRMED
    location: .github/workflows/publish.yml:1-38
    dedupe_key: publish-workflow-untested
    recommended_disposition: recommend-fix
    rationale: ci.yml does not trigger on tag push; publish.yml has no needs:test. A broken package can reach PyPI if the local release-script test step is skipped.
    revisit_condition: null
    fix_effort: small
  - id: OPS-F3
    persona: devops-engineer
    title: publish.yml actions also use mutable tags (inherits deferred aq4nvx7p)
    severity: LOW
    confidence: CONFIRMED
    location: .github/workflows/publish.yml:28-29
    dedupe_key: github-actions-unpinned
    recommended_disposition: recommend-defer
    rationale: publish.yml added after aq4nvx7p was recorded in this.i; same risk, same Dependabot mitigation. Address when aq4nvx7p is revisited.
    revisit_condition: When this.i tension aq4nvx7p is revisited for SHA pinning.
    fix_effort: small
  - id: OPS-F4
    persona: devops-engineer
    title: Away-mode feature (~534 lines across 4 files) exists only in working tree
    severity: LOW
    confidence: CONFIRMED
    location: src/confer/hooks.py, src/confer/integrations.py, src/confer/presence.py, scripts/release.py (all untracked)
    dedupe_key: wip-uncommitted-production-code
    recommended_disposition: recommend-fix
    rationale: Four production source files plus test files and modifications to tracked files have not been staged. A git checkout -- . or disk event loses the implementation.
    revisit_condition: null
    fix_effort: small
  - id: OPS-F5
    persona: devops-engineer
    title: publish.yml top-level permissions could use deny-all default
    severity: LOW
    confidence: CONFIRMED
    location: .github/workflows/publish.yml:17-18
    dedupe_key: workflow-permissions-overpermissive
    recommended_disposition: recommend-defer
    rationale: contents:read at top level is benign for a single-job workflow; switching to {} plus explicit per-job grants is a style improvement, not a security gap.
    revisit_condition: A second job is added to publish.yml.
    fix_effort: small
```
