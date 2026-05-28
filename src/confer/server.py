from contextlib import asynccontextmanager
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from confer.client import DaemonClient


_SERVER_INSTRUCTIONS = """\
This server pings the user out-of-band via Discord DM when terminal output
isn't enough. The user may be away from the keyboard for minutes to hours.

USE the `notify` tool when:
- A long-running task you started has finished and the user is likely away
  (build, deploy, test suite, scheduled job).
- You hit a blocker that needs the user's input AND the conversation has
  been idle long enough that they may have context-switched.
- The user explicitly asked to be told when something happens.

DO NOT use `notify` for:
- Routine progress or status inside an active conversation (the terminal
  is the right channel for that).
- Output the user would see by reading your reply in the chat anyway.
- Anything where the message would arrive before the user could plausibly
  have stepped away.
"""


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


mcp = FastMCP("confer", lifespan=lifespan, instructions=_SERVER_INSTRUCTIONS)


_MESSAGE_DESCRIPTION = (
    "Short, information-dense message body. Aim for one or two sentences. "
    "Include the most important context: file path, error gist, success "
    "criterion, PR or run URL. Example: \"tests/test_auth.py failed - JWT "
    "signature rejected; see auth/jwt.py:42\". Avoid wall-of-text dumps; "
    "if you need to share more, prefer a public URL (PR, issue, hosted log) "
    "over a local file path - the user reads notifications on mobile and "
    "can't reach the workstation filesystem. A local path is still better "
    "than nothing if no URL is available."
)


@mcp.tool()
async def notify(
    message: Annotated[str, Field(description=_MESSAGE_DESCRIPTION)],
) -> str:
    """Ping the user out-of-band via Discord DM.

    Use sparingly - see the confer server's instructions for when this is
    appropriate vs. when terminal output is enough. Returns
    "sent at <ISO-8601 UTC timestamp>" on success, or
    "<NOTIFY_FAILED: <reason>>" on failure (no retries).
    """
    if _client is None:
        raise RuntimeError(
            "DaemonClient not initialized; server lifespan did not start"
        )
    return await _client.notify(message)


def main() -> None:
    mcp.run()
