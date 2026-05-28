from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from confer import server


async def test_mcp_server_registers_notify_tool():
    tools = await server.mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "notify" in tool_names


async def test_mcp_server_advertises_instructions_block():
    """Per Notify Self-Description Policy (4kxp7qnj): a fresh client should
    see when-to-use / when-not-to-use guidance in the server's
    instructions block."""
    instructions = server.mcp.instructions
    assert instructions is not None
    assert "USE the `notify` tool when" in instructions
    assert "DO NOT use `notify`" in instructions
    assert "out-of-band" in instructions.lower()


async def test_notify_tool_description_leads_with_purpose_not_mechanics():
    """The docstring on the tool should lead with WHY, then HOW."""
    tools = await server.mcp.list_tools()
    notify_tool = next(t for t in tools if t.name == "notify")
    desc = notify_tool.description or ""
    # First sentence should be about pinging the user, not about return type
    first_line = desc.strip().splitlines()[0]
    assert "out-of-band" in first_line.lower() or "ping" in first_line.lower()
    # Return-format info should still be present but later
    assert "sent at" in desc
    assert "NOTIFY_FAILED" in desc


async def test_notify_message_parameter_carries_guidance():
    """Per Notify Self-Description Policy: the message parameter must have
    a description telling the agent what shape the payload should take."""
    tools = await server.mcp.list_tools()
    notify_tool = next(t for t in tools if t.name == "notify")
    schema = notify_tool.inputSchema
    message_prop = schema["properties"]["message"]
    assert "description" in message_prop
    desc = message_prop["description"]
    # The phone-friendly URL-preferred-over-file-path note is the key
    # mobile-UX guidance; tests assert it stays.
    assert "URL" in desc
    assert "mobile" in desc.lower()


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
