import asyncio
import hashlib
import logging
import os
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from confer.daemon.transport import FAILURE_PREFIX, DiscordTransport
from confer.protocol import (
    Bye,
    Error,
    Hello,
    Notify,
    NotifyResult,
    HelloOk,
    Message,
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


class Daemon:
    def __init__(self, transport: DiscordTransport) -> None:
        self._transport = transport
        self._clients: dict[str, _Client] = {}
        self._server: asyncio.AbstractServer | None = None

    async def serve(self, socket_path: Path, pid_file: Path) -> None:
        if await self._another_instance_running(socket_path):
            log.info("another daemon already running at %s; exiting", socket_path)
            return

        with suppress(FileNotFoundError):
            socket_path.unlink()

        socket_path.parent.mkdir(parents=True, exist_ok=True)
        pid_file.parent.mkdir(parents=True, exist_ok=True)

        await self._transport.connect()
        await self._transport.wait_for_ready()

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(socket_path)
        )
        socket_path.chmod(0o600)
        pid_file.write_text(str(os.getpid()))
        log.info("daemon listening on %s (pid %s)", socket_path, os.getpid())

        try:
            await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            await self._transport.close()
            with suppress(FileNotFoundError):
                socket_path.unlink()
            with suppress(FileNotFoundError):
                pid_file.unlink()

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
            label = self._assign_label(msg.label_preferred, msg.pid)
            self._clients[label] = _Client(label=label, writer=writer)
            await self._send(
                writer, HelloOk(request_id=msg.request_id, label_assigned=label)
            )
            return label
        if isinstance(msg, Notify):
            info = await self._transport.notify(msg.message)
            status = "failed" if info.startswith(FAILURE_PREFIX) else "ok"
            await self._send(
                writer,
                NotifyResult(request_id=msg.request_id, status=status, info=info),
            )
            return None
        if isinstance(msg, Bye):
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
