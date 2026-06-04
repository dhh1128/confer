"""Support for the integration-freshness gate (this.i m4xq7npk).

NOT a test module (no test_ prefix, so pytest does not collect it). Holds the
stamp-file location, the max-age policy, and pure read/write/enforce helpers
shared by the freshness test (tests/test_integration_freshness.py) and the
auto-stamp hook (tests/conftest.py). Lives under tests/ — not src/ — so it sits
outside the 100% production-coverage gate.
"""

import os
from datetime import date, timedelta
from pathlib import Path

from confer.config import default_config_path

# The checked-in record of when the integration tier last passed.
STAMP_PATH = Path(__file__).parent / "integration" / "last-verified.txt"

# "No more than 2 months old" — 62 days is a generous two calendar months.
MAX_AGE = timedelta(days=62)


def read_stamp() -> date | None:
    """The stamped date, or None if the file is missing or unparseable."""
    try:
        text = STAMP_PATH.read_text().strip()
    except FileNotFoundError:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def write_stamp(today: date) -> None:
    STAMP_PATH.write_text(f"{today.isoformat()}\n")


def is_enforced() -> bool:
    """Whether the gate bites on this machine. Only where it is both meaningful
    and satisfiable: not under CI, and a real confer config present (so the
    integration tier is actually runnable). Everywhere else the freshness test
    skips."""
    if os.environ.get("CI"):
        return False
    return default_config_path().exists()
