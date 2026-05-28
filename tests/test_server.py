from unittest.mock import AsyncMock, MagicMock, patch

from confer import server


async def test_mcp_server_registers_notify_tool():
    tools = await server.mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "notify" in tool_names


async def test_notify_tool_delegates_to_transport():
    fake_transport = MagicMock()
    fake_transport.notify = AsyncMock(return_value="sent at 2026-01-01T00:00:00+00:00")

    with patch.object(server, "_transport", fake_transport):
        result = await server.notify("hi")

    assert result == "sent at 2026-01-01T00:00:00+00:00"
    fake_transport.notify.assert_awaited_once_with("hi")


async def test_notify_tool_raises_when_transport_uninitialized():
    with patch.object(server, "_transport", None):
        import pytest

        with pytest.raises(RuntimeError, match="not initialized"):
            await server.notify("hi")


async def test_lifespan_initializes_and_closes_transport(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('discord_bot_token = "tok"\nconfer_user_id = 1\n')
    monkeypatch.setattr("confer.config.default_config_path", lambda: cfg)

    fake_transport = MagicMock()
    fake_transport.connect = AsyncMock()
    fake_transport.wait_for_ready = AsyncMock()
    fake_transport.close = AsyncMock()

    with patch.object(server, "DiscordTransport", return_value=fake_transport):
        async with server.lifespan(server.mcp):
            assert server._transport is fake_transport
            fake_transport.connect.assert_awaited_once()
            fake_transport.wait_for_ready.assert_awaited_once()

    fake_transport.close.assert_awaited_once()
    assert server._transport is None


def test_main_runs_server():
    with patch.object(server.mcp, "run") as mock_run:
        server.main()
    mock_run.assert_called_once()
