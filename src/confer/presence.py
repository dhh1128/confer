"""Workstation away-presence state (Presence As A Workstation File, pf4nqkx7).

Presence is a single fact — is the user at THIS workstation? — stored as a
file in XDG_RUNTIME_DIR rather than in the daemon, because the consumer is a
global Claude Code Stop hook on a hot path that must not depend on the daemon
(see eh7nqkp4). File present ⇒ away; file absent ⇒ present.
"""

import json
import time
from dataclasses import dataclass

from confer.paths import presence_file


@dataclass(frozen=True)
class Presence:
    away: bool
    note: str | None = None
    since: float | None = None  # epoch seconds when away was set


def read_presence() -> Presence:
    """Read current presence. Absent or unreadable file ⇒ present (fail-safe:
    the away policy is opt-in, so anything ambiguous means not-away)."""
    path = presence_file()
    try:
        raw = path.read_text()
    except (FileNotFoundError, OSError):
        return Presence(away=False)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # A corrupt marker still means "a marker exists" → treat as away, but
        # without metadata. Better to over-nudge than to silently ignore an
        # away the user explicitly set.
        return Presence(away=True)
    return Presence(
        away=bool(data.get("away", True)),
        note=data.get("note"),
        since=data.get("since"),
    )


def is_away() -> bool:
    return read_presence().away


def set_away(note: str | None = None, *, now: float | None = None) -> Presence:
    """Mark the workstation away. `now` is injectable for deterministic tests."""
    when = time.time() if now is None else now
    presence = Presence(away=True, note=note, since=when)
    path = presence_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"away": True, "since": when}
    if note is not None:
        payload["note"] = note
    path.write_text(json.dumps(payload) + "\n")
    return presence


def set_present() -> None:
    """Clear away state. Idempotent — no-op if already present."""
    try:
        presence_file().unlink()
    except FileNotFoundError:
        pass
