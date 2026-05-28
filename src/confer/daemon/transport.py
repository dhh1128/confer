import asyncio
import logging
from datetime import datetime, timezone

import discord


SUCCESS_PREFIX = "sent at "
FAILURE_PREFIX = "<NOTIFY_FAILED: "
FAILURE_SUFFIX = ">"

_READY_TIMEOUT_SECONDS = 30.0

log = logging.getLogger(__name__)


class DiscordTransport:
    def __init__(self, token: str, user_id: int) -> None:
        self._token = token
        self._user_id = user_id
        intents = discord.Intents.default()
        intents.dm_messages = True
        self._client = discord.Client(intents=intents)
        self._dm_channel: discord.DMChannel | None = None
        self._connect_task: asyncio.Task | None = None

    async def connect(self) -> None:
        # login() must complete before wait_until_ready() can be called —
        # it's where discord.py initializes self._ready. Failures here
        # (invalid token, network down) propagate immediately with a real
        # backtrace, rather than getting buried in a background task.
        await self._client.login(self._token)
        # connect() runs the Gateway websocket loop and never returns
        # until the connection is closed, so it must be a background task.
        self._connect_task = asyncio.create_task(self._client.connect())
        self._connect_task.add_done_callback(self._on_connect_task_done)

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
