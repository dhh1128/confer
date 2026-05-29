import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from confer.daemon.transport import DiscordTransport, FAILURE_PREFIX, SUCCESS_PREFIX


def _make_transport_with_mocked_client() -> DiscordTransport:
    transport = DiscordTransport(token="test-token", user_id=42)
    transport._client = MagicMock()
    return transport


def test_transport_does_not_request_privileged_message_content_intent():
    """message_content is a PRIVILEGED intent; requesting it without enabling
    it in the developer portal makes the Gateway reject the connection
    (PrivilegedIntentsRequired). DM content is delivered without it, so confer
    must not request it. Regression guard for a bug caught in smoke testing."""
    transport = DiscordTransport(token="t", user_id=42)
    assert transport._client.intents.message_content is False
    assert transport._client.intents.dm_messages is True


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


async def test_connect_logs_in_then_starts_gateway_in_background_task():
    transport = _make_transport_with_mocked_client()

    async def never_returns(*args, **kwargs):
        await asyncio.sleep(3600)

    transport._client.login = AsyncMock()
    transport._client.connect = AsyncMock(side_effect=never_returns)

    await transport.connect()
    try:
        transport._client.login.assert_awaited_once_with("test-token")
        assert transport._connect_task is not None
        assert not transport._connect_task.done()
    finally:
        transport._connect_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await transport._connect_task


async def test_connect_propagates_login_failure_immediately():
    """A bad bot token should surface as a real exception at connect()
    time, not get buried in a fire-and-forget background task."""
    transport = _make_transport_with_mocked_client()
    transport._client.login = AsyncMock(side_effect=RuntimeError("LoginFailure"))

    with pytest.raises(RuntimeError, match="LoginFailure"):
        await transport.connect()
    assert transport._connect_task is None


async def test_wait_for_ready_delegates_to_client():
    transport = _make_transport_with_mocked_client()
    transport._client.wait_until_ready = AsyncMock()

    await transport.wait_for_ready()

    transport._client.wait_until_ready.assert_awaited_once_with()


async def test_wait_for_ready_raises_clear_error_on_timeout():
    transport = _make_transport_with_mocked_client()

    async def never_ready():
        await asyncio.sleep(3600)

    transport._client.wait_until_ready = AsyncMock(side_effect=never_ready)

    with pytest.raises(TimeoutError, match="Gateway did not become ready"):
        await transport.wait_for_ready(timeout=0.05)


async def test_connect_done_callback_logs_gateway_failure(caplog):
    import logging
    transport = _make_transport_with_mocked_client()
    transport._client.login = AsyncMock()
    transport._client.connect = AsyncMock(side_effect=RuntimeError("gateway dropped"))

    with caplog.at_level(logging.ERROR, logger="confer.daemon.transport"):
        await transport.connect()
        with pytest.raises(RuntimeError):
            await transport._connect_task
    assert any(
        "Gateway task ended with exception" in record.getMessage()
        for record in caplog.records
    )


async def test_connect_done_callback_silent_on_normal_completion(caplog):
    import logging
    transport = _make_transport_with_mocked_client()
    transport._client.login = AsyncMock()
    transport._client.connect = AsyncMock(return_value=None)

    with caplog.at_level(logging.ERROR, logger="confer.daemon.transport"):
        await transport.connect()
        await transport._connect_task
    assert not any(
        "Gateway task ended with exception" in record.getMessage()
        for record in caplog.records
    )


async def test_connect_done_callback_silent_on_cancel():
    transport = _make_transport_with_mocked_client()

    async def long_running(*args, **kwargs):
        await asyncio.sleep(3600)

    transport._client.login = AsyncMock()
    transport._client.connect = AsyncMock(side_effect=long_running)

    await transport.connect()
    transport._connect_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await transport._connect_task
    # No assertion needed; the test verifies the callback doesn't raise on
    # cancellation (it would surface as an unhandled exception in the loop).


def test_is_ready_delegates_to_client():
    transport = _make_transport_with_mocked_client()
    transport._client.is_ready = MagicMock(return_value=True)
    assert transport.is_ready() is True
    transport._client.is_ready.assert_called_once_with()


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


async def test_on_user_message_callback_fires_for_matching_dm():
    received: list[str] = []

    async def callback(content: str) -> None:
        received.append(content)

    transport = DiscordTransport(token="t", user_id=42, on_user_message=callback)
    transport._client = MagicMock()
    await transport._handle_message(_make_dm_message(author_id=42, content="hi"))
    assert received == ["hi"]


async def test_on_user_message_ignored_when_no_callback_registered():
    transport = DiscordTransport(token="t", user_id=42)
    transport._client = MagicMock()
    # Should not raise even though no callback is set.
    await transport._handle_message(_make_dm_message(author_id=42, content="hi"))


async def test_on_user_message_ignores_non_dm_messages():
    received: list[str] = []

    async def callback(content: str) -> None:
        received.append(content)

    transport = DiscordTransport(token="t", user_id=42, on_user_message=callback)
    transport._client = MagicMock()
    msg = MagicMock()
    msg.author.id = 42
    msg.channel = MagicMock(spec=[])  # not a DMChannel
    await transport._handle_message(msg)
    assert received == []


async def test_on_user_message_ignores_messages_from_wrong_user():
    received: list[str] = []

    async def callback(content: str) -> None:
        received.append(content)

    transport = DiscordTransport(token="t", user_id=42, on_user_message=callback)
    transport._client = MagicMock()
    await transport._handle_message(_make_dm_message(author_id=99, content="hi"))
    assert received == []


async def test_on_user_message_swallows_callback_exceptions(caplog):
    import logging

    async def raising_callback(content: str) -> None:
        raise RuntimeError("callback boom")

    transport = DiscordTransport(
        token="t", user_id=42, on_user_message=raising_callback
    )
    transport._client = MagicMock()
    with caplog.at_level(logging.ERROR, logger="confer.daemon.transport"):
        # Should not raise — a misbehaving callback must not tear down the
        # discord.py event loop.
        await transport._handle_message(_make_dm_message(author_id=42, content="hi"))
    assert any(
        "on_user_message callback failed" in record.getMessage()
        for record in caplog.records
    )


def _make_dm_message(author_id: int, content: str) -> MagicMock:
    msg = MagicMock()
    msg.author.id = author_id
    msg.content = content
    msg.channel = MagicMock(spec=discord.DMChannel)
    return msg


async def test_connect_registers_on_message_callback_that_routes_to_handle_message():
    """Verify the on_message closure created inside connect() actually
    delegates to _handle_message (covers the inner function body)."""
    received: list[str] = []

    async def callback(content: str) -> None:
        received.append(content)

    transport = DiscordTransport(token="t", user_id=42, on_user_message=callback)
    transport._client = MagicMock()
    transport._client.login = AsyncMock()

    async def never_returns(*args, **kwargs):
        await asyncio.sleep(3600)

    transport._client.connect = AsyncMock(side_effect=never_returns)

    captured_event_handlers: list = []

    def capture_event(coro):
        captured_event_handlers.append(coro)
        return coro

    transport._client.event = capture_event

    await transport.connect()
    try:
        assert len(captured_event_handlers) == 1
        on_message = captured_event_handlers[0]
        # Invoke the registered handler with a DM from the configured user.
        await on_message(_make_dm_message(author_id=42, content="hello"))
        assert received == ["hello"]
    finally:
        transport._connect_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await transport._connect_task
