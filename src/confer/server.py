from contextlib import asynccontextmanager
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from confer.client import DaemonClient


_SERVER_INSTRUCTIONS = """\
This server lets you reach the user out-of-band when terminal output isn't
enough. confer routes through Discord today; treat it as an opaque
spokesperson that delivers your messages and returns answers — don't assume
how the user is actually responding.

USE the `notify` tool when:
- A long-running task you started has finished and the user is likely away
  (build, deploy, test suite, scheduled job).
- You hit a blocker that needs the user's input AND the conversation has
  been idle long enough that they may have context-switched.
- The user explicitly asked to be told when something happens.

USE the `ask` tool when:
- You need an answer from the user before you can continue, AND
- The user is likely not at the keyboard right now (else just ask in chat).

When using `ask`, choose on_timeout deliberately:
- "use_best_judgment" for moderate-stakes questions where you can reasonably
  proceed if the user is unreachable.
- "abort" for high-stakes questions (destructive operations, irreversible
  choices). On timeout you'll be told to stop and surface state.
You will always receive a natural-language string answer; never a sentinel
token or an exception. If the answer indicates no human response arrived,
follow the directive in that string.

USE the `check_messages` tool when:
- You're at a natural pause point in a long-running task and want to see
  whether the user has sent any unsolicited input.
- Before making a major decision the user might want to redirect.
- After a long-running operation completes, before you assume the original
  plan still applies.
The tool returns a string. If empty/no-messages, it says so explicitly.
If non-empty, each message is anchored by source: [broadcast] (a sweeping
instruction sent to all agents), [re <tag>] (a reply addressed to one of
your specific threads — a question or an earlier notify of yours), or
[late-reply] (an answer that arrived after a question closed). Treat these
as new instructions you should act on. Reading clears the queue, so
messages are delivered exactly once.

REPLIES ARE OFTEN TERSE. The user answers from a phone and frequently
replies in shorthand. Interpret common shorthands fully:
- "stop" (or "halt", "wait") = stop work on this thread and await further
  instructions; do not proceed on your own.
- "go", "bj", "ok", "yes" = proceed; use your best judgment and run to
  completion without further check-ins unless something material changes.
A reply may also be a longer dictated message; read it as natural language.

DO NOT use `notify`, `ask`, or `check_messages` for:
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


_QUESTION_DESCRIPTION = (
    "The question you want answered. Short, information-dense, phrased as "
    "a question the user can answer in one or two sentences (often a "
    "dictated voice reply on mobile). Example: \"Rebase or merge? Conflict "
    "is in src/auth.py and either is workable.\" Include enough context that "
    "the user doesn't need to switch back to the laptop to answer. Prefer "
    "URLs over local file paths when referring to material the user might "
    "need to look at — the user reads on mobile and can't reach the "
    "workstation filesystem."
)

_GIVE_UP_DESCRIPTION = (
    "Seconds to wait before producing a timeout directive instead of an "
    "answer. Bounded 1..86400 (24h). Pick proportional to how long the user "
    "might plausibly be away for this question's importance. Default 1800 "
    "(30 min) is a reasonable middle ground."
)

_ON_TIMEOUT_DESCRIPTION = (
    "What to do if no answer arrives within give_up_after_seconds. "
    "'use_best_judgment' lets you proceed with a default action; 'abort' "
    "tells you to stop and surface task state. Pick by stakes: moderate "
    "questions → use_best_judgment; destructive/irreversible questions → "
    "abort."
)


@mcp.tool()
async def ask(
    question: Annotated[str, Field(description=_QUESTION_DESCRIPTION)],
    give_up_after_seconds: Annotated[
        int, Field(description=_GIVE_UP_DESCRIPTION, ge=1, le=86400)
    ] = 1800,
    on_timeout: Annotated[
        Literal["use_best_judgment", "abort"],
        Field(description=_ON_TIMEOUT_DESCRIPTION),
    ] = "use_best_judgment",
) -> str:
    """Ask confer for an answer on your behalf.

    Returns a natural-language string. Usually the user's reply; on timeout
    a directive telling you what to do next; on confer-side failure a
    directive saying you've lost the channel. Always a string — never raises
    across the MCP boundary. See the server's instructions block for
    when-to-use guidance.
    """
    if _client is None:
        raise RuntimeError(
            "DaemonClient not initialized; server lifespan did not start"
        )
    return await _client.ask(question, give_up_after_seconds, on_timeout)


@mcp.tool()
async def check_messages() -> str:
    """Check confer for messages the user has sent you while you were busy.

    Returns a natural-language string. Empty queue returns a brief directive
    ("No new messages from the user."). Non-empty returns a numbered summary
    with each message tagged by source. Reading clears the queue — messages
    are delivered exactly once per agent. See the server's instructions
    block for when-to-use guidance.
    """
    if _client is None:
        raise RuntimeError(
            "DaemonClient not initialized; server lifespan did not start"
        )
    return await _client.check_messages()


def main() -> None:
    mcp.run()
