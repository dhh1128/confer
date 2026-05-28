# confer — known gaps

Issues discovered post-implementation that aren't yet structured into `this.i` decisions or open tensions. Each entry has enough detail that a future session can pick it up without re-deriving the analysis.

When we resolve a gap, either (a) promote it to a `this.i` decision + code change, or (b) defer it as an open `tension:` node in `this.i` with a `revisit-when:`, then remove it from this file.

---

## G2 — After-fix acid test of `notify` self-description

**Discovered:** 2026-05-28, as the validation step for Notify Self-Description Policy (`4kxp7qnj`).

**Status:** Pending — design fix has landed (server `instructions=` block, purpose-first tool docstring, parameter description). Acid test not yet run.

**Why this matters:** Before-fix evidence (G1, now resolved) was empirical: a fresh Claude Code session in `~/code/confer` answered "when would you use confer" entirely from auto-memory rather than from anything confer self-advertised, because there was no self-advertising to read. The fixes landed in `this.i` decision `4kxp7qnj` and the code commit immediately following. We now need to verify the fixes actually change behavior, not just the schema.

**Test design:**

1. Spawn a `general-purpose` subagent with `isolation: "worktree"` so the fresh Claude can run in its own context with no inherited memory of confer (the orchestrator's memory of the project doesn't carry into a subagent's context window, but the worktree isolates working-tree state too).
2. The subagent prompt should set the scene minimally:
   - Tell it confer's MCP server is registered and `mcp__confer__notify` is available.
   - Do NOT explain what confer is for. Make it read the server's instructions block and the tool description.
   - Give it 5-6 mixed-shape micro-tasks where notify should and shouldn't be used:
     - "Run `uv run pytest`, then tell me how it went." (Routine, should NOT notify — terminal output is right.)
     - "Kick off `make build` and let me know when it's done. I'm going to grab coffee." (SHOULD notify — explicitly away.)
     - "Show me the contents of pyproject.toml." (SHOULD NOT notify — synchronous output.)
     - "Profile the daemon under load. This will take ~30 minutes — wake me up when it's interesting." (SHOULD notify — long-running + away.)
     - "What does the `_assign_label` function do?" (SHOULD NOT notify — answer in chat.)
     - "Wait for me to confirm the design — I might step away." (Ambiguous — interesting to see what it does.)
3. Record whether each notify-or-not decision matches the policy. Also record any over-confident or under-confident invocations.

**What we learn:**

- If most decisions align with the policy → fix is sufficient, close G2.
- If misuse persists in specific patterns → the policy text needs refinement; iterate on the instructions block.
- If misuse persists *across the board* → revisit `3pqvn7mw` (Notify Tool Name Reconsideration Pending); the name itself may be priming wrong behavior.

**When to run:** After phase 2C (`ask` tool) lands so the test can include ask-vs-notify discrimination tasks, OR opportunistically now before 2C starts if we want to lock in the notify policy first. Either ordering works; user's call.
