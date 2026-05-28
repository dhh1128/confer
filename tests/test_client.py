import asyncio
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from confer import client as client_mod
from confer.client import DaemonClient, auto_label
from confer.protocol import (
    Bye,
    Error,
    Hello,
    HelloErr,
    HelloOk,
    Notify,
    NotifyResult,
    decode,
    encode,
)


# ───── auto_label ──────────────────────────────────────────────────────────


def test_auto_label_uses_git_repo_and_branch():
    """One combined git call (rev-parse --show-toplevel --abbrev-ref HEAD)
    returns toplevel and branch on separate lines."""
    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="/home/daniel/code/myapp\nfeat-ask\n", stderr=""
        )

    with patch.object(client_mod.subprocess, "run", side_effect=fake_run) as mock_run:
        assert auto_label() == "myapp/feat-ask"
    assert mock_run.call_count == 1


def test_auto_label_falls_back_to_cwd_basename_when_not_a_git_repo(monkeypatch, tmp_path):
    cwd = tmp_path / "scratch"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    def fake_run(cmd, **_):
        raise subprocess.CalledProcessError(1, cmd)

    with patch.object(client_mod.subprocess, "run", side_effect=fake_run):
        assert auto_label() == "scratch/detached"


def test_auto_label_falls_back_when_git_not_installed(monkeypatch, tmp_path):
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    with patch.object(client_mod.subprocess, "run", side_effect=FileNotFoundError):
        assert auto_label() == "elsewhere/detached"


def test_auto_label_uses_detached_on_detached_head(monkeypatch, tmp_path):
    """Detached HEAD: git outputs 'HEAD' as the abbrev-ref."""
    cwd = tmp_path / "repo"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="/home/d/repo\nHEAD\n", stderr=""
        )

    with patch.object(client_mod.subprocess, "run", side_effect=fake_run):
        assert auto_label() == "repo/detached"


def test_auto_label_uses_detached_when_git_output_is_short(monkeypatch, tmp_path):
    """Defensive: git produced fewer lines than expected; treat as detached."""
    cwd = tmp_path / "tiny"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout="\n", stderr="")

    with patch.object(client_mod.subprocess, "run", side_effect=fake_run):
        assert auto_label() == "tiny/detached"


def test_spawn_daemon_logs_resolved_binary_path(tmp_path, monkeypatch, caplog):
    """The PATH-resolved confer-daemon path should be logged so a PATH-
    shadow attack is visible in retrospect via the log."""
    import logging
    log_path = tmp_path / "daemon.log"
    monkeypatch.setattr(client_mod, "log_file", lambda: log_path)
    monkeypatch.setattr(client_mod.shutil, "which", lambda _: "/usr/local/bin/confer-daemon")

    with caplog.at_level(logging.INFO, logger="confer.client"), patch.object(
        client_mod.subprocess, "Popen"
    ):
        client_mod._spawn_daemon()

    assert any(
        "PATH-resolved to: /usr/local/bin/confer-daemon" in record.getMessage()
        for record in caplog.records
    )


def test_spawn_daemon_logs_when_binary_not_on_path(tmp_path, monkeypatch, caplog):
    import logging
    log_path = tmp_path / "daemon.log"
    monkeypatch.setattr(client_mod, "log_file", lambda: log_path)
    monkeypatch.setattr(client_mod.shutil, "which", lambda _: None)

    with caplog.at_level(logging.INFO, logger="confer.client"), patch.object(
        client_mod.subprocess, "Popen"
    ):
        client_mod._spawn_daemon()

    assert any(
        "not found on PATH" in record.getMessage() for record in caplog.records
    )


def test_spawn_daemon_closes_log_fh_in_parent(tmp_path, monkeypatch):
    """The parent process should not retain an open file handle on the
    daemon log after spawn — leaks across many spawns."""
    log_path = tmp_path / "daemon.log"
    monkeypatch.setattr(client_mod, "log_file", lambda: log_path)

    opened = []
    real_open = open

    def tracking_open(p, *args, **kwargs):
        fh = real_open(p, *args, **kwargs)
        opened.append(fh)
        return fh

    monkeypatch.setattr("builtins.open", tracking_open)

    with patch.object(client_mod.subprocess, "Popen"):
        client_mod._spawn_daemon()

    # The file handle opened for the daemon log should now be closed
    daemon_log_handles = [fh for fh in opened if str(getattr(fh, "name", "")) == str(log_path)]
    assert daemon_log_handles, "expected at least one open on the daemon log"
    assert all(fh.closed for fh in daemon_log_handles)


