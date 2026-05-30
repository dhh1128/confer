"""Claude Code hook entry points for away mode.

Two hooks (registered globally by `confer install-hooks`, ii7nqkp4):

- Stop (`run_stop_hook`): when the workstation is away, nudge a session that is
  about to idle at the terminal to reach the user via confer instead. Enforced
  with exit 2 + a stderr reason, the channel Claude Code feeds back to the model
  (Enforcement Via Stop Hook, eh7nqkp4). FAILS OPEN on every uncertain path so
  it can never wedge an unrelated, non-confer session.
- UserPromptSubmit (`run_prompt_hook`): typing in any session means the user is
  back; clear presence (Auto-Return On Keyboard Input, ar7nqkp4).
"""

import json
import time

from confer.presence import Presence, read_presence, set_present

_CONFER_TOOL_PREFIX = "mcp__confer__"

_AWAY_REASON = (
    "The user is away from the keyboard (confer away mode is on{note}). "
    "Do NOT stop and wait at the terminal — they will not see it. If you need "
    "a decision to continue, call the confer `ask` tool and act on the reply. "
    "If you have finished or are only reporting, call the confer `notify` tool. "
    "After reaching out via confer you may stop."
)


def _is_genuine_human_turn(obj: dict) -> bool:
    """True if `obj` is a real human prompt, not a tool_result envelope.

    Claude Code records BOTH human prompts and tool_results as messages with
    type=='user' (lp7nkq4x). A tool_result envelope's content is composed
    solely of tool_result blocks; a genuine human turn carries text or other
    blocks. We must key the 'since the last human turn' window off the latter,
    or the agent's own confer tool_result resets the window and the guard
    re-nudges after the agent already reached out."""
    if obj.get("type") != "user":
        return False
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, str):
        return True  # a plain-string human prompt
    if not isinstance(content, list):
        return True  # unknown shape → treat as a human turn (conservative)
    # A human turn if any block is NOT a tool_result (text, image, etc.). An
    # all-tool_result message is the agent's tool output, not a human turn.
    for block in content:
        if not (isinstance(block, dict) and block.get("type") == "tool_result"):
            return True
    return False


def _confer_tool_used_since_last_user(transcript_path: str) -> bool:
    """True if any mcp__confer__* tool_use appears after the last GENUINE human
    turn in the JSONL transcript. Fail-open: any read/parse trouble returns True
    (treat as 'already reached out') so the Stop hook does not block (eh7nqkp4).
    """
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except OSError:
        return True
    parsed: list[dict | None] = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            parsed.append(None)
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            parsed.append(None)
            continue
        parsed.append(obj if isinstance(obj, dict) else None)
    last_user = -1
    for i, obj in enumerate(parsed):
        if obj is not None and _is_genuine_human_turn(obj):
            last_user = i
    for obj in parsed[last_user + 1:]:
        if obj is None or obj.get("type") != "assistant":
            continue
        content = (obj.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and isinstance(block.get("name"), str)
                and block["name"].startswith(_CONFER_TOOL_PREFIX)
            ):
                return True
    return False


def run_stop_hook(
    stdin_text: str,
    *,
    presence: Presence | None = None,
    now: float | None = None,
) -> tuple[int, str]:
    """Return (exit_code, stderr_text). (2, reason) blocks the stop and feeds
    `reason` to the model; (0, "") allows it. `presence`/`now` are injectable
    for tests; default to a fresh read and wall-clock. Uses EFFECTIVE-away
    (sticky OR a fired scheduled entry, sq7nkp4x), not just the sticky flag."""
    when = time.time() if now is None else now
    presence = read_presence() if presence is None else presence
    if not presence.effective_away(when):
        return (0, "")
    try:
        data = json.loads(stdin_text)
    except json.JSONDecodeError:
        return (0, "")  # can't understand the event → don't block
    if not isinstance(data, dict):
        return (0, "")
    if data.get("stop_hook_active"):
        return (0, "")  # loop guard: continuation of a prior block
    transcript_path = data.get("transcript_path")
    if not isinstance(transcript_path, str):
        return (0, "")
    if _confer_tool_used_since_last_user(transcript_path):
        return (0, "")
    active_note = presence.active_note(when)
    note = f" — {active_note}" if active_note else ""
    return (2, _AWAY_REASON.format(note=note))


def run_prompt_hook() -> int:
    """UserPromptSubmit side effect: the user is typing here, so they are back
    everywhere. Clears sticky away and any already-fired schedule entry, but
    leaves still-pending future entries (ar7nqkp4 / sq7nkp4x). Always allow the
    prompt (exit 0)."""
    set_present()
    return 0
