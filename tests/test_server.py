from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from confer import server


async def test_mcp_server_registers_notify_tool():
    tools = await server.mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "notify" in tool_names


async def test_notify_tool_delegates_to_daemon_client():
    fake_client = MagicMock()
    fake_client.notify = AsyncMock(return_value="sent at 2026-01-01T00:00:00+00:00")

    with patch.object(server, "_client", fake_client):
        result = await server.notify("hi")

    assert result == "sent at 2026-01-01T00:00:00+00:00"
    fake_client.notify.assert_awaited_once_with("hi")


async def test_notify_tool_raises_when_client_uninitialized():
    with patch.object(server, "_client", None):
        with pytest.raises(RuntimeError, match="not initialized"):
            await server.notify("hi")


async def test_lifespan_initializes_and_closes_daemon_client():
    fake_client = MagicMock()
    fake_client.connect = AsyncMock()
    fake_client.close = AsyncMock()

    with patch.object(server, "DaemonClient", return_value=fake_client):
        async with server.lifespan(server.mcp):
            assert server._client is fake_client
            fake_client.connect.assert_awaited_once()

    fake_client.close.assert_awaited_once()
    assert server._client is None


def test_main_runs_server():
    with patch.object(server.mcp, "run") as mock_run:
        server.main()
    mock_run.assert_called_once()
