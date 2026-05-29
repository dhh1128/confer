# UX Review: confer

**Date:** 2026-05-29
**Effort level:** medium
**Run label:** post-g3
**Mode:** unattended
**Context sources used:** `this.i` (tag-model, threaded-DM, routing, terse-reply, acknowledge-state-change, piggyback nodes), `AGENTS.md`, `README.md`, `docs/gaps.md`, `src/confer/cli.py`, `src/confer/server.py`, `src/confer/daemon/{core,routing,transport}.py`, `src/confer/protocol.py` (class inventory), prior `reviews/devops-post-g3.md`.

---

## Scope determination

The ux-guru persona is written for React/SPA financial-identity UIs (state topology, URL design, component layering, accessibility, l10n via `l10n-svc`). **None of that web-UI surface exists here** — confer is a Python MCP daemon with zero `.tsx/.jsx/.html` files. This is NOT, however, a headless backend with "no UI": confer has two real human-facing surfaces, and the persona's *core* mandate ("how a real, busy person experiences the interface under non-ideal conditions" + intent-boundary / consent concerns) applies squarely to them:

1. **The Discord DM channel** — the message vocabulary, tags, and conventions a human reads on a phone and replies to by thumb/dictation. This is the primary "UI."
2. **The `confer` / `confer-daemon` CLIs** — `confer list`, `confer answer`, `confer-daemon status|stop`.

The SPA-specific sections (URL state, component architecture, React-Query, keyboard focus traps, RTL) are Not Applicable and are not scored as gaps. Findings below are confined to the two surfaces above.

The interaction model is **explicitly chosen and richly documented** in `this.i` (threaded-channel model: `tgq4n7px`, `dm5kqv7n`, `rt7nqp4m`, `nr4kpq7v`, `cg7vnq4p`, `tv4nqk7p`). The single most common "missing design artifact" finding for AI-generated UIs — an undocumented, accidental interaction model — does **not** apply; this is among the most deliberately-designed conversational surfaces I have reviewed. Resolved tensions (mobile one-handed typing, dictation-first, tag-as-addressing-referent, no daemon-side reply expansion) are treated as binding and are not re-litigated.

---

## Evidence Inventory

- Read all user-facing string producers: `_closing_dm_text`, `_format_queue_for_check_messages`, `_format_pending_asks_for_list`, `_format_ambiguous_dm`, `_send_question_dm`, `_pending_hint`, the bounce constants in `routing.py`, the MCP `_SERVER_INSTRUCTIONS` block, and the `argparse` help in `cli.py`.
- Traced the inbound DM path: `DiscordTransport._handle_message` → `_dispatch_user_message` → `_route_and_act` → routing ladder → side effects + which outcomes produce a Discord-side reply to the human.
- Traced the CLI path: `confer answer` → `Inject` → `_handle_inject`.
- App was **not run** (read-only review). Runtime claims about what the human sees on Discord are inferred from the string-producing code and reduced to LIKELY where behavioral.

---

## Executive Summary

The conversational UX is deliberate and, for the surfaces it covers, good: tags are phone-friendly, terse-reply shorthand is documented, mobile/dictation constraints are first-class, and the concierge sigil was chosen for one-handed phone typing. The highest-value finding is a **silent-success gap on the reply path**: when the user dictates a reply that routes successfully (delivered / broadcast / notify-reply), confer sends **no Discord acknowledgment** — the user cannot tell from their phone whether the message landed, or on which thread — which sits in direct tension with the project's own `qn7pkm4v` "no silent transitions" principle. The two next findings are **stale user-facing affordances**: the `confer answer` help text still advertises the pre-G3 `N ...` and `label-prefix:` addressing forms the daemon no longer honors, and the README still says only `notify` is implemented. All three are small fixes.

---

## Missing Design Artifacts

Mostly **present and strong** for this project type:

- **Interaction model decision:** PRESENT — `this.i` threaded-channel decisions. Not a gap.
- **Product vocabulary / glossary:** PARTIAL — terms (thread, tag, label, notify, ask, broadcast, interjection, concierge) are defined inside `this.i` `why` fields but there is no single user/operator-facing glossary; the human on the phone never sees these definitions. LOW — noted below, not a top finding.
- **User task inventory covering all audiences:** PARTIAL — the design is centered on one human (Daniel, the away-from-keyboard operator) and the agent. That is correct for a single-user personal tool (confirmed by `confer_direct_push_no_prs` / single-user framing), so the "enterprise multi-audience" expectation does **not** fire here. Not a gap.
- **Route map / state-ownership table / mobile strategy:** Not applicable (no web UI, no routes, no multi-surface client).

