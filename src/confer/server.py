from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from confer.config import Settings
from confer.daemon.transport import DiscordTransport


_transport: DiscordTransport | None = None


@asynccontextmanager
async def lifespan(app: FastMCP):
    global _transport
    settings = Settings.load()
    _transport = DiscordTransport(
        token=settings.discord_bot_token,
        user_id=settings.confer_user_id,
    )
    await _transport.connect()
    await _transport.wait_for_ready()
    try:
        yield
    finally:
        try:
            await _transport.close()
        finally:
            _transport = None


mcp = FastMCP("confer", lifespan=lifespan)


@mcp.tool()
async def notify(message: str) -> str:
    """Send a notification to the user via Discord DM.

    Returns "sent at <ISO-8601 UTC timestamp>" on success, or
    "<NOTIFY_FAILED: <reason>>" on failure (no retries).
    """
    if _transport is None:
        raise RuntimeError(
            "DiscordTransport not initialized; server lifespan did not start"
        )
    return await _transport.notify(message)


def main() -> None:
    mcp.run()
