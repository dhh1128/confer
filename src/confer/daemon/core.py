import asyncio
import errno
import hashlib
import logging
import os
import signal
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from confer.daemon.routing import (
    Ambiguous,
    Bounce,
    Deliver,
    PendingAsk as RoutingPendingAsk,
    route_user_message,
)
from confer.daemon.transport import FAILURE_PREFIX, DiscordTransport
from confer.protocol import (
    CURRENT_PROTOCOL_VERSION,
    AskBegin,
    AskCancel,
    AskReply,
    AskTimeout,
    Bye,
    Error,
    Hello,
    HelloErr,
    HelloOk,
    Message,
    Notify,
    NotifyResult,
    Status,
    StatusResult,
    decode,
    encode,
)

log = logging.getLogger(__name__)

_SKIP_REPING_NEAR_DEADLINE = 60.0  # seconds
_QUEUE_PER_LABEL_LIMIT = 100


def _closing_dm_text(reason: str, question: str) -> str:
    """Render the closing DM body for an ask resolving without a user reply.

    Reasons:
      - "use_best_judgment" / "abort": timeout dispositions
      - "withdrawn": ASK_CANCEL path
      - "lost_contact": orphan drop on MCP-server disconnect
    """
    templates = {
        "use_best_judgment": (
            "**Time's up — agent will use its best judgment on:** *{q}*"
        ),
        "abort": (
            "**Time's up — agent will stop and surface state for:** *{q}*"
        ),
        "withdrawn": "**Question withdrawn:** *{q}*",
        "lost_contact": "**Lost contact with the agent that asked:** *{q}*",
    }
    return templates[reason].format(q=question)


def _shortest_unique_suffix(labels: list[str]) -> dict[str, str]:
    """For each label, pick a short hint string suitable for the routing
    footer. Strategy: take the segment after the last '/' if it's unique
    across all labels; otherwise use the full label."""
    after_slash = {label: label.rsplit("/", 1)[-1] for label in labels}
    seen: dict[str, int] = {}
    for hint in after_slash.values():
        seen[hint] = seen.get(hint, 0) + 1
    return {
        label: hint if seen[hint] == 1 else label
        for label, hint in after_slash.items()
    }


def _compose_ask_footer(asks_newest_first: list["_PendingAsk"]) -> str:
    """Format the routing footer the bot appends to ask DMs.

    Empty string when 1 or fewer asks are pending — the body alone is enough,
    per Reply Routing Footer (xqp4nv7m)."""
    n = len(asks_newest_first)
    if n <= 1:
        return ""
    hints = _shortest_unique_suffix([a.label for a in asks_newest_first])
    label_parts = ", ".join(hints[a.label] for a in asks_newest_first)
    return (
        f"\n(reply: {label_parts}, 1-{n}, "
        f"or just answer if I'm the only one waiting)"
    )


@dataclass(frozen=True)
class QueuedMessage:
    timestamp: float
    content: str
    source: Literal["late_reply"]
    original_question: str | None


@dataclass
class _Client:
    label: str
    writer: asyncio.StreamWriter


@dataclass
class _PendingAsk:
    request_id: str
    label: str
    question: str
    on_timeout: Literal["use_best_judgment", "abort"]
    give_up_after_seconds: int
    started_at: float  # monotonic
    writer: asyncio.StreamWriter
    re_ping_task: asyncio.Task | None = None
    timeout_task: asyncio.Task | None = None


def _make_disambiguator(pid: int) -> str:
    payload = f"{pid}:{time.time_ns()}".encode()
    return hashlib.sha256(payload).hexdigest()[:4]


def _atomic_write_pid_file(pid_path: Path, pid: int) -> None:
    """Write pid_path atomically via tmpfile + rename, so a crash between
    socket-bind and PID-file-visible never leaves a working daemon with no
    PID file."""
    tmp = pid_path.with_suffix(pid_path.suffix + ".tmp")
    tmp.write_text(str(pid))
    tmp.replace(pid_path)