---

## Top Findings

Ordered by bang-for-buck.

### F1: Successful reply routing is silent on Discord — user can't tell a dictated reply landed
- **Severity:** MEDIUM
- **Confidence:** LIKELY
- **User scenario / location:** `src/confer/daemon/core.py:431-481` (`_dispatch_user_message` replies to the human only for `bounced`/`ambiguous`/`concierge`; `delivered`, `broadcast`, and `queued_notify_reply` produce no Discord-side reply).
- **Finding:** When the user DMs a reply that routes successfully — answering an ask (`DeliverAsk`), broadcasting (`Broadcast`), or interjecting on a notify thread (`EnqueueNotifyReply`) — the daemon performs the side effect and sends the human nothing back. On a phone with no read receipts, the user has just dictated into a void: no confirmation the message was received, no echo of which thread it hit (critical when a 2-char `re k3` prefix could plausibly have matched the wrong thread), and for an interjection, no signal that delivery is *deferred* until the agent next polls (pull-only, `pl7nqx4v`). The failure/ambiguous paths *do* reply, which trains the user that silence means success — but silence is indistinguishable from a dropped Gateway send or a misrouted tag.
- **Tension with recorded intent:** `qn7pkm4v` ("Acknowledge Actionable State Changes") states *"Every transition that changes whether a question is answerable produces a brief Discord DM"* and explicitly rejects silent transitions because *"Productivity While Away makes the asynchronous Discord channel the user's only window into agent state — silent transitions strand the user mid-dictation."* A user-initiated reply that resolves an ask is exactly such a transition, yet it is silent. There is a legitimate counter-reading: `qn7pkm4v` also values minimizing Discord noise, and one could argue the *agent's* eventual action is the real acknowledgment. That counter-reading is why this is MEDIUM/LIKELY and recommend-defer rather than a confirmed bug — but the gap deserves an explicit product decision rather than falling out of the code by default.
- **Impact:** Affects the single most frequent user action (replying), every time, on the channel that is the user's *only* window when away. Highest frequency × real (if moderate) uncertainty cost.
- **Recommendation:** Decide explicitly: either (a) emit a terse confirmation echoing the resolved thread tag and outcome (e.g. `Re: k3qp — delivered`; for an interjection, `Re: m4qp — queued; agent will see it on its next check`), mirroring the existing `_closing_dm_text` style; or (b) record a deliberate `tension:`/decision node in `this.i` that the reply path is intentionally silent and *why* the noise cost beats the strand-the-user cost — closing the gap against `qn7pkm4v` either way. A reply-echo respects the "brief, action-relevant, no decorative noise" constraint while removing the did-it-land ambiguity, and would especially de-risk the unique-prefix matcher (`re k3`), which can silently bind the wrong thread.

### F2: `confer answer --help` advertises pre-G3 addressing forms the daemon no longer honors
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **User scenario / location:** `src/confer/cli.py:99-106` — help text: *"Use 'N ...' for the Nth pending ask, 'label-prefix: ...' for a specific agent, or just text when only one ask is pending."*
- **Finding:** The G3 routing rewrite (`rt7nqp4m`) **explicitly dropped** both the numeric shortcut (`N ...`) and label-prefix addressing in favor of thread tags (`re <tag>`). The `confer answer` help string was never updated and still instructs the user to use both removed forms. A user who follows the help and types `confer answer "2 roll it back"` will not target the 2nd pending ask — `2` is not a tag, so the text falls through the ladder (e.g. broadcast, or single-ask-wins, or an ambiguity bounce), routing somewhere the user did not intend, with no hint that the documented syntax is dead. This is an intent-boundary failure: the label describes a capability the system no longer has.
- **Impact:** Every CLI user reading `--help` to learn how to target a specific ask. The CLI's entire reason to exist (`ci7n4pvm`) is targeted answering from the laptop; the help misdescribes exactly that.
- **Recommendation:** Rewrite the help to the current model: *"Use 're <tag> ...' to target a specific thread (tag shown by `confer list`), or just text when only one ask is pending."* Drop the `N ...` and `label-prefix:` clauses. Cross-check the module docstring (`cli.py:1-10`) too. (Note: `confer list` correctly surfaces tags via `_format_pending_asks_for_list`, so the right mental model is already one command away — only the `answer` help contradicts it.)

