"""Live ask-timeout integration tests (this.i 5nqx7pmw).

The ask *reply* path needs a human (see test_interactive.py), but the *timeout*
path is fully automatable and exercises a code path the notify smoke test does
not: the daemon sends the question DM to real Discord and drives the
timeout/outcome machinery end to end. give_up_after_seconds=1 keeps each run to
roughly a second plus one throwaway DM.
"""

import pytest

from confer.client import DaemonClient

pytestmark = pytest.mark.integration


async def _ask_with_timeout(on_timeout: str) -> str:
    client = DaemonClient()
    await client.connect()
    try:
        return await client.ask(
            question=(
                "[confer integration test] No reply needed — this asks with a "
                "1-second deadline to exercise the timeout path."
            ),
            give_up_after_seconds=1,
            on_timeout=on_timeout,
        )
    finally:
        await client.close()


async def test_ask_times_out_use_best_judgment(integration_daemon):
    result = await _ask_with_timeout("use_best_judgment")
    assert result.startswith("No answer was received within the requested window."), result
    assert "best judgment" in result, result


async def test_ask_times_out_abort(integration_daemon):
    result = await _ask_with_timeout("abort")
    assert result.startswith("No answer was received within the requested window."), result
    assert "Stop work on this task" in result, result
