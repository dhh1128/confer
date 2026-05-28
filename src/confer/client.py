import asyncio
import logging
import os
import subprocess
import uuid
from pathlib import Path
from subprocess import DEVNULL

from confer.paths import log_file, socket_path
from confer.protocol import (
    Bye,
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


class DaemonClient:
    def __init__(self, label_preferred: str | None = None) -> None:
        self._label_preferred = (
            label_preferred if label_preferred is not None else auto_label()
        )
        self._label_assigned: str | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[str, asyncio.Future] = {}
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

    async def close(self) -> None:
        if self._writer is None:
            return
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
