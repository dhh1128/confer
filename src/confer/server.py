from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from confer.client import DaemonClient


_client: DaemonClient | None = None


@asynccontextmanager
async def lifespan(app: FastMCP):
    global _client
    _client = DaemonClient()
    await _client.connect()
    try:
        yield
    finally:
        try:
            await _client.close()
        finally:
            _client = None


mcp = FastMCP("confer", lifespan=lifespan)


@mcp.tool()
async def notify(message: str) -> str:
    """Send a notification to the user via Discord DM.

    Returns "sent at <ISO-8601 UTC timestamp>" on success, or
    "<NOTIFY_FAILED: <reason>>" on failure (no retries). The message is
    prefixed with this agent's auto-derived label so the user can tell
    which agent is talking when multiple agents are running.
    """
    if _client is None:
        raise RuntimeError(
            "DaemonClient not initialized; server lifespan did not start"
        )
    return await _client.notify(message)


def main() -> None:
    mcp.run()
