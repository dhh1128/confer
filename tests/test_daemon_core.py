import asyncio
import errno
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from confer.daemon.core import Daemon, _Client, _make_disambiguator
from confer.daemon.transport import FAILURE_PREFIX
from confer.protocol import (
    CURRENT_PROTOCOL_VERSION,
    Bye,
    Error,
    Hello,
    HelloErr,
    HelloOk,
    Notify,
    NotifyResult,
    Status,
    StatusResult,
    decode,
    encode,
)


def _writer_mock() -> MagicMock:
    w = MagicMock()
    w.write = MagicMock()
    w.drain = AsyncMock()
    w.close = MagicMock()
    w.wait_closed = AsyncMock()
    return w


def _written_messages(writer: MagicMock) -> list:
    raw = b"".join(call.args[0] for call in writer.write.call_args_list)
    lines = [line for line in raw.split(b"\n") if line.strip()]
    return [decode(line) for line in lines]


def _reader_with(messages) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    for msg in messages:
        reader.feed_data(encode(msg))
    reader.feed_eof()
    return reader


def _make_daemon() -> Daemon:
    transport = MagicMock()
    transport.notify = AsyncMock(return_value="sent at 2026-05-28T00:00:00+00:00")
    return Daemon(transport=transport)


async def test_hello_assigns_label_and_responds():
    daemon = _make_daemon()
    reader = _reader_with(
        [Hello(request_id="r1", label_preferred="confer/main", pid=42)]
    )
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    responses = _written_messages(writer)
    assert len(responses) == 1
    assert isinstance(responses[0], HelloOk)
    assert responses[0].request_id == "r1"
    assert responses[0].label_assigned == "confer/main"


async def test_hello_disambiguates_on_label_collision():
    daemon = _make_daemon()
    daemon._clients["confer/main"] = _Client(
        label="confer/main", writer=_writer_mock()
    )
    reader = _reader_with(
        [Hello(request_id="r1", label_preferred="confer/main", pid=42)]
    )
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    response = _written_messages(writer)[0]
    assert response.label_assigned.startswith("confer/main#")
    assert len(response.label_assigned) == len("confer/main") + 1 + 4


async def test_notify_dispatches_to_transport_and_returns_ok():
    daemon = _make_daemon()
    reader = _reader_with([
        Hello(request_id="r1", label_preferred="confer/main", pid=1),
        Notify(request_id="r2", message="hi"),
    ])
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    responses = _written_messages(writer)
    assert isinstance(responses[1], NotifyResult)
    assert responses[1].request_id == "r2"
    assert responses[1].status == "ok"
    assert responses[1].info.startswith("sent at ")
    daemon._transport.notify.assert_awaited_once_with("hi")


async def test_notify_returns_failed_status_when_transport_returns_failure():
    daemon = _make_daemon()
    daemon._transport.notify = AsyncMock(
        return_value=f"{FAILURE_PREFIX}HTTPException: boom>"
    )
    reader = _reader_with([
        Hello(request_id="r1", label_preferred="x", pid=1),
        Notify(request_id="r2", message="hi"),
    ])
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    assert _written_messages(writer)[1].status == "failed"


async def test_bye_terminates_handler_and_skips_subsequent_messages():
    daemon = _make_daemon()
    reader = asyncio.StreamReader()
    reader.feed_data(encode(Hello(request_id="r1", label_preferred="x", pid=1)))
    reader.feed_data(encode(Bye()))
    reader.feed_data(encode(Notify(request_id="r9", message="never")))
    reader.feed_eof()
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    responses = _written_messages(writer)
    assert len(responses) == 1
    assert isinstance(responses[0], HelloOk)


async def test_invalid_json_returns_error_response():
    daemon = _make_daemon()
    reader = asyncio.StreamReader()
    reader.feed_data(b"not json\n")
    reader.feed_eof()
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    response = _written_messages(writer)[0]
    assert isinstance(response, Error)
    assert response.code == "bad_message"


async def test_empty_line_is_skipped():
    daemon = _make_daemon()
    reader = asyncio.StreamReader()
    reader.feed_data(b"\n  \n")
    reader.feed_eof()
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    assert _written_messages(writer) == []


