# confer — known gaps

Issues discovered post-implementation that aren't yet structured into `this.i` decisions or open tensions. Each entry has enough detail that a future session can pick it up without re-deriving the analysis.

When we resolve a gap, either (a) promote it to a `this.i` decision + code change, or (b) defer it as an open `tension:` node in `this.i` with a `revisit-when:`, then remove it from this file.

---

## G1 — MCP self-description is too thin to be useful to a fresh Claude

**Discovered:** 2026-05-28, during phase 2B smoke-test setup.

**How surfaced:** A Claude Code session in `~/code/confer` (not the active design session — a fresh one Daniel started to register the MCP server) was asked to describe when it would use the `confer` MCP server. It answered well, but on inspection it had drawn entirely from auto-memory, not from anything confer self-advertises. When prompted to inspect what confer *actually* tells a fresh client, it found:

- **No server-level instructions block.** The MCP system prompt has a `## MCP Server Instructions` section where `kila` gets a paragraph; `confer` contributes nothing. (`FastMCP("confer", lifespan=...)` is constructed without `instructions=`.)
- **`ListMcpResourcesTool` on `confer` returns empty.** No `confer://about` doc, no usage guide.
- **`notify` tool description is mechanics-first**, not purpose-first. Current text leads with "Send a notification to the user via Discord DM" — never says *when* to call it or when not to. The whole reason the tool exists (out-of-band ping when terminal output isn't enough) is absent.
- **`message` parameter has no description.** Schema is `{"properties": {"message": {"title": "Message", "type": "string"}}}` — zero shape guidance for the model.

A fresh Claude reading just this would likely overuse `notify` (as a generic "tell the user" channel) and miss its actual purpose. The auto-memory crutch hides the gap in any session that has it.

**Proposed fixes** (ranked by leverage; my disposition in parens):

1. **Server-level instructions block via `FastMCP(..., instructions=...)`** — `[ACCEPT]`. Highest-leverage single change. 4-8 lines covering when-to-use and when-not-to-use. Goes into every client's system prompt automatically.
2. **Rewrite `notify` tool description purpose-first** — `[ACCEPT]`. Lead with: "Ping the user out-of-band (Discord DM) when they are likely away from the terminal. Use sparingly: long builds done, blockers needing input, scheduled tasks. Do not use for routine progress updates inside an active conversation."
3. **Add a parameter description to `message`** — `[ACCEPT]`. Tell the model: keep it short, include the most important context (file path, error gist), don't dump a wall of text. Include one concrete example.
4. **Expose an MCP resource `confer://usage-guide` with long-form policy** — `[DEFER]`. Overkill for a one-tool surface; revisit when `ask` and `check_messages` land (phase 2C/2D) and the policy space is bigger.
5. **Rename `notify` to something more specific (e.g., `ping_user_offband`, `dm_user_async`)** — `[DEFER, possibly REJECT]`. Touches the recorded Naming decision (`qj4xm7pn`); fixing the description is the cheaper, more direct lever. Revisit only if empirical evidence (#6) shows misuse persisting even with good instructions.
6. **Acid-test with a fresh Claude** — `[ACCEPT, ordering matters]`. Validation methodology, not a fix in itself. Run before and after the description changes (#1–#3) to verify they actually move behavior:
   - **Before:** already partially done by the session that discovered this — a clean Claude session in confer that had no MCP self-description to read on. Confirms baseline gap.
   - **After:** repeat with a fresh Claude session post-fix. Give it 3-5 mixed-shape tasks where notify *should* and *shouldn't* be used; observe whether reaches for notify at the right moments. If misuse pattern persists, then revisit #5 (rename).

**Methodology angle:** The fix is an external-contract change per `docs/methodology.md` §3 (what the MCP client sees and uses to decide invocation). It should land as a `this.i` decision node committed alone before the code change. Tentative node title: "Notify Self-Description Policy" — covers the instructions block, the purpose-first description, the parameter guidance, and the deliberate non-rename.

**When to act:** After current phase 2B smoke test completes (the manual end-to-end notify verification). Not a blocker for that smoke test itself — `notify` works mechanically; the gap is about how *other* sessions discover it. Probably a small focused phase between 2B-smoke-complete and the start of 2C (`ask`).
