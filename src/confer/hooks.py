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

from confer.presence import Presence, read_presence, set_present

_CONFER_TOOL_PREFIX = "mcp__confer__"

_AWAY_REASON = (
    "The user is away from the keyboard (confer away mode is on{note}). "
    "Do NOT stop and wait at the terminal — they will not see it. If you need "
    "a decision to continue, call the confer `ask` tool and act on the reply. "
    "If you have finished or are only reporting, call the confer `notify` tool. "
    "After reaching out via confer you may stop."
)


def _confer_tool_used_since_last_user(transcript_path: str) -> bool:
    """True if any mcp__confer__* tool_use appears after the last human turn in
    the JSONL transcript. Fail-open: any read/parse trouble returns True (treat
    as 'already reached out') so the Stop hook does not block (eh7nqkp4)."""
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
        if obj is not None and obj.get("type") == "user":
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
    stdin_text: str, *, presence: Presence | None = None
) -> tuple[int, str]:
    """Return (exit_code, stderr_text). (2, reason) blocks the stop and feeds
    `reason` to the model; (0, "") allows it. `presence` is injectable for
    tests; defaults to a fresh read."""
    presence = read_presence() if presence is None else presence
    if not presence.away:
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
    note = f" — {presence.note}" if presence.note else ""
    return (2, _AWAY_REASON.format(note=note))


def run_prompt_hook() -> int:
    """UserPromptSubmit side effect: the user is typing here, so they are back
    everywhere. Always allow the prompt (exit 0)."""
    set_present()
    return 0