async def test_hello_with_unsupported_protocol_version_returns_hello_err():
    daemon = _make_daemon()
    reader = _reader_with(
        [Hello(request_id="r1", label_preferred="x", pid=1, protocol_version=999)]
    )
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    response = _written_messages(writer)[0]
    assert isinstance(response, HelloErr)
    assert response.request_id == "r1"
    assert "protocol_version 999 not supported" in response.reason
    # No client registered
    assert "x" not in daemon._clients


async def test_notify_before_hello_returns_hello_required_error():
    daemon = _make_daemon()
    reader = _reader_with([Notify(request_id="r1", message="hi")])
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    response = _written_messages(writer)[0]
    assert isinstance(response, Error)
    assert response.code == "hello_required"
    assert response.request_id == "r1"
    # transport.notify was never called
    daemon._transport.notify.assert_not_called()


async def test_status_does_not_require_hello():
    """STATUS comes from the CLI; it has no agent identity and must work
    without prior HELLO."""
    daemon = _make_daemon()
    daemon._start_time = 100.0
    reader = _reader_with([Status(request_id="r1")])
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    response = _written_messages(writer)[0]
    assert isinstance(response, StatusResult)


async def test_unexpected_message_kind_returns_error():
    daemon = _make_daemon()
    reader = _reader_with([
        Hello(request_id="r0", label_preferred="x", pid=1),
        HelloOk(request_id="r1", label_assigned="x"),  # client should never send this
    ])
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    responses = _written_messages(writer)
    assert isinstance(responses[1], Error)
    assert responses[1].code == "unexpected_message"
    assert responses[1].request_id == "r1"


async def test_client_disconnect_removes_label_from_registry():
    daemon = _make_daemon()
    reader = _reader_with(
        [Hello(request_id="r1", label_preferred="confer/main", pid=1)]
    )
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    assert "confer/main" not in daemon._clients


async def test_status_reports_uptime_gateway_state_and_sorted_clients():
    daemon = _make_daemon()
    daemon._transport.is_ready = MagicMock(return_value=True)
    daemon._start_time = 1000.0
    daemon._clients["zzz"] = _Client(label="zzz", writer=_writer_mock())
    daemon._clients["aaa"] = _Client(label="aaa", writer=_writer_mock())

    reader = _reader_with([Status(request_id="s1")])
    writer = _writer_mock()

    import time as _time
    real_time = _time.time
    _time.time = lambda: 1005.0
    try:
        await daemon._handle_client(reader, writer)
    finally:
        _time.time = real_time

    response = _written_messages(writer)[0]
    assert isinstance(response, StatusResult)
    assert response.request_id == "s1"
    assert response.uptime_seconds == 5.0
    assert response.gateway_state == "ready"
    assert response.clients == ["aaa", "zzz"]


async def test_status_reports_not_ready_when_gateway_not_ready():
    daemon = _make_daemon()
    daemon._transport.is_ready = MagicMock(return_value=False)
    daemon._start_time = None

    reader = _reader_with([Status(request_id="s1")])
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)

    response = _written_messages(writer)[0]
    assert response.gateway_state == "not_ready"
    assert response.uptime_seconds == 0.0


def test_make_disambiguator_is_4_lowercase_hex_chars():
    d = _make_disambiguator(1)
    assert len(d) == 4
    assert all(c in "0123456789abcdef" for c in d)


def test_assign_label_raises_when_all_disambiguators_collide(monkeypatch):
    import pytest

    daemon = _make_daemon()
    daemon._clients["x"] = _Client(label="x", writer=_writer_mock())
    daemon._clients["x#dead"] = _Client(label="x#dead", writer=_writer_mock())
    monkeypatch.setattr(
        "confer.daemon.core._make_disambiguator", lambda pid: "dead"
    )
    with pytest.raises(RuntimeError, match="could not assign"):
        daemon._assign_label("x", 42)


async def test_serve_binds_socket_with_0600_perms_and_writes_pid(tmp_path):
    sock = tmp_path / "confer.sock"
    pid = tmp_path / "confer.pid"
    transport = MagicMock()
    transport.connect = AsyncMock()
    transport.wait_for_ready = AsyncMock()
    transport.close = AsyncMock()
    daemon = Daemon(transport=transport)

    task = asyncio.create_task(daemon.serve(sock, pid))
    for _ in range(200):
        if sock.exists() and pid.exists():
            break
        await asyncio.sleep(0.01)

    assert sock.exists()
    assert sock.stat().st_mode & 0o777 == 0o600
    assert pid.read_text() == str(os.getpid())
    transport.connect.assert_awaited_once()
    transport.wait_for_ready.assert_awaited_once()

    daemon.stop()
    await task

    transport.close.assert_awaited_once()
    assert not sock.exists()
    assert not pid.exists()


