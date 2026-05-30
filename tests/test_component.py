"""Component tier (this.i c7nq4xkp).

Wires the REAL Daemon + real serve() on a real tmp-dir unix socket to a REAL
DaemonClient across that socket, faking ONLY the discord.py transport via the
existing `transport=` constructor seam. This closes the seam the unit tests
leave open — there, the real serve() is tested against a mocked transport and
the real client against a hand-rolled fake daemon, so the two real halves never
meet over the wire. Deterministic, network-free, human-free, CI-run, and
coverage-counted (it is all our own code).

FakeTransport also exposes inject(content), which drives the daemon's
on_user_message callback to simulate an inbound Discord DM — letting this tier
cover, in CI, the inbound -> route -> IPC -> client path that otherwise needs a
live human (interactive tier) or is unreachable (integration: the bot cannot DM
itself).
"""

import asyncio
from datetime import datetime, timezone

import pytest

from confer import client as client_mod
from confer.client import DaemonClient
from confer.daemon.core import Daemon
from confer.daemon.transport import SUCCESS_PREFIX


class FakeTransport:
    """Stand-in for DiscordTransport at the discord.py boundary. Implements the
    interface the Daemon calls (connect / wait_for_ready / is_ready / notify /
    close) and records outbound sends, plus inject() to simulate an inbound DM
    from the configured user."""

    def __init__(self) -> None:
        self.on_user_message = None
        self.sent: list[str] = []
        self._ready = False

    async def connect(self) -> None:
        self._ready = True

    async def wait_for_ready(self, timeout: float = 30.0) -> None:
        self._ready = True

    def is_ready(self) -> bool:
        return self._ready

    async def notify(self, message: str) -> str:
        self.sent.append(message)
        return f"{SUCCESS_PREFIX}{datetime.now(timezone.utc).isoformat()}"

    async def close(self) -> None:
        self._ready = False

    async def inject(self, content: str) -> None:
        """Simulate an inbound Discord DM from the configured user."""
        if self.on_user_message is not None:
            await self.on_user_message(content)


@pytest.fixture
async def component(tmp_path, monkeypatch):
    """Real Daemon serving on a real tmp socket with a FakeTransport, plus a
    connected real DaemonClient. Yields (transport, client)."""
    sock = tmp_path / "confer.sock"
    pid = tmp_path / "confer.pid"

    transport = FakeTransport()
    daemon = Daemon(transport=transport)
    # Mirror __main__._run_daemon's wiring: an inbound DM routes through the
    # daemon's dispatcher.
    transport.on_user_message = daemon._dispatch_user_message

    serve_task = asyncio.create_task(daemon.serve(sock, pid))
    for _ in range(200):
        if sock.exists():
            break
        await asyncio.sleep(0.01)
    assert sock.exists(), "daemon did not bind the socket"

    # Point the real client at this socket so connect() does not auto-spawn.
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)
    client = DaemonClient(label_preferred="component-test")
    await client.connect()

    try:
        yield transport, client
    finally:
        await client.close()
        daemon.stop()
        await serve_task


async def test_notify_crosses_the_wire_to_the_transport(component):
    transport, client = component
    result = await client.notify("build finished")

    assert result.startswith(SUCCESS_PREFIX), result
    # The daemon tags and labels the body before handing it to the transport.
    assert any("build finished" in body for body in transport.sent), transport.sent
    assert any("component-test" in body for body in transport.sent), transport.sent


async def test_injected_reply_returns_through_ask(component):
    transport, client = component

    ask_task = asyncio.create_task(
        client.ask(
            "Proceed with the rebase?",
            give_up_after_seconds=30,
            on_timeout="use_best_judgment",
        )
    )

    # Wait until the daemon has sent the question DM (the ask is now pending and
    # eligible for next-message-wins), then simulate the user's reply.
    for _ in range(200):
        if transport.sent:
            break
        await asyncio.sleep(0.01)
    assert transport.sent, "ask did not send a question DM"

    await transport.inject("yes, go ahead")

    result = await asyncio.wait_for(ask_task, timeout=5)
    assert result == "yes, go ahead", result


async def test_unsolicited_dm_surfaces_via_check_messages(component):
    transport, client = component

    # No ask pending + a connected agent -> the inbound DM broadcasts into the
    # agent's queue.
    await transport.inject("heads up: requirements changed")

    result = await client.check_messages()
    assert "requirements changed" in result, result
