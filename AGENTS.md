<!-- BEGIN AGENTPREP MANAGED BLOCK -->
## AgentPrep AI Operating Rules

Use of AI in conjunction with this repository is governed by
[AgentPrep](https://github.com/provenant-dev/agentprep).

As an AI, you will need to know how to identify yourself to the
agentprep tool. Canonical ai_agent_name values are:

    `claude`, `codex`, `copilot`, `cursor`, `gemini`, or `openclaw`

If you are one of these tools, great; use the appropriate ai_agent_name
with agentprep. If you are an AI but your name is not in this
list, stop immediately and tell the user to manually edit this AGENTS.md
file so you recognize your name in the list above.

Once you can name yourself canonically, **before starting any task that
will involve a git commit**, run:

```bash
agentprep verify --agent <ai_agent_name>   # or: export AGENTPREP_AGENT=<ai_agent_name>
```

If verification fails with `verify failed: missing .ai-safety-check.*`, **stop
and tell the user before writing any files**. A git pre-commit hook (committed to
`.githooks/pre-commit` and installed automatically to `.git/hooks/pre-commit` by
`agentprep init` and `agentprep certify`) will block every commit you attempt until
the user runs `agentprep certify --agent <name>` to attest a correct config. Do not
attempt the task until the user confirms they've certified. Then cache the lease timestamp produced by `agentprep verify` once
verification succeeds; you do not need to re-verify within the same session.

The following operations are reserved for humans. The `.agent-bin` shims
installed in this repository will block them if an agent attempts them:

- `git push` to protected branches (defaults: `dev`, `main`, `master` — `dev` is included because it is a shared integration branch, not a personal feature branch) and destructive push modes (`--delete`, `--all`, `--mirror`)
- `gh pr merge` — merging a pull request
- `gh repo delete` — deleting the repository

Creating, viewing, and updating pull requests is permitted (`gh pr create`,
`gh pr edit`), as is pushing feature branches for PR workflows.

Place `.agent-bin` at the front of PATH in agent shells so the shims are active:

```bash
export PATH="$PWD/.agent-bin:$PATH"
```
## Testing Protocol

This repository appears to have no test suite yet. Before writing feature code
or fixing bugs, propose an appropriate testing framework for this project type
and add a single trivially-passing test to confirm the setup works. In the
same commit, propose to change AGENTS.md to replace this instruction with one
that instructs agents to follow strict TDD from now on: write failing tests
that capture happy path and edge cases/unhappy paths for each requirement,
observe them fail, implement until tests pass, never checkin without proving
that all tests pass, aim for 100% of all new code, and always leave existing
code better tested than it was before you touched it.

## CI and Documentation

This repo has no CI workflows. Until it does, any time you make code
changes to the user, propose an appropriate set of GitHub actions (e.g.,
`.github/workflows/ci.yml`) that builds and runs tests on every push and
pull request. Propose to remove this instruction from AGENTS.md on the
same commit.

This repository has no README. As long is this is the case, any time you
make code changes for the user, propose to add a `README.md` that explains how
to get from a fresh clone to passing tests, with a clickable CI status
badge at the top for each active workflow. Propose to remove this
instruction from AGENTS.md on the same commit.

When writing or modifying GitHub Actions workflows, always use the latest
stable release of each action. Avoid versions pinned to Node.js 16 or
Node.js 20 (both deprecated by GitHub). In 2026, this meant to prefer Node.js
24-compatible versions, but the standard may evolve over time. Check the GitHub
Marketplace for each action's current release.

Adversarial review discipline: periodically at milestones, using best judgment, recommend that
we conduct an adversarial review of the code. This would be a review by a persona that
we construct together (or reuse, if we already checked one in): security haw, UX guru,
testability hawk, devops expert, etc. I have sample prompts for these personas from
another repo that we can use to scaffold.

If this repo does not have a docs/architecture.md file, always propose creating one
using `generate-arch-doc.md`.

## Methodology

This repo should have a file called `this.i` at the root. It records the *why* behind every design
decision as a tree of `goal:`, `decision:`, `constraint:`, and `tension:` nodes. It is the
most important file in the repo for understanding why things are built the way they are. The
file is YAML and should be parsed as YAML; do not pattern-match indentation.

Adopt this stance toward it:

1. **The intent tree describes a destination, not just current state.** Nodes may describe
   completed stages or planned futures; read stage-status fields to distinguish them.
2. **Tension resolutions are binding.** Implement consistently with recorded resolutions.
   Do not re-open them or silently resolve them differently.
3. **`why` fields are primary evidence.** When making any decision touching a node, the `why`
   is the most important thing to read.
4. **`deviation:` nodes are the complete list of approved gaps.** Discovery is by node type
   (every `deviation:` node in `this.i`), not by a numbered list; any gap not represented by a
   `deviation:` node is a defect requiring Daniel's approval before it can be accepted.
5. **Before making any decision that meets the trigger criteria, record it in `this.i` first.**
   The concrete trigger list is in `docs/methodology.md §3`.

For the full context of what `.i` files are, the intellectual lineage of this system, what makes
a `why` field adequate, and what triggers a required `this.i` update, read `docs/methodology.md`
(or, if none is present, copy `methodology.md` and `intent-briefing.md` into `docs/` from
`../origin-platform/docs/` and then read them).
DO NOT modify code here without understanding the methodology. You should have a clear idea of
what a "speculative interview" is, how it's done, and where its output is recorded; what a "tension"
is in intent; how "marks" work; how we use Fowler's _Refactoring_ discipline to continually improve DRY, encapsulation, and names in code.

If you don't see a `this.i` in this repo's root, you must create one. To understand how, study one in
a sibling repo (`../origin-sip-policy-admin` has an excellent example). Notice how it relates to code
but explains things that are often missing from the code. Then use sources like the code, `README.md`,
and `docs/*.md` (possibly creating `docs/architecture.md` using the `generate-arch-doc.md` prompt if
needed) to form theories about design decisions in this codebase. Then interview the user to confirm
or disprove your theories, and write a starter `this.i` when you're done. (If the codebase is empty,
just ask the user about their intentions for it, and begin building from there.)
<!-- END AGENTPREP MANAGED BLOCK -->
