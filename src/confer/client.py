import asyncio
import logging
import os
import shutil
import subprocess
import uuid
from contextlib import suppress
from pathlib import Path
from subprocess import DEVNULL
from typing import Literal

from confer.paths import log_file, socket_path
from confer.protocol import (
    AskBegin,
    AskCancel,
    AskReply,
    AskTimeout,
    Bye,
    CheckMessages,
    CheckMessagesResult,
    Hello,
    HelloErr,
    HelloOk,
    Message,
    Notify,
    NotifyResult,
    decode,
    encode,
)

log = logging.getLogger(__name__)

_DAEMON_SPAWN_TIMEOUT = 10.0
_DAEMON_POLL_INTERVAL = 0.1
_NOTIFY_FAILURE_PREFIX = "<NOTIFY_FAILED: "

# Natural-language directives returned from `ask()` per Sentinel Returns
# Not Exceptions (nx2pj4wq) under Natural Language Outcomes (xj4nqv7m).
_TIMEOUT_DIRECTIVES: dict[str, str] = {
    "use_best_judgment": (
        "No answer was received within the requested window. Follow your "
        "existing instructions or your best judgment about how to proceed."
    ),
    "abort": (
        "No answer was received within the requested window. Stop work on this "
        "task and leave its state somewhere the user can pick up later "
        "(e.g., a WIP commit, a status file)."
    ),
}
_DAEMON_DISCONNECT_DIRECTIVE = (
    "Lost connection to confer; question not answered. Retry or proceed "
    "without the user's input."
)
_CHECK_MESSAGES_DISCONNECT_DIRECTIVE = (
    "Lost connection to confer; could not check for messages."
)


def _pending_note(n: int) -> str:
    """Bracketed confer meta-note appended to an ask result when other
    messages are waiting (pb7nqm4x). Distinct from the user's own words."""
    plural = "s" if n != 1 else ""
    return f"[confer: {n} other message{plural} waiting — call check_messages]"


