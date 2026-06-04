"""Install away-mode integrations into the user's global Claude Code config
(Integrations Installed Explicitly, ii7nqkp4).

Writes a Stop hook and a UserPromptSubmit hook into ~/.claude/settings.json and
`/away` / `/back` slash commands into ~/.claude/commands. Idempotent and
non-clobbering: it merges into existing settings and never duplicates an entry.
"""

import json
import shutil
from pathlib import Path


def claude_dir() -> Path:
    return Path.home() / ".claude"


def resolve_confer_bin() -> str:
    """Absolute path to the `confer` console script so the hook runs regardless
    of the hook process's PATH; falls back to the bare name if not resolvable."""
    return shutil.which("confer") or "confer"


_AWAY_MD = """\
---
description: Turn on confer away mode now, or schedule it (e.g. /away at 1100)
argument-hint: "[in <min> | at <HHMM>]"
allowed-tools: Bash({bin} away:*)
---
Enabling confer away mode:

!`{bin} away $ARGUMENTS`

I'm away from the keyboard (now, or as scheduled above). Until I'm back, when
you'd pause for my input or finish a task, reach me with the confer
`ask`/`notify` tools instead of waiting at the terminal.
"""

_BACK_MD = """\
---
description: Turn off confer away mode, or cancel a scheduled away
argument-hint: "[at <HHMM> | all]"
allowed-tools: Bash({bin} back:*)
---
Disabling confer away mode:

!`{bin} back $ARGUMENTS`

I'm back at the keyboard; resume normal interactive behavior (any future
scheduled aways are preserved unless I said 'all').
"""


def _load_settings(path: Path) -> dict:
    """Return parsed settings, or {} if the file is missing/empty. A genuinely
    corrupt settings.json raises json.JSONDecodeError — the caller surfaces it
    rather than clobbering the user's config."""
    try:
        text = path.read_text()
    except OSError:
        return {}
    text = text.strip()
    if not text:
        return {}
    return json.loads(text)


def _has_command(event_list: list, command: str) -> bool:
    for group in event_list:
        for handler in group.get("hooks", []):
            if handler.get("command") == command:
                return True
    return False


def _ensure_hook(settings: dict, event: str, command: str, matcher) -> bool:
    """Append a command hook for `event` if absent. Returns True if it changed
    settings, False if the command was already registered."""
    hooks = settings.setdefault("hooks", {})
    event_list = hooks.setdefault(event, [])
    if _has_command(event_list, command):
        return False
    entry: dict = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        entry = {"matcher": matcher, **entry}
    event_list.append(entry)
    return True


def install(
    *,
    settings_path: Path | None = None,
    commands_dir: Path | None = None,
    confer_bin: str | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Install (or report, if dry_run) the hooks + slash commands. Returns a
    human-readable list of the actions taken/planned."""
    settings_path = settings_path or (claude_dir() / "settings.json")
    commands_dir = commands_dir or (claude_dir() / "commands")
    confer_bin = confer_bin or resolve_confer_bin()

    stop_cmd = f"{confer_bin} hook stop"
    prompt_cmd = f"{confer_bin} hook prompt"

    settings = _load_settings(settings_path)
    actions: list[str] = []
    changed = False

    if _ensure_hook(settings, "Stop", stop_cmd, matcher=""):
        actions.append(f"add Stop hook -> {stop_cmd}")
        changed = True
    else:
        actions.append("Stop hook already registered (skipped)")
    if _ensure_hook(settings, "UserPromptSubmit", prompt_cmd, matcher=None):
        actions.append(f"add UserPromptSubmit hook -> {prompt_cmd}")
        changed = True
    else:
        actions.append("UserPromptSubmit hook already registered (skipped)")

    actions.append(f"write {commands_dir / 'away.md'}")
    actions.append(f"write {commands_dir / 'back.md'}")

    if dry_run:
        return actions

    if changed:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    commands_dir.mkdir(parents=True, exist_ok=True)
    (commands_dir / "away.md").write_text(_AWAY_MD.format(bin=confer_bin))
    (commands_dir / "back.md").write_text(_BACK_MD.format(bin=confer_bin))
    return actions
