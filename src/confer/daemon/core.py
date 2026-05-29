import asyncio
import errno
import hashlib
import logging
import os
import secrets
import signal
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from confer.daemon.routing import (
    CONCIERGE_STUB,
    Ambiguous,
    AskThread,
    Bounce,
    Broadcast,
    Concierge,
    DeliverAsk,
    EnqueueNotifyReply,
    NotifyThread,
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
    CheckMessages,
    CheckMessagesResult,
    Error,
    Hello,
    HelloErr,
    HelloOk,
    Inject,
    InjectResult,
    ListAsks,
    ListAsksResult,
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
_NOTIFY_TAGS_PER_LABEL = 20  # cap on live replyable notify-threads per agent
_TAG_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"  # base32, matches node ids
_TAG_LEN = 4


def _make_thread_tag() -> str:
    """Random 4-char base32 thread tag (Thread Tag Model, tgq4n7px)."""
    return "".join(secrets.choice(_TAG_ALPHABET) for _ in range(_TAG_LEN))


def _closing_dm_text(reason: str, tag: str) -> str:
    """Render the closing DM body for an ask resolving without a Discord-typed
    reply, anchored with the thread tag (Threaded DM Conventions, dm5kqv7n).

    Reasons: "use_best_judgment" / "abort" (timeout dispositions), "withdrawn"
    (ASK_CANCEL), "lost_contact" (orphan drop on disconnect), "cli_answered"
    (resolved via the confer CLI — F-A fix, pkn7mvq4)."""
    templates = {
        "use_best_judgment": (
            "Re: {tag} — time's up; agent will use its best judgment."
        ),
        "abort": "Re: {tag} — time's up; agent will stop and surface task state.",
        "withdrawn": "Re: {tag} — question withdrawn.",
        "lost_contact": "Re: {tag} — lost contact with the agent that asked.",
        "cli_answered": "Re: {tag} — answered from the laptop.",
    }
    return templates[reason].format(tag=tag)


@dataclass(frozen=True)
class QueuedMessage:
    timestamp: float
    content: str
    source: Literal["late_reply", "notify_reply", "broadcast"]
    tag: str | None  # thread tag this entry concerns (None for broadcast)


def _format_queue_for_check_messages(queue) -> str:
    """Render a deque of QueuedMessage as natural-language prose for the agent
    (Check Messages Inbox Model, cm7vnpqx). Empty queues return a short
    directive. Each entry is anchored so the agent can correlate it with the
    thread it concerns."""
    if not queue:
        return "No new messages from the user."
    count = len(queue)
    lines = [f"{count} message{'s' if count != 1 else ''} from the user:", ""]
    for entry in queue:
        if entry.source == "broadcast":
            lines.append(f"[broadcast] {entry.content}")
        elif entry.source == "notify_reply":
            lines.append(f"[re {entry.tag}] {entry.content}")
        else:  # late_reply
            anchor = f"re {entry.tag}" if entry.tag else "late-reply"
            lines.append(f"[{anchor}] {entry.content}")
    return "\n".join(lines)


def _format_pending_asks_for_list(asks) -> str:
    """Render pending asks (newest-first) for the CLI `confer list` output,
    leading with each ask's tag so the user can `confer answer "re <tag> ..."`."""
    if not asks:
        return "No pending asks."
    lines = [f"{len(asks)} pending ask(s) (newest first):", ""]
    for ask in asks:
        lines.append(f"  [{ask.tag}] {ask.label}: {ask.question}")
    return "\n".join(lines)


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
    tag: str = ""
    re_ping_task: asyncio.Task | None = None
    timeout_task: asyncio.Task | None = None


@dataclass
class _NotifyThread:
    tag: str
    label: str
    created_at: float  # monotonic; oldest evicted first at the per-label cap


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
        self._notify_threads: dict[str, _NotifyThread] = {}
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
                self._drop_notify_threads_for_label(client_label)
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
        # CLI-side messages: HELLO-exempt per CLI Inject Tool (ci7n4pvm)
        # and the STATUS precedent in xn7pqv4m.
        if isinstance(msg, Inject):
            await self._handle_inject(msg.request_id, msg.content, writer)
            return None
        if isinstance(msg, ListAsks):
            await self._handle_list_asks(msg.request_id, writer)
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
            await self._handle_notify(msg, writer, client_label)
            return None
        if isinstance(msg, AskBegin):
            await self._handle_ask_begin(msg, writer, client_label)
            return None
        if isinstance(msg, AskCancel):
            await self._handle_ask_cancel(msg.request_id)
            return None
        if isinstance(msg, CheckMessages):
            await self._handle_check_messages(msg.request_id, client_label, writer)
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

    async def _handle_notify(
        self, msg: Notify, writer: asyncio.StreamWriter, client_label: str
    ) -> None:
        """A notify is a tagged, replyable thread (Notify Replyable Threads,
        nr4kpq7v). Assign a tag, register the notify-thread so a later
        `re <tag>` can route back, and send the DM anchored with the tag."""
        tag = self._assign_thread_tag()
        self._register_notify_thread(tag, client_label)
        body = f"[{tag}] {client_label}: {msg.message}"
        info = await self._transport.notify(body)
        status = "failed" if info.startswith(FAILURE_PREFIX) else "ok"
        # Piggyback hint (pb7nqm4x): fold a pending-message count into the
        # notify status string, only on success (the status string is
        # confer-authored, so appending to it pollutes nothing).
        if status == "ok":
            info += self._pending_hint(client_label)
        await self._send(
            writer,
            NotifyResult(request_id=msg.request_id, status=status, info=info),
        )

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
            tag=self._assign_thread_tag(),
        )
        self._pending_asks[msg.request_id] = pending
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
        await self._send_dm_best_effort(_closing_dm_text("withdrawn", pending.tag))

    async def _dispatch_user_message(self, content: str) -> None:
        """Called from DiscordTransport's on_message handler whenever a DM
        arrives from the configured user. Routes the content and, for outcomes
        that produce user-facing text (bounce / ambiguous / concierge), replies
        on the Discord side so the user sees the explanation on the same
        channel they used to send."""
        outcome, detail, _ = await self._route_and_act(content)
        if outcome in ("bounced", "ambiguous", "concierge"):
            await self._send_dm_best_effort(detail)

    async def _route_and_act(self, content: str) -> tuple[str, str, object]:
        """Shared core for the Discord and CLI ingestion paths. Applies the
        tag-based routing ladder (rt7nqp4m), performs the queue/deliver side
        effects, and returns (outcome_tag, detail_text, decision). The caller
        decides whether to surface detail as a Discord DM or via its own
        channel."""
        asks = [self._to_routing_ask(p) for p in self._pending_asks.values()]
        notifies = [
            NotifyThread(tag=nt.tag, label=nt.label)
            for nt in self._notify_threads.values()
        ]
        connected_labels = list(self._clients.keys())
        tag_to_label = {a.tag: a.label for a in asks}
        decision = route_user_message(content, asks, notifies, connected_labels)

        if isinstance(decision, Concierge):
            return ("concierge", CONCIERGE_STUB, decision)
        if isinstance(decision, DeliverAsk):
            label = tag_to_label.get(decision.tag, "?")
            await self._deliver_reply_by_tag(decision.tag, decision.content, label)
            return ("delivered", f"Delivered to {label}.", decision)
        if isinstance(decision, EnqueueNotifyReply):
            self._enqueue_message(
                decision.label, decision.content,
                source="notify_reply", tag=decision.tag,
            )
            return ("queued_notify_reply", f"Queued for {decision.label}.", decision)
        if isinstance(decision, Broadcast):
            for label in connected_labels:
                self._enqueue_message(
                    label, decision.content, source="broadcast", tag=None
                )
            return (
                "broadcast",
                f"Broadcast to {len(connected_labels)} connected agent(s).",
                decision,
            )
        if isinstance(decision, Bounce):
            return ("bounced", decision.text, decision)
        # Ambiguous
        return ("ambiguous", self._format_ambiguous_dm(decision.asks), decision)

    async def _handle_inject(
        self, request_id: str, content: str, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a CLI-side INJECT message: route as if Discord-arrived, but
        return the outcome via INJECT_RESULT (the CLI user reads it in their
        terminal). When the inject resolves an ask, also send a Discord closing
        DM so the channel reflects that the question is answered (F-A fix,
        pkn7mvq4) — the Discord-side user did not type the answer."""
        outcome, detail, decision = await self._route_and_act(content)
        if isinstance(decision, DeliverAsk) and outcome == "delivered":
            await self._send_dm_best_effort(
                _closing_dm_text("cli_answered", decision.tag)
            )
        await self._send(
            writer,
            InjectResult(request_id=request_id, outcome=outcome, detail=detail),
        )

    async def _handle_list_asks(
        self, request_id: str, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a CLI-side LIST_ASKS message: a formatted view of pending
        asks (with tags) for the user to choose from when answering via CLI."""
        asks = self._pending_asks_newest_first()
        formatted = _format_pending_asks_for_list(asks)
        await self._send(
            writer,
            ListAsksResult(
                request_id=request_id, formatted=formatted, count=len(asks)
            ),
        )

    async def _handle_check_messages(
        self, request_id: str, client_label: str, writer: asyncio.StreamWriter
    ) -> None:
        """Drain the calling client's queue and return its contents formatted
        as a natural-language string. Per Check Messages Inbox Model
        (cm7vnpqx), reading clears the queue."""
        queue = self._queues.get(client_label)
        if queue is None or not queue:
            formatted = _format_queue_for_check_messages(())
            count = 0
        else:
            count = len(queue)
            formatted = _format_queue_for_check_messages(queue)
            queue.clear()
        await self._send(
            writer,
            CheckMessagesResult(
                request_id=request_id, formatted=formatted, count=count
            ),
        )

    async def _deliver_reply_by_tag(
        self, tag: str, content: str, label: str
    ) -> None:
        target_request_id: str | None = None
        for req_id, p in self._pending_asks.items():
            if p.tag == tag:
                target_request_id = req_id
                break
        if target_request_id is None:
            # Race: ask resolved between routing snapshot and now. Enqueue as a
            # late_reply under the snapshot label, tagged so the agent can tell
            # which thread it answered.
            self._enqueue_message(label, content, source="late_reply", tag=tag)
            return
        pending = self._pending_asks.pop(target_request_id)
        await self._cancel_ask_tasks(pending)
        with suppress(Exception):
            await self._send(
                pending.writer,
                AskReply(
                    request_id=pending.request_id,
                    content=content,
                    pending_count=self._pending_count(pending.label),
                ),
            )

    def _enqueue_message(
        self,
        label: str,
        content: str,
        source: Literal["late_reply", "notify_reply", "broadcast"],
        tag: str | None,
    ) -> None:
        queue = self._queues.setdefault(label, deque(maxlen=_QUEUE_PER_LABEL_LIMIT))
        was_full = len(queue) == _QUEUE_PER_LABEL_LIMIT
        queue.append(
            QueuedMessage(
                timestamp=time.time(), content=content, source=source, tag=tag
            )
        )
        if was_full:
            log.warning(
                "check_messages queue full for label=%s; oldest entry evicted",
                label,
            )

    def _format_ambiguous_dm(self, asks: tuple[AskThread, ...]) -> str:
        lines = ["Multiple questions are waiting — reply with a tag:"]
        for ask in asks:
            lines.append(f"  [{ask.tag}] {ask.label}: {ask.question}")
        return "\n".join(lines)

    async def _send_question_dm(self, pending: _PendingAsk) -> None:
        body = f"[{pending.tag}] {pending.label}: {pending.question}"
        await self._send_dm_best_effort(body)

    async def _re_ping_loop(self, pending: _PendingAsk) -> None:
        """Periodically remind the user that an ask is still open, anchored with
        the thread tag. Skips any re-ping that would land within
        _SKIP_REPING_NEAR_DEADLINE seconds of the deadline. Send failures are
        non-fatal: the ask still resolves on reply or timeout."""
        deadline_at = pending.started_at + pending.give_up_after_seconds
        while True:
            try:
                await asyncio.sleep(self._re_ping_every_seconds)
            except asyncio.CancelledError:
                return
            remaining = deadline_at - time.monotonic()
            if remaining < _SKIP_REPING_NEAR_DEADLINE:
                return
            body = (
                f"Re: {pending.tag} — still waiting on your answer: "
                f"{pending.question}"
            )
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
                    request_id=pending.request_id,
                    outcome=pending.on_timeout,
                    pending_count=self._pending_count(pending.label),
                ),
            )
        await self._send_dm_best_effort(
            _closing_dm_text(pending.on_timeout, pending.tag)
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
        and DM the user once per dropped ask. No retention (Orphan Ask Drop
        Policy, v4kn7mpq)."""
        orphans = [p for p in self._pending_asks.values() if p.writer is writer]
        for pending in orphans:
            self._pending_asks.pop(pending.request_id, None)
            await self._cancel_ask_tasks(pending)
            await self._send_dm_best_effort(
                _closing_dm_text("lost_contact", pending.tag)
            )

    def _drop_notify_threads_for_label(self, label: str) -> None:
        """A notify-thread is addressable only while its agent is connected
        (Notify Replyable Threads, nr4kpq7v); drop them on disconnect."""
        for tag in [
            t for t, nt in self._notify_threads.items() if nt.label == label
        ]:
            self._notify_threads.pop(tag, None)

    def _register_notify_thread(self, tag: str, label: str) -> None:
        same_label = [
            nt for nt in self._notify_threads.values() if nt.label == label
        ]
        if len(same_label) >= _NOTIFY_TAGS_PER_LABEL:
            oldest = min(same_label, key=lambda nt: nt.created_at)
            self._notify_threads.pop(oldest.tag, None)
        self._notify_threads[tag] = _NotifyThread(
            tag=tag, label=label, created_at=time.monotonic()
        )

    def _pending_count(self, label: str) -> int:
        """Number of messages waiting in a label's check_messages queue —
        the piggyback hint count (pb7nqm4x)."""
        queue = self._queues.get(label)
        return len(queue) if queue else 0

    def _pending_hint(self, label: str) -> str:
        """Suffix appended to confer-authored status strings when the agent
        has queued messages, nudging it to drain via check_messages."""
        n = self._pending_count(label)
        if n == 0:
            return ""
        return f" ({n} message{'s' if n != 1 else ''} waiting — call check_messages)"

    def _active_tags(self) -> set[str]:
        return {p.tag for p in self._pending_asks.values()} | set(
            self._notify_threads.keys()
        )

    def _assign_thread_tag(self) -> str:
        active = self._active_tags()
        for _ in range(100):
            tag = _make_thread_tag()
            if tag not in active:
                return tag
        raise RuntimeError("could not assign a unique thread tag after 100 tries")

    def _pending_asks_newest_first(self) -> list[_PendingAsk]:
        return sorted(
            self._pending_asks.values(),
            key=lambda p: p.started_at,
            reverse=True,
        )

    def _to_routing_ask(self, pending: _PendingAsk) -> AskThread:
        return AskThread(
            tag=pending.tag,
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