class DaemonClient:
    def __init__(self, label_preferred: str | None = None) -> None:
        self._label_preferred = (
            label_preferred if label_preferred is not None else auto_label()
        )
        self._label_assigned: str | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._pending_ask_request_ids: set[str] = set()
        self._reader_task: asyncio.Task | None = None

    @property
    def label(self) -> str:
        if self._label_assigned is None:
            raise RuntimeError("DaemonClient.label accessed before connect()")
        return self._label_assigned

    async def connect(self) -> None:
        sock = socket_path()
        self._reader, self._writer = await self._connect_or_spawn(sock)
        self._reader_task = asyncio.create_task(self._read_loop())
        request_id = str(uuid.uuid4())
        hello = Hello(
            request_id=request_id,
            label_preferred=self._label_preferred,
            pid=os.getpid(),
        )
        response = await self._send_and_wait(hello)
        if isinstance(response, HelloErr):
            raise RuntimeError(f"daemon rejected hello: {response.reason}")
        if not isinstance(response, HelloOk):
            raise RuntimeError(
                f"unexpected response to HELLO: {type(response).__name__}"
            )
        self._label_assigned = response.label_assigned

    async def notify(self, message: str) -> str:
        request_id = str(uuid.uuid4())
        msg = Notify(request_id=request_id, message=message)
        response = await self._send_and_wait(msg)
        if not isinstance(response, NotifyResult):
            return f"{_NOTIFY_FAILURE_PREFIX}unexpected daemon response>"
        return response.info

    async def ask(
        self,
        question: str,
        give_up_after_seconds: int,
        on_timeout: Literal["use_best_judgment", "abort"],
    ) -> str:
        """Send an ASK_BEGIN and await either AskReply or AskTimeout from
        the daemon. Returns a natural-language directive per Natural Language
        Outcomes (xj4nqv7m): the user's reply text on success, a timeout
        directive on timeout, or a disconnect directive if the daemon goes
        away. CancelledError (typically from agent-side ESC) sends ASK_CANCEL
        to the daemon before propagating up.
        """
        request_id = str(uuid.uuid4())
        msg = AskBegin(
            request_id=request_id,
            question=question,
            give_up_after_seconds=give_up_after_seconds,
            on_timeout=on_timeout,
        )
        self._pending_ask_request_ids.add(request_id)
        try:
            try:
                response = await self._send_and_wait(msg)
            except asyncio.CancelledError:
                await self._send_ask_cancel(request_id)
                raise
            except RuntimeError:
                return _DAEMON_DISCONNECT_DIRECTIVE
        finally:
            self._pending_ask_request_ids.discard(request_id)
            self._pending.pop(request_id, None)
        if isinstance(response, AskReply):
            # The reply is the user's verbatim words; if other messages are
            # waiting, append the piggyback hint as a clearly bracketed
            # confer meta-note so it can't be mistaken for the user's text
            # (Pending-Message Piggyback Hint, pb7nqm4x).
            if response.pending_count > 0:
                return f"{response.content}\n\n{_pending_note(response.pending_count)}"
            return response.content
        if isinstance(response, AskTimeout):
            directive = _TIMEOUT_DIRECTIVES.get(
                response.outcome, _DAEMON_DISCONNECT_DIRECTIVE
            )
            if response.pending_count > 0:
                return f"{directive} {_pending_note(response.pending_count)}"
            return directive
        return _DAEMON_DISCONNECT_DIRECTIVE

    async def check_messages(self) -> str:
        """Drain the daemon-side queue for this client's label. Returns a
        natural-language string per Check Messages Inbox Model (cm7vnpqx):
        either a formatted multi-line summary or a directive saying no
        messages are present."""
        request_id = str(uuid.uuid4())
        msg = CheckMessages(request_id=request_id)
        try:
            response = await self._send_and_wait(msg)
        except RuntimeError:
            return _CHECK_MESSAGES_DISCONNECT_DIRECTIVE
        if isinstance(response, CheckMessagesResult):
            return response.formatted
        return _CHECK_MESSAGES_DISCONNECT_DIRECTIVE

    async def _send_ask_cancel(self, request_id: str) -> None:
        """Fire-and-forget ASK_CANCEL. Per ASK_CANCEL Protocol (3mq7pvxn)
        the daemon does not respond; do not register a pending future."""
        if self._writer is None:
            return
        with suppress(Exception):
            self._writer.write(encode(AskCancel(request_id=request_id)))
            await self._writer.drain()

    async def close(self) -> None:
        if self._writer is None:
            return
        # Per ASK_CANCEL Protocol (3mq7pvxn) graceful-shutdown path: emit
        # ASK_CANCEL for every in-flight ask so the user sees "Question
        # withdrawn" rather than "Lost contact" DMs.
        for request_id in list(self._pending_ask_request_ids):
            with suppress(Exception):
                self._writer.write(encode(AskCancel(request_id=request_id)))
        with suppress(Exception):
            await self._writer.drain()
        try:
            self._writer.write(encode(Bye()))
            await self._writer.drain()
        except Exception:
            pass
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except Exception:
            pass
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass

    async def _connect_or_spawn(
        self, sock: Path
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        try:
            return await asyncio.open_unix_connection(str(sock))
        except OSError:
            pass
        _spawn_daemon()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + _DAEMON_SPAWN_TIMEOUT
        while loop.time() < deadline:
            await asyncio.sleep(_DAEMON_POLL_INTERVAL)
            try:
                return await asyncio.open_unix_connection(str(sock))
            except OSError:
                continue
        raise RuntimeError(
            f"daemon did not start within {_DAEMON_SPAWN_TIMEOUT}s"
        )

    async def _read_loop(self) -> None:
        assert self._reader is not None
        while True:
            line = await self._reader.readline()
            if not line:
                self._fail_pending("daemon closed connection")
                return
            try:
                msg = decode(line)
            except ValueError:
                continue
            request_id = getattr(msg, "request_id", None)
            if request_id is None:
                continue
            fut = self._pending.pop(request_id, None)
            if fut is not None and not fut.done():
                fut.set_result(msg)

    def _fail_pending(self, reason: str) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError(reason))
        self._pending.clear()

    async def _send_and_wait(self, msg: Message) -> Message:
        assert self._writer is not None
        request_id = getattr(msg, "request_id")
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut
        self._writer.write(encode(msg))
        await self._writer.drain()
        return await fut


def auto_label() -> str:
    repo, branch = _detect_repo_and_branch()
    return f"{repo}/{branch}"


def _detect_repo_and_branch() -> tuple[str, str]:
    """Combined git probe: one subprocess for both toplevel and branch.
    Falls back to (cwd basename, 'detached') when not in a git repo, when
    git is not installed, or on detached HEAD."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd().name, "detached"
    lines = result.stdout.strip().splitlines()
    if len(lines) < 2:
        return Path.cwd().name, "detached"
    repo = Path(lines[0]).name
    branch = lines[1] if lines[1] and lines[1] != "HEAD" else "detached"
    return repo, branch


def _spawn_daemon() -> None:
    log_path = log_file()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = shutil.which("confer-daemon")
    log.info(
        "auto-spawning confer-daemon (PATH-resolved to: %s)",
        resolved if resolved is not None else "<not found on PATH>",
    )
    log_fh = open(log_path, "a")
    try:
        subprocess.Popen(
            ["confer-daemon"],
            start_new_session=True,
            stdout=log_fh,
            stderr=log_fh,
            stdin=DEVNULL,
            close_fds=True,
        )
    finally:
        log_fh.close()