# ───── DaemonClient end-to-end against a fake daemon ───────────────────────


@asynccontextmanager
async def _fake_daemon(handler, sock_path: Path):
    server = await asyncio.start_unix_server(handler, path=str(sock_path))
    try:
        yield server
    finally:
        server.close()
        await server.wait_closed()


async def test_connect_sends_hello_and_stores_assigned_label(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        line = await reader.readline()
        msg = decode(line)
        assert isinstance(msg, Hello)
        writer.write(encode(HelloOk(request_id=msg.request_id, label_assigned="confer/main#a3f1")))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        c = DaemonClient(label_preferred="confer/main")
        await c.connect()
        assert c.label == "confer/main#a3f1"
        await c.close()


async def test_connect_raises_on_hello_err(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        line = await reader.readline()
        msg = decode(line)
        writer.write(encode(HelloErr(request_id=msg.request_id, reason="config bad")))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        c = DaemonClient(label_preferred="x")
        with pytest.raises(RuntimeError, match="config bad"):
            await c.connect()
        await c.close()


async def test_connect_raises_on_unexpected_hello_response(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        line = await reader.readline()
        msg = decode(line)
        writer.write(encode(NotifyResult(request_id=msg.request_id, status="ok", info="x")))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        c = DaemonClient(label_preferred="x")
        with pytest.raises(RuntimeError, match="unexpected response"):
            await c.connect()
        await c.close()


async def test_notify_round_trips_through_daemon(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        hello = decode(await reader.readline())
        writer.write(encode(HelloOk(request_id=hello.request_id, label_assigned="x")))
        await writer.drain()
        notify = decode(await reader.readline())
        assert isinstance(notify, Notify)
        writer.write(encode(NotifyResult(
            request_id=notify.request_id, status="ok", info="sent at NOW"
        )))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        c = DaemonClient(label_preferred="x")
        await c.connect()
        result = await c.notify("hi")
        assert result == "sent at NOW"
        await c.close()


async def test_notify_returns_failure_sentinel_on_unexpected_response(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        hello = decode(await reader.readline())
        writer.write(encode(HelloOk(request_id=hello.request_id, label_assigned="x")))
        await writer.drain()
        notify = decode(await reader.readline())
        # Respond with an Error using the same request_id (unexpected for notify)
        writer.write(encode(Error(
            code="boom", message="boom", request_id=notify.request_id
        )))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        c = DaemonClient(label_preferred="x")
        await c.connect()
        result = await c.notify("hi")
        assert result.startswith("<NOTIFY_FAILED: ")
        await c.close()


# ───── auto-spawn ──────────────────────────────────────────────────────────


async def test_connect_auto_spawns_daemon_when_socket_missing(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)
    monkeypatch.setattr(client_mod, "log_file", lambda: tmp_path / "daemon.log")
    monkeypatch.setattr(client_mod, "_DAEMON_POLL_INTERVAL", 0.02)

    popen_calls = []
    server_holder: list = []

    async def handler(reader, writer):
        hello = decode(await reader.readline())
        writer.write(encode(HelloOk(request_id=hello.request_id, label_assigned="x")))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def start_fake_server_soon():
        await asyncio.sleep(0.05)
        srv = await asyncio.start_unix_server(handler, path=str(sock))
        server_holder.append(srv)

    spawn_task: list = []

    def fake_popen(cmd, **_):
        popen_calls.append(cmd)
        spawn_task.append(asyncio.create_task(start_fake_server_soon()))
        return MagicMock()

    monkeypatch.setattr(client_mod.subprocess, "Popen", fake_popen)

    c = DaemonClient(label_preferred="x")
    try:
        await c.connect()
        assert c.label == "x"
        assert popen_calls == [["confer-daemon"]]
    finally:
        await c.close()
        await spawn_task[0]
        server_holder[0].close()
        await server_holder[0].wait_closed()


async def test_connect_raises_when_daemon_does_not_start_in_time(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)
    monkeypatch.setattr(client_mod, "log_file", lambda: tmp_path / "daemon.log")
    monkeypatch.setattr(client_mod, "_DAEMON_SPAWN_TIMEOUT", 0.2)
    monkeypatch.setattr(client_mod, "_DAEMON_POLL_INTERVAL", 0.05)

    with patch.object(client_mod.subprocess, "Popen") as fake_popen:
        c = DaemonClient(label_preferred="x")
        with pytest.raises(RuntimeError, match="did not start"):
            await c.connect()
    fake_popen.assert_called_once()


# ───── miscellaneous ───────────────────────────────────────────────────────


def test_label_property_raises_before_connect():
    c = DaemonClient(label_preferred="x")
    with pytest.raises(RuntimeError, match="before connect"):
        _ = c.label


async def test_close_is_idempotent_when_never_connected():
    c = DaemonClient(label_preferred="x")
    await c.close()
    await c.close()


async def test_read_loop_ignores_invalid_json(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        hello = decode(await reader.readline())
        # send garbage line first
        writer.write(b"not-valid-json\n")
        # then the real HelloOk
        writer.write(encode(HelloOk(request_id=hello.request_id, label_assigned="x")))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        c = DaemonClient(label_preferred="x")
        await c.connect()
        assert c.label == "x"
        await c.close()


async def test_read_loop_skips_messages_with_no_request_id(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        hello = decode(await reader.readline())
        # Send a Bye (no request_id) which should be ignored by client's read loop
        writer.write(encode(Bye()))
        writer.write(encode(HelloOk(request_id=hello.request_id, label_assigned="x")))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        c = DaemonClient(label_preferred="x")
        await c.connect()
        await c.close()


async def test_close_when_reader_task_never_started():
    c = DaemonClient(label_preferred="x")
    c._writer = MagicMock()
    c._writer.write = MagicMock()
    c._writer.drain = AsyncMock()
    c._writer.close = MagicMock()
    c._writer.wait_closed = AsyncMock()
    c._reader_task = None
    await c.close()
    c._writer.close.assert_called_once()


async def test_close_swallows_reader_task_exception():
    c = DaemonClient(label_preferred="x")
    c._writer = MagicMock()
    c._writer.write = MagicMock()
    c._writer.drain = AsyncMock()
    c._writer.close = MagicMock()
    c._writer.wait_closed = AsyncMock()

    async def raises():
        raise RuntimeError("boom")

    task = asyncio.create_task(raises())
    c._reader_task = task

    # Explicitly let the task complete with its exception before close()
    # runs — clearer than the previous `await asyncio.sleep(0)` which
    # depended on event-loop scheduling.
    with pytest.raises(RuntimeError):
        await task

    await c.close()


async def test_read_loop_skips_messages_with_unknown_request_id(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        hello = decode(await reader.readline())
        writer.write(encode(NotifyResult(request_id="never-asked", status="ok", info="x")))
        writer.write(encode(HelloOk(request_id=hello.request_id, label_assigned="x")))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(handler, path=str(sock))
    try:
        c = DaemonClient(label_preferred="x")
        await c.connect()
        await c.close()
    finally:
        server.close()
        await server.wait_closed()


async def test_fail_pending_skips_already_done_futures():
    c = DaemonClient(label_preferred="x")
    loop = asyncio.get_event_loop()
    fut_done = loop.create_future()
    fut_done.set_result("already done")
    fut_pending = loop.create_future()
    c._pending = {"a": fut_done, "b": fut_pending}

    c._fail_pending("oh no")

    assert fut_done.result() == "already done"
    with pytest.raises(RuntimeError, match="oh no"):
        fut_pending.result()


async def test_notify_raises_when_daemon_closes_mid_request(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        hello = decode(await reader.readline())
        writer.write(encode(HelloOk(request_id=hello.request_id, label_assigned="x")))
        await writer.drain()
        await reader.readline()  # read notify
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        c = DaemonClient(label_preferred="x")
        await c.connect()
        with pytest.raises(RuntimeError, match="daemon closed"):
            await c.notify("hi")
        await c.close()