### F3: README overview is stale — claims only `notify` is implemented
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **User scenario / location:** `README.md:66` (*"Phase 2B status — only `notify` is implemented; `ask` and `check_messages` are next."*) and the single-row Tools table at `:68-70`, whose `notify` row also describes the label prefix as "planned for phase 2C — currently the raw message body is sent unprefixed," which `_handle_notify` (`core.py:390`) now contradicts (`[{tag}] {label}: {message}`).
- **Finding:** `ask`, `check_messages`, the CLI, and the entire G3 threaded channel are all implemented (confirmed by `protocol.py` class inventory and the live handlers), but the README — the first artifact a new user/operator reads — describes a much earlier phase. A reader can't tell from the README that `ask` or `check_messages` exist, nor that messages are now tag-anchored.
- **Impact:** First-time orientation for any human setting confer up. Low frequency (once per reader) but it is the front door and it actively misdescribes the current capability set.
- **Recommendation:** Update the status line and Tools table to list `notify`, `ask`, `check_messages` with current signatures, and correct the notify-prefix note to reflect the shipped `[tag] label: body` anchoring.

### F4: Dead/expired notify-thread tag replies bounce only through the generic no-agents path
- **Severity:** LOW
- **Confidence:** LIKELY
- **User scenario / location:** `src/confer/daemon/routing.py:114-136`; notify-thread lifecycle `core.py:663-680` (`_drop_notify_threads_for_label`, `_NOTIFY_TAGS_PER_LABEL` cap).
- **Finding:** A notify tag is addressable only while its agent is connected, and the oldest notify tags are silently evicted at a per-label cap of 20 (`nr4kpq7v`, by design). But when the user replies `re m4qp ...` to a tag that has since died or been evicted, the prefix match finds nothing and the message falls through to the ordinary ladder — it may broadcast, hit a lone ask, or bounce with the generic `NO_AGENTS_BOUNCE`. The user is never told specifically *"that thread is closed"*; from their phone they cannot distinguish "I typed the tag right but it expired" from "I typed the tag wrong." `qn7pkm4v` deliberately DMs the user when an *agent-side* transition closes a thread (lost contact / timeout / withdrawn), so the user has been trained that closures are announced — but a tag they try to reach *after* eviction gets no thread-specific explanation.
- **Impact:** Edge case (reply to an old/expired notify thread), but precisely the kind of non-ideal-conditions confusion the persona targets, and inconsistent with the closure-announcement pattern elsewhere.
- **Recommendation:** When an inbound reply carries a leading `re <token>` whose token matches no active tag, distinguish that from "no marker / ordinary prose" and bounce with a thread-specific message (e.g. *"No open thread `m4qp` — it may have closed. `.` for status or reply without a tag to broadcast."*) rather than routing it onward or returning the generic no-agents bounce. Confidence is LIKELY because the exact fall-through outcome depends on concurrent ask/agent state at reply time.

---

## Additional Patterns Noted

- **No user/operator glossary.** Thread / tag / label / notify / ask / broadcast / interjection / concierge are defined only inside `this.i` `why` fields. A short README or `docs/` glossary would help a returning user map the tags and `re`/`.` conventions they see on the phone. LOW.
- **Ambiguity bounce can be long on mobile.** `_format_ambiguous_dm` (`core.py:582-586`) lists every awaiting ask with full `question` text. With several long questions pending this becomes a wall of text on a phone — counter to the mobile-terse ethos elsewhere. Consider truncating each question to a short preview after the tag. LOW.
- **Discord 2000-char limit not guarded.** `DiscordTransport.notify` (`transport.py:103-114`) sends bodies straight to `channel.send`; a long agent `notify`/`ask` body, a re-ping that re-embeds the full question (`core.py:606-609`), or a many-thread ambiguity list could exceed Discord's 2000-char message cap and raise `HTTPException`, surfacing to the agent as `<NOTIFY_FAILED: ...>` rather than a truncated-but-delivered message. The `_MESSAGE_DESCRIPTION`/`_QUESTION_DESCRIPTION` guidance discourages wall-of-text, but nothing enforces it. LOW/SPECULATIVE — depends on agent behavior; flagged for the orchestrator, overlaps a robustness concern more than pure UX.
- **`confer answer` exit-code semantics are reasonable** (`_NON_ZERO_EXIT_OUTCOMES = {bounced, ambiguous}`) — scripts can detect a non-delivery. Good; no change.
- **Terse-reply vocabulary lives only in the agent's instruction block**, not anywhere the human sees it. That is intentional (`tv4nqk7p`: replies pass verbatim, the agent interprets) and correct — noted only to confirm it is not a gap.

