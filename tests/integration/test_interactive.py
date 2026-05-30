"""Human-in-the-loop tests (this.i k4n7pqx2).

These cover the one boundary no automatable test can reach: the inbound
on_message -> route path, which structurally requires a real human sending a
real Discord DM. Run them with (--no-cov because this tier is coverage-exempt, this.i gjx4m7p2;
-s so the live ACTION REQUIRED prompt is not swallowed by pytest capture):

    uv run pytest --interactive -s --no-cov tests/integration/test_interactive.py

You (the operator) must watch the bot's Discord DM and act on the printed
prompt within the deadline. Skipped unless --interactive is passed.
"""

import asyncio
import time
from contextlib import suppress

import pytest

from confer.client import DaemonClient

pytestmark = pytest.mark.interactive

_HUMAN_DEADLINE_SECONDS = 180


def _tell(message: str) -> None:
    """Print an instruction straight to the controlling terminal so it is
    visible even under pytest output capture; fall back to stdout when there is
    no tty (e.g. run from an agent harness — the instruction still lands in
    captured output)."""
    banner = f"\n{'=' * 70}\n{message}\n{'=' * 70}\n"
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(banner)
            tty.flush()
            return
    except OSError:
        pass
    print(banner, flush=True)


async def test_ask_reply_round_trip(integration_daemon):
    """You reply to the bot's ask DM; the typed reply must come back through
    ask() (next-message-wins, this.i routing rt7nqp4m)."""
    nonce = "confer-hitl-pong"
    _tell(
        "ACTION REQUIRED (ask reply test):\n"
        f"  Within {_HUMAN_DEADLINE_SECONDS}s, reply to the confer bot's Discord "
        "DM\n"
        f"  with exactly:   {nonce}"
    )
    client = DaemonClient()
    await client.connect()
    try:
        result = await client.ask(
            question=f"[confer interactive test] Please reply with: {nonce}",
            give_up_after_seconds=_HUMAN_DEADLINE_SECONDS,
            on_timeout="use_best_judgment",
        )
    finally:
        await client.close()
    assert nonce in result, (
        f"expected your reply '{nonce}' to come back through ask(); got: {result!r}"
    )


async def test_check_messages_receives_unsolicited_dm(integration_daemon):
    """You send an unsolicited DM; it must surface via check_messages
    (broadcast to connected agents, this.i routing)."""
    nonce = "confer-hitl-inbound"
    _tell(
        "ACTION REQUIRED (inbound check_messages test):\n"
        f"  Within {_HUMAN_DEADLINE_SECONDS}s, send the confer bot an UNSOLICITED "
        "Discord DM\n"
        f"  containing the text:   {nonce}"
    )
    client = DaemonClient()
    await client.connect()
    result = ""
    try:
        deadline = time.monotonic() + _HUMAN_DEADLINE_SECONDS
        while time.monotonic() < deadline:
            result = await client.check_messages()
            if nonce in result:
                break
            await asyncio.sleep(2)
    finally:
        with suppress(Exception):
            await client.close()
    assert nonce in result, (
        f"expected your DM containing '{nonce}' to surface via check_messages; "
        f"last saw: {result!r}"
    )
