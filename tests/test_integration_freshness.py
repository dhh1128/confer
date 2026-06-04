"""Freshness gate for the integration tier (this.i m4xq7npk).

A deliberately time-dependent test: it forces the integration tier to be
re-run periodically while the code evolves, so Discord / discord.py API drift
(4vxn7pqm) cannot ship silently between rare manual integration runs. Scoped by
freshness.is_enforced() to bite only an equipped machine (real config, not CI);
it skips everywhere else. The stamp is refreshed automatically by the
auto-stamp hook in tests/conftest.py on a green integration run.
"""

from datetime import date

import pytest

import freshness

_RERUN_HINT = (
    "Re-run the integration tier with "
    "`CONFER_INTEGRATION=1 uv run pytest --no-cov -m integration` "
    "(which auto-refreshes the stamp on success), then commit "
    f"{freshness.STAMP_PATH.name}."
)


def test_integration_tests_verified_recently():
    if not freshness.is_enforced():
        pytest.skip(
            "freshness gate is enforced only with a real config and outside CI"
        )
    stamp = freshness.read_stamp()
    if stamp is None:
        pytest.fail(
            f"No usable integration freshness stamp at {freshness.STAMP_PATH}. "
            + _RERUN_HINT
        )
    age = date.today() - stamp
    assert age <= freshness.MAX_AGE, (
        f"Integration tests last verified {stamp.isoformat()} "
        f"({age.days} days ago; limit {freshness.MAX_AGE.days}). " + _RERUN_HINT
    )
