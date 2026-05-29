"""User-facing CLI for confer per CLI Inject Tool (ci7n4pvm).

Two subcommands:
  confer list           — show pending asks the user can answer
  confer answer "text"  — apply Reply Routing Rules to text and report outcome

Connects to the daemon's Unix socket but does NOT send HELLO; the CLI is a
user-side injector, not an MCP-spawned client. Inject and ListAsks are
HELLO-exempt on the daemon side per the STATUS precedent (xn7pqv4m).
"""

import argparse
import asyncio
import sys
import uuid

from confer.paths import socket_path
from confer.protocol import (
    Inject,
    InjectResult,
    ListAsks,
    ListAsksResult,
    Message,
    decode,
    encode,
)


_NON_ZERO_EXIT_OUTCOMES = {"bounced", "ambiguous"}


async def _send_one(msg: Message) -> Message:
    """Open a one-shot connection, send msg, read one response line, close."""
    sock = socket_path()
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock))
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        print(
            f"confer: cannot reach daemon at {sock} ({exc.__class__.__name__}). "
            f"Is the daemon running? Try opening any MCP client to auto-spawn it.",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        try:
            writer.write(encode(msg))
            await writer.drain()
            line = await reader.readline()
        except (ConnectionResetError, BrokenPipeError):
            line = b""
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    if not line:
        print("confer: daemon closed connection before responding.", file=sys.stderr)
        sys.exit(2)
    return decode(line)


async def _cmd_list() -> int:
    response = await _send_one(ListAsks(request_id=str(uuid.uuid4())))
    if not isinstance(response, ListAsksResult):
        print(
            f"confer: unexpected response from daemon: {type(response).__name__}",
            file=sys.stderr,
        )
        return 2
    print(response.formatted)
    return 0


async def _cmd_answer(text: str) -> int:
    response = await _send_one(
        Inject(request_id=str(uuid.uuid4()), content=text)
    )
    if not isinstance(response, InjectResult):
        print(
            f"confer: unexpected response from daemon: {type(response).__name__}",
            file=sys.stderr,
        )
        return 2
    print(response.detail)
    return 1 if response.outcome in _NON_ZERO_EXIT_OUTCOMES else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="confer",
        description=(
            "User-side CLI for the confer daemon. Lets you answer pending "
            "agent asks from the laptop without going through Discord."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="List pending asks newest-first.")
    answer = sub.add_parser(
        "answer",
        help=(
            "Send text to the daemon, routed by the same rules as a Discord "
            "DM. Use 'N ...' for the Nth pending ask, 'label-prefix: ...' "
            "for a specific agent, or just text when only one ask is pending."
        ),
    )
    answer.add_argument("text", help="Reply or message body.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "list":
        return asyncio.run(_cmd_list())
    return asyncio.run(_cmd_answer(args.text))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
