import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

import discord


SUCCESS_PREFIX = "sent at "
FAILURE_PREFIX = "<NOTIFY_FAILED: "
FAILURE_SUFFIX = ">"

_READY_TIMEOUT_SECONDS = 30.0

log = logging.getLogger(__name__)


OnUserMessage = Callable[[str], Awaitable[None]]


class DiscordTransport:
    def __init__(
        self,
        token: str,
        user_id: int,
        on_user_message: OnUserMessage | None = None,
    ) -> None:
        self._token = token
        self._user_id = user_id
        self._on_user_message = on_user_message
        intents = discord.Intents.default()
        intents.dm_messages = True
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._dm_channel: discord.DMChannel | None = None
        self._connect_task: asyncio.Task | None = None

    async def connect(self) -> None:
        # login() must complete before wait_until_ready() can be called —
        # it's where discord.py initializes self._ready. Failures here
        # (invalid token, network down) propagate immediately with a real
        # backtrace, rather than getting buried in a background task.
        await self._client.login(self._token)
        # discord.py registers events by callback __name__. Bind via a
        # named local wrapper so the on_message hook reaches _handle_message.
        async def on_message(message):
            await self._handle_message(message)
        self._client.event(on_message)
        # connect() runs the Gateway websocket loop and never returns
        # until the connection is closed, so it must be a background task.
        self._connect_task = asyncio.create_task(self._client.connect())
        self._connect_task.add_done_callback(self._on_connect_task_done)

    async def _handle_message(self, message) -> None:
        """on_message handler logic. Filters DM messages from the configured
        user and forwards content to the on_user_message callback (if
        registered). Callback exceptions are logged but not re-raised so a
        misbehaving daemon doesn't tear down the discord.py event loop."""
        if self._on_user_message is None:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return
        if message.author.id != self._user_id:
            return
        try:
            await self._on_user_message(message.content)
        except Exception as exc:
            log.error("on_user_message callback failed: %r", exc)

    @staticmethod
    def _on_connect_task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("Discord Gateway task ended with exception: %r", exc)

    async def wait_for_ready(self, timeout: float = _READY_TIMEOUT_SECONDS) -> None:
        try:
            await asyncio.wait_for(self._client.wait_until_ready(), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise TimeoutError(
                f"Discord Gateway did not become ready within {timeout}s; "
                f"check bot token validity and network connectivity"
            ) from e

    def is_ready(self) -> bool:
        return self._client.is_ready()

    async def _get_dm_channel(self) -> discord.DMChannel:
        if self._dm_channel is not None:
            return self._dm_channel
        user = await self._client.fetch_user(self._user_id)
        self._dm_channel = await user.create_dm()
        return self._dm_channel

    async def notify(self, message: str) -> str:
        try:
            channel = await self._get_dm_channel()
            await channel.send(message)
        except discord.NotFound:
            return (
                f"{FAILURE_PREFIX}user not found "
                f"(user_id={self._user_id}){FAILURE_SUFFIX}"
            )
        except discord.HTTPException as exc:
            return f"{FAILURE_PREFIX}{type(exc).__name__}: {exc}{FAILURE_SUFFIX}"
        return f"{SUCCESS_PREFIX}{datetime.now(timezone.utc).isoformat()}"

    async def close(self) -> None:
        await self._client.close()
        if self._connect_task is None:
            return
        try:
            await self._connect_task
        except Exception:
            pass
