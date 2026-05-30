"""Live notify smoke test — the first integration-tier test (this.i 5nqx7pmw).

Proves the full notify path end to end against a real Discord bot: spawn the
daemon, confirm the Gateway is ready, send a notify, and assert it reports
success. Gated + isolated by the integration_daemon fixture; skipped unless
CONFER_INTEGRATION=1 and a real config is present.
"""

import asyncio
from contextlib import suppress

import pytest

from confer.client import DaemonClient
from confer.paths import socket_path
from confer.protocol import Status, StatusResult, decode, encode

pytestmark = pytest.mark.integration


async def _query_gateway_state() -> str:
    """Open a raw connection and ask the daemon for its Gateway state."""
    reader, writer = await asyncio.open_unix_connection(str(socket_path()))
    try:
        writer.write(encode(Status(request_id="integration-status")))
        await writer.drain()
        line = await reader.readline()
        msg = decode(line)
        assert isinstance(msg, StatusResult), msg
        return msg.gateway_state
    finally:
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()


async def test_notify_reaches_discord(integration_daemon):
    # The fixture only yields once the socket is bound, which serve() does after
    # wait_for_ready() — so this should already be "ready". Asserted explicitly
    # per the chosen test scope (notify smoke + gateway ready).
    assert await _query_gateway_state() == "ready"

    client = DaemonClient()
    await client.connect()
    try:
        result = await client.notify(
            "confer integration smoke test — please ignore."
        )
    finally:
        await client.close()

    assert result.startswith("sent at "), result


async def test_notify_reports_failure_for_unknown_user(integration_daemon_bad_user):
    # Real token, bogus confer_user_id (1): fetch_user must raise discord.NotFound,
    # which our transport maps to the failure sentinel. Proves the error branch
    # against real discord.py, not a mock (narrows Mock Depth, this.i 4vxn7pqm).
    client = DaemonClient()
    await client.connect()
    try:
        result = await client.notify("this should never be delivered")
    finally:
        await client.close()

    assert result.startswith("<NOTIFY_FAILED:"), result
    assert "user not found" in result, result
