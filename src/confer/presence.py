"""Workstation away-presence state (Presence As A Workstation File, pf4nqkx7;
refined for Scheduled Away Transitions, sq7nkp4x).

Presence answers "is daniel effectively away from THIS workstation right now?"
It is stored as a small JSON file in XDG_RUNTIME_DIR (confer.presence). The file
is no longer a single binary fact: it carries a current sticky-away flag PLUS a
bounded queue of FUTURE away activations (each an epoch + optional note). File
absent ⇒ fully present with nothing scheduled.

EFFECTIVE-AWAY — the only thing the Stop hook cares about — is a pure function
of the file plus the clock: sticky-away is set, OR some pending entry's time has
arrived. So the hot-path read stays a dependency-free file stat (no daemon).
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from confer.paths import presence_file


@dataclass(frozen=True)
class PendingAway:
    """A scheduled future away activation (sq7nkp4x)."""

    at: float  # epoch seconds when this activation fires
    note: str | None = None


@dataclass(frozen=True)
class Presence:
    away: bool  # sticky away set immediately (confer away with no schedule)
    note: str | None = None  # note for the sticky away
    since: float | None = None  # epoch when sticky away was set
    pending: tuple[PendingAway, ...] = field(default_factory=tuple)

    def effective_away(self, now: float) -> bool:
        """Am I away right now? Sticky away, or any pending entry that has
        fired (its time has arrived)."""
        if self.away:
            return True
        return any(p.at <= now for p in self.pending)

    def active_note(self, now: float) -> str | None:
        """The note to surface for the current away state: the sticky note if
        sticky away, else the note of the most-recently-fired pending entry."""
        if self.away:
            return self.note
        fired = [p for p in self.pending if p.at <= now]
        if not fired:
            return None
        return max(fired, key=lambda p: p.at).note


def _present() -> Presence:
    return Presence(away=False)


def read_presence() -> Presence:
    """Read current presence. Absent or unreadable file ⇒ present (fail-safe:
    the away policy is opt-in, so anything ambiguous means not-away). A corrupt
    but non-empty marker still means "a marker exists" ⇒ sticky away without
    metadata (better to over-nudge than ignore an away daniel set)."""
    path = presence_file()
    try:
        raw = path.read_text()
    except (FileNotFoundError, OSError):
        return _present()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Presence(away=True)
    if not isinstance(data, dict):
        return Presence(away=True)
    pending = _read_pending(data.get("pending"))
    return Presence(
        away=bool(data.get("away", False)),
        note=data.get("note"),
        since=data.get("since"),
        pending=pending,
    )


def _read_pending(raw) -> tuple[PendingAway, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[PendingAway] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        at = item.get("at")
        if not isinstance(at, (int, float)):
            continue
        out.append(PendingAway(at=float(at), note=item.get("note")))
    return tuple(sorted(out, key=lambda p: p.at))


def save_presence(presence: Presence) -> None:
    """Persist presence. When fully present (not sticky-away and no pending),
    remove the file so 'file absent ⇒ present' stays the canonical empty
    state."""
    path = presence_file()
    if not presence.away and not presence.pending:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    payload: dict = {"away": presence.away}
    if presence.since is not None:
        payload["since"] = presence.since
    if presence.note is not None:
        payload["note"] = presence.note
    if presence.pending:
        payload["pending"] = [
            ({"at": p.at, "note": p.note} if p.note is not None else {"at": p.at})
            for p in presence.pending
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def is_away(now: float | None = None) -> bool:
    when = time.time() if now is None else now
    return read_presence().effective_away(when)


def set_away(note: str | None = None, *, now: float | None = None) -> Presence:
    """Go away NOW (immediate sticky away). Preserves any pending schedule —
    scheduling future aways and being away now are independent."""
    when = time.time() if now is None else now
    current = read_presence()
    presence = Presence(
        away=True, note=note, since=when, pending=current.pending
    )
    save_presence(presence)
    return presence


def schedule_away(
    at: float, note: str | None = None, *, now: float | None = None
) -> Presence:
    """Append a future away activation. Preserves current sticky state and any
    existing pending entries."""
    current = read_presence()
    new_pending = tuple(
        sorted(current.pending + (PendingAway(at=at, note=note),), key=lambda p: p.at)
    )
    presence = Presence(
        away=current.away,
        note=current.note,
        since=current.since,
        pending=new_pending,
    )
    save_presence(presence)
    return presence


def set_present(*, now: float | None = None) -> Presence:
    """Become present NOW (bare `back`, and what typing a prompt does). Clears
    sticky away and discards any already-FIRED pending entry, but LEAVES still-
    pending future entries (the ar7nqkp4 invariant that makes prompt-first
    scheduling safe)."""
    when = time.time() if now is None else now
    current = read_presence()
    future = tuple(p for p in current.pending if p.at > when)
    presence = Presence(away=False, pending=future)
    save_presence(presence)
    return presence


def cancel_pending(at: float) -> bool:
    """`back at <T>`: cancel the one pending entry matching epoch `at`. Returns
    True if an entry was removed, False if none matched (the caller reports the
    miss explicitly rather than silently no-op'ing, sq7nkp4x)."""
    current = read_presence()
    kept = tuple(p for p in current.pending if p.at != at)
    if len(kept) == len(current.pending):
        return False
    save_presence(
        Presence(
            away=current.away,
            note=current.note,
            since=current.since,
            pending=kept,
        )
    )
    return True


def clear_all() -> None:
    """`back all`: clear current away AND wipe the entire pending queue."""
    try:
        presence_file().unlink()
    except FileNotFoundError:
        pass
