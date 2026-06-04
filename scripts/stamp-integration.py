#!/usr/bin/env python3
"""Manual escape hatch to refresh the integration-freshness stamp (this.i
m4xq7npk).

Normally the stamp refreshes automatically when the integration tier passes
(pytest_sessionfinish hook in tests/conftest.py). Use this only to set the
stamp by hand right after a known-good integration run, e.g. when you ran the
tier in a way that bypassed the hook. Writes today's date to
tests/integration/last-verified.txt; commit the result.
"""

import sys
from datetime import date
from pathlib import Path

# Make tests/ importable so we reuse the single source of truth for the policy.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

import freshness  # noqa: E402


def main() -> int:
    today = date.today()
    freshness.write_stamp(today)
    print(f"Stamped {freshness.STAMP_PATH} = {today.isoformat()}")
    print("Remember to commit the stamp.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
