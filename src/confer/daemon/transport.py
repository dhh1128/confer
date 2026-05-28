import asyncio
from datetime import datetime, timezone

import discord


SUCCESS_PREFIX = "sent at "
FAILURE_PREFIX = "<NOTIFY_FAILED: "
FAILURE_SUFFIX = ">"


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
        self._connect_task = asyncio.create_task(self._client.start(self._token))

    async def wait_for_ready(self) -> None:
        await self._client.wait_until_ready()

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
