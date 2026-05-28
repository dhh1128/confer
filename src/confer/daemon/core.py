import asyncio
import errno
import hashlib
import logging
import os
import signal
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from confer.daemon.transport import FAILURE_PREFIX, DiscordTransport
from confer.protocol import (
    CURRENT_PROTOCOL_VERSION,
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


@dataclass
class _Client:
    label: str
    writer: asyncio.StreamWriter


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
    def __init__(self, transport: DiscordTransport) -> None:
        self._transport = transport
        self._clients: dict[str, _Client] = {}
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
        await self._send(
            writer,
            Error(
                code="unexpected_message",
                message=f"unexpected {type(msg).__name__} from client",
                request_id=getattr(msg, "request_id", None),
            ),
        )
        return None

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