---

## Residual Unknowns

- Whether F1's silence is genuinely confusing in practice requires watching a real away-from-keyboard session (does the user actually feel stranded, or does the agent's follow-up action serve as ack?). The persona could not run the Discord channel.
- Actual Discord rendering of the `[tag] label: body` and `Re: tag — ...` anchors on the mobile client (line wrapping, code-span vs literal brackets) was not observed.
- Whether long ambiguity lists / questions actually breach the 2000-char cap in real use was not measured.

---

## Decisions Needed

- **F1 (product decision):** Should the reply path emit a brief Discord acknowledgment (echoing thread + outcome), or is silence-on-success intentional? Either way, reconcile with `qn7pkm4v` — by adding the ack or by recording a decision/tension node stating the silence is deliberate and why.
- **F4:** Should an expired/unknown-tag `re` reply get a thread-specific "that thread is closed" bounce, consistent with the agent-side closure announcements?

---

## Findings manifest

```yaml
findings:
  - id: UX-F1
    persona: ux-guru
    title: Successful reply routing is silent on Discord; user can't tell a dictated reply landed
    severity: MEDIUM
    confidence: LIKELY
    location: src/confer/daemon/core.py:431-481
    dedupe_key: reply-routing-unacknowledged
    recommended_disposition: recommend-defer
    rationale: Delivered/broadcast/notify-reply produce no Discord ack, leaving the away user unsure their reply landed or on which thread; in tension with qn7pkm4v's no-silent-transitions principle, but the agent's follow-up action is a plausible implicit ack, so it needs a product call not an automatic fix.
    revisit_condition: A real away-from-keyboard session shows the user re-sending or asking "did that go through?", or a mis-prefixed reply (re k3) silently hits the wrong thread.
    fix_effort: small
  - id: UX-F2
    persona: ux-guru
    title: confer answer --help advertises pre-G3 'N ...' and 'label-prefix:' addressing the daemon dropped
    severity: MEDIUM
    confidence: CONFIRMED
    location: src/confer/cli.py:99-106
    dedupe_key: cli-answer-help-stale
    recommended_disposition: recommend-fix
    rationale: rt7nqp4m removed numeric and label-prefix addressing in favor of 're <tag>'; the help still tells users to use both, so following it routes the answer somewhere unintended with no hint the syntax is dead.
    revisit_condition: null
    fix_effort: small
  - id: UX-F3
    persona: ux-guru
    title: README claims only notify is implemented; ask/check_messages/CLI/threading all shipped
    severity: LOW
    confidence: CONFIRMED
    location: README.md:66-70
    dedupe_key: readme-status-stale
    recommended_disposition: recommend-fix
    rationale: The front-door doc misdescribes the capability set (no ask/check_messages, claims notify body is unprefixed) contradicting core.py:390 and the protocol class inventory; cheap to correct.
    revisit_condition: null
    fix_effort: small
  - id: UX-F4
    persona: ux-guru
    title: Reply to a dead/expired notify-thread tag falls through to generic routing with no thread-specific bounce
    severity: LOW
    confidence: LIKELY
    location: src/confer/daemon/routing.py:114-136
    dedupe_key: expired-tag-reply-unhandled
    recommended_disposition: recommend-defer
    rationale: A 're <tag>' to an evicted/closed notify thread matches nothing and routes onward (broadcast/lone-ask) or returns the generic no-agents bounce; user can't tell an expired tag from a typo, unlike the agent-side closure DMs qn7pkm4v already sends.
    revisit_condition: Notify-thread eviction (per-label cap 20) or post-disconnect tag replies become common enough to confuse in practice.
    fix_effort: small
```
