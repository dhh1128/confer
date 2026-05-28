import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from confer.transport import DiscordTransport, FAILURE_PREFIX, SUCCESS_PREFIX


def _make_transport_with_mocked_client() -> DiscordTransport:
    transport = DiscordTransport(token="test-token", user_id=42)
    transport._client = MagicMock()
    return transport


def _mocked_response(status: int = 500) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.reason = "mocked"
    return response


async def test_notify_sends_message_to_dm():
    transport = _make_transport_with_mocked_client()
    mock_user = MagicMock()
    mock_dm_channel = MagicMock()
    mock_dm_channel.send = AsyncMock()
    mock_user.create_dm = AsyncMock(return_value=mock_dm_channel)
    transport._client.fetch_user = AsyncMock(return_value=mock_user)

    result = await transport.notify("hello there")

    assert result.startswith(SUCCESS_PREFIX)
    mock_dm_channel.send.assert_awaited_once_with("hello there")


async def test_notify_returns_failure_sentinel_when_user_not_found():
    transport = _make_transport_with_mocked_client()
    transport._client.fetch_user = AsyncMock(
        side_effect=discord.NotFound(_mocked_response(404), "User does not exist")
    )

    result = await transport.notify("hello")

    assert result.startswith(FAILURE_PREFIX)
    assert "user not found" in result.lower()


async def test_notify_returns_failure_sentinel_when_send_fails():
    transport = _make_transport_with_mocked_client()
    mock_user = MagicMock()
    mock_dm_channel = MagicMock()
    mock_dm_channel.send = AsyncMock(
        side_effect=discord.HTTPException(_mocked_response(500), "boom")
    )
    mock_user.create_dm = AsyncMock(return_value=mock_dm_channel)
    transport._client.fetch_user = AsyncMock(return_value=mock_user)

    result = await transport.notify("hello")

    assert result.startswith(FAILURE_PREFIX)
    assert "HTTPException" in result


async def test_dm_channel_is_cached_across_calls():
    transport = _make_transport_with_mocked_client()
    mock_user = MagicMock()
    mock_dm_channel = MagicMock()
    mock_dm_channel.send = AsyncMock()
    mock_user.create_dm = AsyncMock(return_value=mock_dm_channel)
    transport._client.fetch_user = AsyncMock(return_value=mock_user)

    await transport.notify("first")
    await transport.notify("second")

    transport._client.fetch_user.assert_awaited_once()
    mock_user.create_dm.assert_awaited_once()
    assert mock_dm_channel.send.await_count == 2


async def test_connect_starts_client_in_background_task():
    transport = _make_transport_with_mocked_client()

    async def never_returns(*args, **kwargs):
        await asyncio.sleep(3600)

    transport._client.start = AsyncMock(side_effect=never_returns)

    await transport.connect()
    try:
        assert transport._connect_task is not None
        assert not transport._connect_task.done()
        transport._client.start.assert_called_once_with("test-token")
    finally:
        transport._connect_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await transport._connect_task


async def test_wait_for_ready_delegates_to_client():
    transport = _make_transport_with_mocked_client()
    transport._client.wait_until_ready = AsyncMock()

    await transport.wait_for_ready()

    transport._client.wait_until_ready.assert_awaited_once_with()


async def test_close_closes_client_when_no_connect_task():
    transport = _make_transport_with_mocked_client()
    transport._client.close = AsyncMock()

    await transport.close()

    transport._client.close.assert_awaited_once()


async def test_close_awaits_connect_task_when_present():
    transport = _make_transport_with_mocked_client()
    transport._client.close = AsyncMock()

    async def finishes_quickly():
        return None

    transport._connect_task = asyncio.create_task(finishes_quickly())

    await transport.close()

    transport._client.close.assert_awaited_once()
    assert transport._connect_task.done()


async def test_close_swallows_exceptions_from_connect_task():
    transport = _make_transport_with_mocked_client()
    transport._client.close = AsyncMock()

    async def raises():
        raise RuntimeError("boom")

    transport._connect_task = asyncio.create_task(raises())

    await transport.close()  # must not raise

    transport._client.close.assert_awaited_once()
    assert transport._connect_task.done()
