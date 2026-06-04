"""Time-input parsing for scheduled away (sq7nkp4x).

Turns the user's `--in <minutes>` / `--at <HHMM>` into an absolute activation
epoch, applying the two rules from sq7nkp4x:
  - `at <HHMM>` is that clock time TODAY, or — if it has already passed —
    the same time TOMORROW. This single rule also yields the 24h cap for free:
    no input can name a moment more than 24h ahead.
  - times are in workstation LOCAL time; we return epoch seconds (DST handled
    by the platform via the local-time conversion).

`now` and a `localtime` converter are injectable so the logic is deterministic
under test without monkeypatching wall-clock.
"""

import time as _time
from datetime import datetime, timedelta


class AwayTimeError(ValueError):
    """Raised for malformed --in / --at input; the CLI surfaces the message."""


def parse_in_minutes(raw: str, *, now: float | None = None) -> float:
    """`--in <minutes>` → activation epoch. Minutes must be a non-negative
    number; 0 means now."""
    when = _time.time() if now is None else now
    try:
        minutes = float(raw)
    except (TypeError, ValueError):
        raise AwayTimeError(f"--in expects a number of minutes, got {raw!r}")
    if minutes < 0:
        raise AwayTimeError(f"--in minutes must be >= 0, got {minutes}")
    return when + minutes * 60.0


def parse_at_clock(raw: str, *, now: float | None = None) -> float:
    """`--at <HHMM>` (or HH:MM) → activation epoch in local time, rolling to
    tomorrow if the time already passed today (sq7nkp4x)."""
    when = _time.time() if now is None else now
    hour, minute = _parse_hhmm(raw)
    local = datetime.fromtimestamp(when)
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target.timestamp() <= when:
        target = target + timedelta(days=1)
    return target.timestamp()


def _parse_hhmm(raw: str) -> tuple[int, int]:
    s = raw.strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) != 2:
            raise AwayTimeError(f"--at expects HHMM or HH:MM, got {raw!r}")
        hh, mm = parts
    elif len(s) == 4 and s.isdigit():
        hh, mm = s[:2], s[2:]
    elif len(s) in (1, 2) and s.isdigit():
        hh, mm = s, "0"  # bare hour, e.g. "9" → 09:00
    else:
        raise AwayTimeError(f"--at expects HHMM or HH:MM (24-hour), got {raw!r}")
    try:
        hour, minute = int(hh), int(mm)
    except ValueError:
        raise AwayTimeError(f"--at expects numbers, got {raw!r}")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise AwayTimeError(
            f"--at time out of range (00:00–23:59), got {raw!r}"
        )
    return hour, minute