class Daemon:
    def __init__(
        self,
        transport: DiscordTransport,
        re_ping_every_seconds: int = 900,
    ) -> None:
        self._transport = transport
        self._re_ping_every_seconds = re_ping_every_seconds
        self._clients: dict[str, _Client] = {}
        self._pending_asks: dict[str, _PendingAsk] = {}
        self._queues: dict[str, deque[QueuedMessage]] = {}
        self._server: asyncio.AbstractServer | None = None
        self._start_time: float | None = None
        self._stop_event: asyncio.Event | None = None

    def stop(self) -> None:
        """Trigger graceful shutdown of a running serve() call."""
        if self._stop_event is not None:
            self._stop_event.set()

    async def serve(self, socket_path: Path, pid_file: Path) -> None:
        if await self._another_instance_running(socket_path):
            log.info("another daemon already running at %s; exiting", socket_path)
            return

        with suppress(FileNotFoundError):
            socket_path.unlink()

        for parent in {socket_path.parent, pid_file.parent}:
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            # mkdir(mode=...) only applies to *newly created* dirs; chmod a
            # pre-existing parent so the fallback path is 0700 regardless.
            with suppress(OSError):
                parent.chmod(0o700)

        await self._transport.connect()
        await self._transport.wait_for_ready()

        self._start_time = time.time()
        # Apply a restrictive umask around the bind so the socket file is
        # created with 0600 directly, closing the TOCTOU window between
        # bind and the subsequent chmod.
        old_umask = os.umask(0o077)
        try:
            try:
                self._server = await asyncio.start_unix_server(
                    self._handle_client, path=str(socket_path)
                )
            except OSError as e:
                if e.errno == errno.EADDRINUSE:
                    log.info("lost a race to bind %s; exiting", socket_path)
                    await self._transport.close()
                    return
                raise
        finally:
            os.umask(old_umask)
        socket_path.chmod(0o600)
        _atomic_write_pid_file(pid_file, os.getpid())
        log.info("daemon listening on %s (pid %s)", socket_path, os.getpid())

        self._stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, self._stop_event.set)

        try:
            await self._stop_event.wait()
        finally:
            for sig in (signal.SIGTERM, signal.SIGINT):
                with suppress(NotImplementedError, ValueError):
                    loop.remove_signal_handler(sig)
            self._server.close()
            with suppress(Exception):
                await self._server.wait_closed()
            await self._transport.close()
            with suppress(FileNotFoundError):
                socket_path.unlink()
            with suppress(FileNotFoundError):
                pid_file.unlink()
            self._stop_event = None

    async def _another_instance_running(self, socket_path: Path) -> bool:
        if not socket_path.exists():
            return False
        try:
            _, writer = await asyncio.open_unix_connection(str(socket_path))
        except OSError:
            return False
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()
        return True

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        client_label: str | None = None
        try:
            async for raw in reader:
                if not raw.strip():
                    continue
                try:
                    msg = decode(raw)
                except ValueError as e:
                    await self._send(
                        writer, Error(code="bad_message", message=str(e))
                    )
                    continue
                done = await self._dispatch(msg, writer, client_label)
                if isinstance(msg, Hello) and isinstance(done, str):
                    client_label = done
                if isinstance(msg, Bye):
                    break
        except (ConnectionResetError, BrokenPipeError):
            # Client dropped abruptly. Clean up normally; nothing else to do.
            pass
        finally:
            if client_label is not None:
                self._clients.pop(client_label, None)
                await self._drop_asks_for_writer(writer, client_label)
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    async def _dispatch(
        self,
        msg: Message,
        writer: asyncio.StreamWriter,
        client_label: str | None,
    ) -> str | None:
        if isinstance(msg, Hello):
            if msg.protocol_version != CURRENT_PROTOCOL_VERSION:
                await self._send(
                    writer,
                    HelloErr(
                        request_id=msg.request_id,
                        reason=(
                            f"protocol_version {msg.protocol_version} not "
                            f"supported (daemon speaks "
                            f"{CURRENT_PROTOCOL_VERSION}); restart the daemon "
                            f"after upgrading"
                        ),
                    ),
                )
                return None
            label = self._assign_label(msg.label_preferred, msg.pid)
            self._clients[label] = _Client(label=label, writer=writer)
            await self._send(
                writer, HelloOk(request_id=msg.request_id, label_assigned=label)
            )
            return label
        if isinstance(msg, Status):
            uptime = (
                0.0 if self._start_time is None else time.time() - self._start_time
            )
            gateway = "ready" if self._transport.is_ready() else "not_ready"
            await self._send(
                writer,
                StatusResult(
                    request_id=msg.request_id,
                    uptime_seconds=uptime,
                    gateway_state=gateway,
                    clients=sorted(self._clients.keys()),
                ),
            )
            return None
        if isinstance(msg, Bye):
            return None
        if client_label is None:
            await self._send(
                writer,
                Error(
                    code="hello_required",
                    message=(
                        f"HELLO must be sent before {type(msg).__name__}"
                    ),
                    request_id=getattr(msg, "request_id", None),
                ),
            )
            return None
        if isinstance(msg, Notify):
            info = await self._transport.notify(msg.message)
            status = "failed" if info.startswith(FAILURE_PREFIX) else "ok"
            await self._send(
                writer,
                NotifyResult(request_id=msg.request_id, status=status, info=info),
            )
            return None
        if isinstance(msg, AskBegin):
            await self._handle_ask_begin(msg, writer, client_label)
            return None
        if isinstance(msg, AskCancel):
            await self._handle_ask_cancel(msg.request_id)
            return None
        await self._send(
            writer,
            Error(
                code="unexpected_message",
                message=f"unexpected {type(msg).__name__} from client",
                request_id=getattr(msg, "request_id", None),
            ),
        )
        return None

    async def _handle_ask_begin(
        self, msg: AskBegin, writer: asyncio.StreamWriter, client_label: str
    ) -> None:
        pending = _PendingAsk(
            request_id=msg.request_id,
            label=client_label,
            question=msg.question,
            on_timeout=msg.on_timeout,
            give_up_after_seconds=msg.give_up_after_seconds,
            started_at=time.monotonic(),
            writer=writer,
        )
        self._pending_asks[msg.request_id] = pending
        # Send the question DM with footer reflecting the current pending set.
        await self._send_question_dm(pending)
        # Start the timeout and re-ping tasks. The timeout task fires first
        # if the give_up_after_seconds deadline elapses without a reply; the
        # re-ping task periodically reminds the user.
        pending.timeout_task = asyncio.create_task(self._timeout_loop(pending))
        pending.re_ping_task = asyncio.create_task(self._re_ping_loop(pending))

    async def _handle_ask_cancel(self, request_id: str) -> None:
        pending = self._pending_asks.pop(request_id, None)
        if pending is None:
            return  # idempotent — already resolved
        await self._cancel_ask_tasks(pending)
        await self._send_dm_best_effort(
            _closing_dm_text("withdrawn", pending.question)
        )

    async def _dispatch_user_message(self, content: str) -> None:
        """Called from DiscordTransport's on_message handler whenever a DM
        arrives from the configured user. Routes via route_user_message and
        acts on the decision."""
        snapshot = [self._to_routing_ask(p) for p in self._pending_asks.values()]
        decision = route_user_message(content, snapshot)
        if isinstance(decision, Deliver):
            await self._deliver_reply(decision.label, decision.content)
        elif isinstance(decision, Bounce):
            await self._send_dm_best_effort(decision.text)
        else:
            # RouteDecision union is closed (Deliver | Bounce | Ambiguous),
            # so this branch always handles Ambiguous.
            await self._send_dm_best_effort(
                self._format_ambiguous_dm(decision.pending_asks)
            )

    async def _deliver_reply(self, label: str, content: str) -> None:
        # Find the (one) pending ask matching the label; route there.
        target_request_id: str | None = None
        for req_id, p in self._pending_asks.items():
            if p.label == label:
                target_request_id = req_id
                break
        if target_request_id is None:
            # Race: ask was resolved between routing snapshot and now. Treat
            # as late_reply and enqueue.
            self._enqueue_late_reply(label, content, original_question=None)
            return
        pending = self._pending_asks.pop(target_request_id)
        await self._cancel_ask_tasks(pending)
        with suppress(Exception):
            await self._send(
                pending.writer,
                AskReply(request_id=pending.request_id, content=content),
            )

    def _enqueue_late_reply(
        self, label: str, content: str, original_question: str | None
    ) -> None:
        queue = self._queues.setdefault(label, deque(maxlen=_QUEUE_PER_LABEL_LIMIT))
        was_full = len(queue) == _QUEUE_PER_LABEL_LIMIT
        queue.append(
            QueuedMessage(
                timestamp=time.time(),
                content=content,
                source="late_reply",
                original_question=original_question,
            )
        )
        if was_full:
            log.warning(
                "check_messages queue full for label=%s; oldest entry evicted",
                label,
            )

    def _format_ambiguous_dm(
        self, asks: tuple[RoutingPendingAsk, ...]
    ) -> str:
        lines = ["**Multiple asks waiting** — reply with the index or label prefix:"]
        for i, ask in enumerate(asks, start=1):
            lines.append(f"  [{i}] *{ask.label}*: {ask.question}")
        return "\n".join(lines)

    async def _send_question_dm(self, pending: _PendingAsk) -> None:
        asks = self._pending_asks_newest_first()
        footer = _compose_ask_footer(asks)
        body = f"**Question** *({pending.label})*: {pending.question}{footer}"
        await self._send_dm_best_effort(body)

    async def _re_ping_loop(self, pending: _PendingAsk) -> None:
        """Periodically remind the user that an ask is still open.

        Skips any re-ping that would land within _SKIP_REPING_NEAR_DEADLINE
        seconds of the give_up_after_seconds deadline (avoids "still waiting"
        followed seconds later by a timeout DM). Send failures are non-fatal:
        the ask still resolves on reply or timeout per its own contract."""
        deadline_at = pending.started_at + pending.give_up_after_seconds
        while True:
            try:
                await asyncio.sleep(self._re_ping_every_seconds)
            except asyncio.CancelledError:
                return
            remaining = deadline_at - time.monotonic()
            if remaining < _SKIP_REPING_NEAR_DEADLINE:
                return
            asks = self._pending_asks_newest_first()
            footer = _compose_ask_footer(asks)
            body = f"Still waiting on your answer to: *{pending.question}*{footer}"
            try:
                await self._transport.notify(body)
            except Exception as exc:
                log.warning(
                    "re-ping send failed for ask=%s: %r", pending.request_id, exc
                )

    async def _timeout_loop(self, pending: _PendingAsk) -> None:
        try:
            await asyncio.sleep(pending.give_up_after_seconds)
        except asyncio.CancelledError:
            return
        # Time's up. If the ask was already resolved (race), nothing to do.
        if self._pending_asks.pop(pending.request_id, None) is None:
            return
        with suppress(asyncio.CancelledError):
            if pending.re_ping_task is not None:
                pending.re_ping_task.cancel()
        with suppress(Exception):
            await self._send(
                pending.writer,
                AskTimeout(
                    request_id=pending.request_id, outcome=pending.on_timeout
                ),
            )
        await self._send_dm_best_effort(
            _closing_dm_text(pending.on_timeout, pending.question)
        )

    async def _cancel_ask_tasks(self, pending: _PendingAsk) -> None:
        for task in (pending.re_ping_task, pending.timeout_task):
            if task is None or task.done():
                continue
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task

    async def _drop_asks_for_writer(
        self, writer: asyncio.StreamWriter, client_label: str
    ) -> None:
        """When an MCP server disconnects, drop its pending asks immediately
        and DM the user once per dropped ask. No retention (per Orphan Ask
        Drop Policy, v4kn7mpq)."""
        orphans = [p for p in self._pending_asks.values() if p.writer is writer]
        for pending in orphans:
            self._pending_asks.pop(pending.request_id, None)
            await self._cancel_ask_tasks(pending)
            await self._send_dm_best_effort(
                _closing_dm_text("lost_contact", pending.question)
            )

    def _pending_asks_newest_first(self) -> list[_PendingAsk]:
        return sorted(
            self._pending_asks.values(),
            key=lambda p: p.started_at,
            reverse=True,
        )

    def _to_routing_ask(self, pending: _PendingAsk) -> RoutingPendingAsk:
        return RoutingPendingAsk(
            request_id=pending.request_id,
            label=pending.label,
            question=pending.question,
            started_at=pending.started_at,
        )

    async def _send_dm_best_effort(self, body: str) -> None:
        """Send a DM whose return value we don't surface to any agent (closing
        notifications, bounces, re-pings, etc.). Failures are logged."""
        try:
            result = await self._transport.notify(body)
        except Exception as exc:
            log.warning("daemon DM send raised: %r", exc)
            return
        if result.startswith(FAILURE_PREFIX):
            log.warning("daemon DM send failed: %s", result)

    def _assign_label(self, preferred: str, pid: int) -> str:
        if preferred not in self._clients:
            return preferred
        for _ in range(100):
            candidate = f"{preferred}#{_make_disambiguator(pid)}"
            if candidate not in self._clients:
                return candidate
        raise RuntimeError(
            f"could not assign a unique label after 100 attempts for {preferred!r}"
        )

    async def _send(self, writer: asyncio.StreamWriter, msg: Message) -> None:
        writer.write(encode(msg))
        await writer.drain()
