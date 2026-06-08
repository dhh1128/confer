## Testing Protocol

Strict TDD is in force. For every requirement, write failing tests that
capture the happy path and the edge / unhappy paths first, observe them
fail, implement until they pass, and never check in without proving that
all tests pass. Aim for 100% branch coverage on all new code, and always
leave existing code better tested than it was before you touched it. The
project standard is `uv run pytest` (with `--cov-branch --cov-fail-under=100`
already configured in `pyproject.toml`); a passing run is a gate
precondition (see `docs/methodology.md` §9).

## CI and Documentation

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


<!-- >>> tick stanza >>> (managed by `tick init`) -->

## Task tracking: `tick`

This repo tracks tasks, tech debt, and ideas in a local [`tick`](https://github.com/dhh1128/tick)
ledger (an orphan `tick` branch; the `tick` CLI is the interface). Reads are plain
files — do **not** use an external API for task tracking.

- **First, if a `tick` command says the repo isn't initialized**, run `tick init`
  once to connect this clone to the ledger — it adopts the existing remote ledger
  if a colleague already set one up, or creates a new one otherwise.
- **A tick mark is the sigil `~` immediately followed by a digit-first 4-char
  base32 id** (the id part looks like `4mz3`, so the full mark is that id with a
  leading `~`). It pins a tick to a code location.
- **Before editing a file**, grep it for marks and read what they reference:
  `rg '~[2-7][a-z2-7]{3}\b' <file>` then `tick show <id>`. A mark means recorded
  context exists for that spot — read it first.
- **Search** existing ticks with `tick grep <text>`; **list** with `tick ls`.
- **Capture** new work with `tick add "<title>"` and place the printed mark
  (`~` + the new id) at the relevant code spot.
- When your change **resolves** a tick, run `tick off <id>` and **delete the
  mark(s)** it reports still in the code.

<!-- <<< tick stanza <<< -->