async def test_serve_responds_to_signal_via_stop_event(tmp_path):
    import signal as _signal

    sock = tmp_path / "confer.sock"
    pid = tmp_path / "confer.pid"
    transport = MagicMock()
    transport.connect = AsyncMock()
    transport.wait_for_ready = AsyncMock()
    transport.close = AsyncMock()
    daemon = Daemon(transport=transport)

    task = asyncio.create_task(daemon.serve(sock, pid))
    for _ in range(200):
        if sock.exists():
            break
        await asyncio.sleep(0.01)

    # Send a real SIGTERM to our own process; the daemon's signal handler
    # (installed in serve()) should set the stop event and trigger cleanup.
    os.kill(os.getpid(), _signal.SIGTERM)
    await task
    assert not sock.exists()
    assert not pid.exists()


async def test_serve_handles_eaddrinuse_silently_on_bind(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    pid = tmp_path / "confer.pid"
    transport = MagicMock()
    transport.connect = AsyncMock()
    transport.wait_for_ready = AsyncMock()
    transport.close = AsyncMock()
    daemon = Daemon(transport=transport)

    def raise_eaddrinuse(*args, **kwargs):
        raise OSError(errno.EADDRINUSE, "Address in use")

    monkeypatch.setattr(asyncio, "start_unix_server", raise_eaddrinuse)

    # No exception should escape; daemon should clean up and return.
    await daemon.serve(sock, pid)

    transport.close.assert_awaited_once()
    assert not pid.exists()


async def test_serve_propagates_unexpected_oserror_on_bind(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    pid = tmp_path / "confer.pid"
    transport = MagicMock()
    transport.connect = AsyncMock()
    transport.wait_for_ready = AsyncMock()
    transport.close = AsyncMock()
    daemon = Daemon(transport=transport)

    def raise_other(*args, **kwargs):
        raise OSError(errno.EACCES, "permission denied")

    monkeypatch.setattr(asyncio, "start_unix_server", raise_other)

    with pytest.raises(OSError, match="permission denied"):
        await daemon.serve(sock, pid)


def test_atomic_write_pid_file_replaces_existing(tmp_path):
    from confer.daemon.core import _atomic_write_pid_file

    pf = tmp_path / "confer.pid"
    pf.write_text("99999")
    _atomic_write_pid_file(pf, 12345)
    assert pf.read_text() == "12345"
    # No leftover .tmp file
    assert not pf.with_suffix(pf.suffix + ".tmp").exists()


def test_stop_is_noop_when_no_serve_running(tmp_path):
    transport = MagicMock()
    daemon = Daemon(transport=transport)
    # Should not raise; stop is a no-op when _stop_event is None.
    daemon.stop()


async def test_serve_detects_another_running_daemon_and_exits_cleanly(tmp_path):
    sock = tmp_path / "confer.sock"
    pid = tmp_path / "confer.pid"

    saw_probe = False

    async def fake_handler(reader, writer):
        nonlocal saw_probe
        saw_probe = True
        writer.close()
        await writer.wait_closed()

    fake_server = await asyncio.start_unix_server(fake_handler, path=str(sock))
    try:
        transport = MagicMock()
        transport.connect = AsyncMock()
        transport.wait_for_ready = AsyncMock()
        transport.close = AsyncMock()
        daemon = Daemon(transport=transport)

        await daemon.serve(sock, pid)

        transport.connect.assert_not_called()
        await asyncio.sleep(0.01)
        assert saw_probe
        assert not pid.exists()
    finally:
        fake_server.close()
        await fake_server.wait_closed()


async def test_serve_removes_stale_socket_file_and_binds(tmp_path):
    sock = tmp_path / "confer.sock"
    pid = tmp_path / "confer.pid"

    # Stale socket file (regular file, nothing listening).
    sock.write_text("stale")

    transport = MagicMock()
    transport.connect = AsyncMock()
    transport.wait_for_ready = AsyncMock()
    transport.close = AsyncMock()
    daemon = Daemon(transport=transport)

    task = asyncio.create_task(daemon.serve(sock, pid))
    for _ in range(200):
        if pid.exists():
            break
        await asyncio.sleep(0.01)

    assert pid.exists()

    daemon.stop()
    await task
