import asyncio
import errno
import os
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from confer.daemon.core import (
    Daemon,
    QueuedMessage,
    _Client,
    _NotifyThread,
    _PendingAsk,
    _closing_dm_text,
    _make_disambiguator,
)
from confer.daemon.transport import FAILURE_PREFIX
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
    # The notify is sent as a tagged thread body "[tag] label: message".
    body = daemon._transport.notify.await_args.args[0]
    assert body.endswith("confer/main: hi")
    assert body.startswith("[") and "] confer/main:" in body


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


async def test_status_reports_uptime_gateway_state_and_sorted_clients(monkeypatch):
    daemon = _make_daemon()
    daemon._transport.is_ready = MagicMock(return_value=True)
    daemon._start_time = 1000.0
    daemon._clients["zzz"] = _Client(label="zzz", writer=_writer_mock())
    daemon._clients["aaa"] = _Client(label="aaa", writer=_writer_mock())

    reader = _reader_with([Status(request_id="s1")])
    writer = _writer_mock()

    # Use monkeypatch (auto-reverts on test exit) instead of manual save/
    # restore of a module attribute (would leak if an exception fired
    # before the try block).
    monkeypatch.setattr("confer.daemon.core.time.time", lambda: 1005.0)
    await daemon._handle_client(reader, writer)

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


async def test_serve_creates_parent_dirs_with_0700_perms(tmp_path):
    """The fallback XDG_RUNTIME_DIR is a subdirectory we create ourselves;
    it must be 0700 since the socket-perm protection relies on the parent
    being inaccessible too."""
    parent = tmp_path / "runtime"
    sock = parent / "confer.sock"
    pid = parent / "confer.pid"
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

    assert parent.stat().st_mode & 0o777 == 0o700

    daemon.stop()
    await task


async def test_serve_chmods_existing_parent_dir_to_0700(tmp_path):
    parent = tmp_path / "runtime"
    parent.mkdir(mode=0o755)  # pre-existing with loose perms
    sock = parent / "confer.sock"
    pid = parent / "confer.pid"
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

    assert parent.stat().st_mode & 0o777 == 0o700

    daemon.stop()
    await task


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


# ───── Multi-client / concurrency (C4 thorough coverage) ───────────────────


async def test_two_concurrent_clients_with_distinct_labels_both_registered():
    daemon = _make_daemon()

    r1, w1 = asyncio.StreamReader(), _writer_mock()
    r2, w2 = asyncio.StreamReader(), _writer_mock()

    r1.feed_data(encode(Hello(request_id="h1", label_preferred="agent-a", pid=1)))
    r2.feed_data(encode(Hello(request_id="h2", label_preferred="agent-b", pid=2)))

    t1 = asyncio.create_task(daemon._handle_client(r1, w1))
    t2 = asyncio.create_task(daemon._handle_client(r2, w2))

    # Poll until both HELLO_OK have been written
    for _ in range(200):
        if w1.write.call_count and w2.write.call_count:
            break
        await asyncio.sleep(0.005)

    assert "agent-a" in daemon._clients
    assert "agent-b" in daemon._clients
    assert len(daemon._clients) == 2

    r1.feed_eof()
    r2.feed_eof()
    await asyncio.gather(t1, t2)

    assert daemon._clients == {}


async def test_label_collision_under_contention_disambiguates_later_arrival():
    daemon = _make_daemon()

    r1, w1 = asyncio.StreamReader(), _writer_mock()
    r1.feed_data(encode(Hello(request_id="h1", label_preferred="confer/main", pid=1)))
    t1 = asyncio.create_task(daemon._handle_client(r1, w1))

    for _ in range(200):
        if w1.write.call_count:
            break
        await asyncio.sleep(0.005)
    assert "confer/main" in daemon._clients

    r2, w2 = asyncio.StreamReader(), _writer_mock()
    r2.feed_data(encode(Hello(request_id="h2", label_preferred="confer/main", pid=2)))
    t2 = asyncio.create_task(daemon._handle_client(r2, w2))

    for _ in range(200):
        if w2.write.call_count:
            break
        await asyncio.sleep(0.005)

    response2 = _written_messages(w2)[0]
    assert isinstance(response2, HelloOk)
    assert response2.label_assigned.startswith("confer/main#")
    assert response2.label_assigned in daemon._clients
    assert len(daemon._clients) == 2

    r1.feed_eof()
    r2.feed_eof()
    await asyncio.gather(t1, t2)


async def test_concurrent_notify_from_two_clients_each_gets_correct_result():
    daemon = _make_daemon()

    async def slow_notify(msg):
        await asyncio.sleep(0.01)
        return f"sent at {msg}"

    daemon._transport.notify = AsyncMock(side_effect=slow_notify)

    r1, w1 = asyncio.StreamReader(), _writer_mock()
    r2, w2 = asyncio.StreamReader(), _writer_mock()

    r1.feed_data(encode(Hello(request_id="h1", label_preferred="a", pid=1)))
    r1.feed_data(encode(Notify(request_id="n1", message="msg-a")))
    r1.feed_eof()

    r2.feed_data(encode(Hello(request_id="h2", label_preferred="b", pid=2)))
    r2.feed_data(encode(Notify(request_id="n2", message="msg-b")))
    r2.feed_eof()

    await asyncio.gather(
        daemon._handle_client(r1, w1),
        daemon._handle_client(r2, w2),
    )

    r1_messages = _written_messages(w1)
    r2_messages = _written_messages(w2)
    assert len(r1_messages) == 2 and len(r2_messages) == 2
    nr1 = r1_messages[1]
    nr2 = r2_messages[1]
    assert isinstance(nr1, NotifyResult) and isinstance(nr2, NotifyResult)
    # The daemon now sends a tagged body "[tag] label: message"; the echo
    # transport reflects that, and each client gets its own correct message.
    assert nr1.request_id == "n1" and nr1.info.endswith("a: msg-a")
    assert nr2.request_id == "n2" and nr2.info.endswith("b: msg-b")


async def test_status_reflects_concurrent_connected_clients(monkeypatch):
    daemon = _make_daemon()
    daemon._transport.is_ready = MagicMock(return_value=True)
    daemon._start_time = 0.0
    monkeypatch.setattr("confer.daemon.core.time.time", lambda: 5.0)

    r1, w1 = asyncio.StreamReader(), _writer_mock()
    r2, w2 = asyncio.StreamReader(), _writer_mock()
    r1.feed_data(encode(Hello(request_id="h1", label_preferred="alpha", pid=1)))
    r2.feed_data(encode(Hello(request_id="h2", label_preferred="beta", pid=2)))

    t1 = asyncio.create_task(daemon._handle_client(r1, w1))
    t2 = asyncio.create_task(daemon._handle_client(r2, w2))

    for _ in range(200):
        if len(daemon._clients) == 2:
            break
        await asyncio.sleep(0.005)

    # Now a CLI sends Status while both are connected
    rs, ws = _reader_with([Status(request_id="s1")]), _writer_mock()
    await daemon._handle_client(rs, ws)

    response = _written_messages(ws)[0]
    assert isinstance(response, StatusResult)
    assert sorted(response.clients) == ["alpha", "beta"]

    r1.feed_eof()
    r2.feed_eof()
    await asyncio.gather(t1, t2)


# ───── TM-CV2: disconnect cleanup observable via Status ────────────────────


async def test_status_does_not_include_disconnected_clients():
    daemon = _make_daemon()
    daemon._transport.is_ready = MagicMock(return_value=True)
    daemon._start_time = 0.0

    # Client connects, registers, then immediately disconnects (EOF).
    r = _reader_with([Hello(request_id="h1", label_preferred="ephemeral", pid=1)])
    w = _writer_mock()
    await daemon._handle_client(r, w)

    assert "ephemeral" not in daemon._clients

    # CLI Status query after disconnect: 'ephemeral' should NOT be listed.
    rs = _reader_with([Status(request_id="s1")])
    ws = _writer_mock()
    await daemon._handle_client(rs, ws)

    response = _written_messages(ws)[0]
    assert isinstance(response, StatusResult)
    assert "ephemeral" not in response.clients


# ───── TM-CV3: _another_instance_running on PermissionError ────────────────


async def test_another_instance_running_returns_false_on_permission_error(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    sock.write_text("stale")

    async def raise_permission(_):
        raise PermissionError("EACCES")

    monkeypatch.setattr(asyncio, "open_unix_connection", raise_permission)

    transport = MagicMock()
    daemon = Daemon(transport=transport)
    result = await daemon._another_instance_running(sock)
    # Documented broad-OSError catch: any failure to connect is treated as
    # "nobody there" so the daemon proceeds to unlink and bind. EACCES is
    # in scope.
    assert result is False


# ───── TM2: _make_disambiguator collision space ────────────────────────────


def test_make_disambiguator_produces_distinct_values_for_repeated_calls():
    """Two calls with the same pid produce different hashes because the
    time_ns input differs. Not strictly guaranteed but vanishingly unlikely
    to fail at 100 iterations."""
    seen = set()
    for _ in range(100):
        seen.add(_make_disambiguator(42))
    # Expect very high distinctness (in practice all 100 should differ).
    assert len(seen) > 50


# ───── TM4: connection reset / broken pipe in reader ────────────────────────


async def test_handle_client_swallows_connection_reset_in_reader():
    daemon = _make_daemon()
    reader = asyncio.StreamReader()
    reader.set_exception(ConnectionResetError("connection reset"))
    writer = _writer_mock()

    # Should not propagate the ConnectionResetError; finally runs cleanly.
    await daemon._handle_client(reader, writer)


async def test_handle_client_swallows_broken_pipe_in_reader():
    daemon = _make_daemon()
    reader = asyncio.StreamReader()
    reader.set_exception(BrokenPipeError("pipe closed"))
    writer = _writer_mock()

    await daemon._handle_client(reader, writer)


# ───── (back to lifecycle / stop tests) ────────────────────────────────────


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




# ─── ask machinery (G3 tag model) ───────────────────────────────────────────


def _mocked_transport() -> MagicMock:
    t = MagicMock()
    t.notify = AsyncMock(return_value="sent at 2026-05-29T00:00:00+00:00")
    return t


class _FakeClock:
    """Deterministic clock+sleep for timing tests (TST-F1): sleep advances the
    clock by the requested duration and yields once — no wall-clock dependence,
    so the production timing constants are exercised at real values."""

    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    async def sleep(self, d: float) -> None:
        self.now += d
        await asyncio.sleep(0)


def _clock_daemon(re_ping_every_seconds: int = 900) -> tuple[Daemon, _FakeClock]:
    fc = _FakeClock()
    daemon = Daemon(
        transport=_mocked_transport(),
        re_ping_every_seconds=re_ping_every_seconds,
        clock=fc.time,
        sleep=fc.sleep,
    )
    return daemon, fc


def _insert_pending(
    daemon: Daemon,
    writer: MagicMock,
    *,
    request_id: str = "ask-r1",
    question: str = "rebase?",
    on_timeout: str = "use_best_judgment",
    give_up_after_seconds: float = 30,
    label: str = "confer/main",
    tag: str = "taga",
) -> _PendingAsk:
    """Insert a pending ask WITHOUT spawning the background timeout/re-ping
    tasks, so a test can drive _timeout_loop / _re_ping_loop directly against
    a fake clock."""
    pending = _PendingAsk(
        request_id=request_id,
        label=label,
        question=question,
        on_timeout=on_timeout,
        give_up_after_seconds=give_up_after_seconds,
        started_at=daemon._clock(),
        writer=writer,
        tag=tag,
    )
    daemon._pending_asks[request_id] = pending
    return pending


async def _hello_and_get_writer(daemon: Daemon, label: str = "confer/main") -> MagicMock:
    writer = _writer_mock()
    daemon._clients[label] = _Client(label=label, writer=writer)
    return writer


async def _register_ask(
    daemon: Daemon,
    request_id: str = "ask-r1",
    question: str = "rebase?",
    on_timeout="use_best_judgment",
    give_up_after_seconds: int = 60,
    label: str = "confer/main",
    writer: MagicMock | None = None,
) -> tuple[MagicMock, _PendingAsk]:
    if writer is None:
        writer = await _hello_and_get_writer(daemon, label=label)
    msg = AskBegin(
        request_id=request_id,
        question=question,
        give_up_after_seconds=give_up_after_seconds,
        on_timeout=on_timeout,
    )
    await daemon._handle_ask_begin(msg, writer, label)
    return writer, daemon._pending_asks[request_id]


async def test_ask_begin_assigns_tag_and_sends_tagged_question_dm():
    daemon = _make_daemon()
    writer, pending = await _register_ask(daemon)
    assert len(pending.tag) == 4
    assert all(c in "abcdefghijklmnopqrstuvwxyz234567" for c in pending.tag)
    body = daemon._transport.notify.await_args.args[0]
    assert body == f"[{pending.tag}] confer/main: rebase?"
    # No footer.
    assert "reply:" not in body
    await daemon._handle_ask_cancel(pending.request_id)


async def test_thread_tags_are_unique_across_active_threads():
    daemon = _make_daemon()
    w1, p1 = await _register_ask(daemon, request_id="r1", label="confer/main")
    w2 = await _hello_and_get_writer(daemon, label="myapp/feat")
    await daemon._handle_ask_begin(
        AskBegin(request_id="r2", question="merge?", give_up_after_seconds=60,
                 on_timeout="abort"),
        w2, "myapp/feat",
    )
    assert p1.tag != daemon._pending_asks["r2"].tag
    await daemon._handle_ask_cancel("r1")
    await daemon._handle_ask_cancel("r2")


async def test_assign_thread_tag_regenerates_on_collision(monkeypatch):
    daemon = _make_daemon()
    seq = iter(["aaaa", "aaaa", "bbbb"])
    monkeypatch.setattr("confer.daemon.core._make_thread_tag", lambda: next(seq))
    # Pre-occupy "aaaa".
    daemon._notify_threads["aaaa"] = _NotifyThread(
        tag="aaaa", label="x", created_at=1.0
    )
    tag = daemon._assign_thread_tag()
    assert tag == "bbbb"


async def test_assign_thread_tag_raises_after_100_collisions(monkeypatch):
    daemon = _make_daemon()
    monkeypatch.setattr("confer.daemon.core._make_thread_tag", lambda: "aaaa")
    daemon._notify_threads["aaaa"] = _NotifyThread(
        tag="aaaa", label="x", created_at=1.0
    )
    with pytest.raises(RuntimeError, match="unique thread tag"):
        daemon._assign_thread_tag()


async def test_ask_cancel_sends_withdrawn_dm_with_tag():
    daemon = _make_daemon()
    writer, pending = await _register_ask(daemon)
    daemon._transport.notify.reset_mock()
    await daemon._handle_ask_cancel(pending.request_id)
    assert pending.request_id not in daemon._pending_asks
    body = daemon._transport.notify.await_args.args[0]
    assert body == f"Re: {pending.tag} — question withdrawn."


async def test_ask_cancel_idempotent_when_absent():
    daemon = _make_daemon()
    await daemon._handle_ask_cancel("nope")
    daemon._transport.notify.assert_not_awaited()


async def test_timeout_use_best_judgment_sends_directive_and_closing_dm():
    # Deterministic: drive the timeout loop directly against a fake clock with a
    # realistic give_up_after_seconds (not 0), no wall-clock margin.
    daemon, fc = _clock_daemon()
    writer = await _hello_and_get_writer(daemon)
    pending = _insert_pending(daemon, writer, give_up_after_seconds=30, tag="bj01")
    await daemon._timeout_loop(pending)
    assert pending.request_id not in daemon._pending_asks
    assert fc.now == 30  # the loop waited exactly the give-up window
    sent = _written_messages(writer)
    assert any(
        isinstance(m, AskTimeout) and m.outcome == "use_best_judgment" for m in sent
    )
    bodies = [c.args[0] for c in daemon._transport.notify.await_args_list]
    assert "Re: bj01 — time's up; agent will use its best judgment." in bodies


async def test_timeout_loop_cancels_live_re_ping_task():
    # Covers the timeout path that cancels a still-running re-ping task.
    daemon, fc = _clock_daemon()
    writer = await _hello_and_get_writer(daemon)
    pending = _insert_pending(daemon, writer, give_up_after_seconds=30, tag="tc01")

    async def _sleeper():
        await asyncio.sleep(3600)

    pending.re_ping_task = asyncio.create_task(_sleeper())
    await daemon._timeout_loop(pending)
    with pytest.raises(asyncio.CancelledError):
        await pending.re_ping_task


async def test_timeout_abort_sends_abort_directive():
    daemon, fc = _clock_daemon()
    writer = await _hello_and_get_writer(daemon)
    pending = _insert_pending(
        daemon, writer, on_timeout="abort", give_up_after_seconds=30, tag="ab01"
    )
    await daemon._timeout_loop(pending)
    sent = _written_messages(writer)
    assert any(isinstance(m, AskTimeout) and m.outcome == "abort" for m in sent)
    bodies = [c.args[0] for c in daemon._transport.notify.await_args_list]
    assert "Re: ab01 — time's up; agent will stop and surface task state." in bodies


async def test_dispatch_user_message_single_ask_unprefixed_delivers():
    daemon = _make_daemon()
    writer, pending = await _register_ask(daemon)
    await daemon._dispatch_user_message("rebase please")
    assert pending.request_id not in daemon._pending_asks
    reply = next(m for m in _written_messages(writer) if isinstance(m, AskReply))
    assert reply.content == "rebase please"


async def test_dispatch_user_message_tag_routes_to_specific_ask():
    daemon = _make_daemon()
    w1, p1 = await _register_ask(daemon, request_id="r1", label="confer/main")
    w2 = await _hello_and_get_writer(daemon, label="myapp/feat")
    await daemon._handle_ask_begin(
        AskBegin(request_id="r2", question="merge?", give_up_after_seconds=60,
                 on_timeout="use_best_judgment"),
        w2, "myapp/feat",
    )
    p2 = daemon._pending_asks["r2"]
    await daemon._dispatch_user_message(f"re {p2.tag} go ahead")
    assert "r2" not in daemon._pending_asks
    assert "r1" in daemon._pending_asks  # untouched
    reply = next(m for m in _written_messages(w2) if isinstance(m, AskReply))
    assert reply.content == "go ahead"
    await daemon._handle_ask_cancel("r1")


async def test_dispatch_user_message_bounces_when_no_agents():
    daemon = _make_daemon()
    await daemon._dispatch_user_message("anyone?")
    body = daemon._transport.notify.await_args.args[0]
    assert "No agent is connected" in body


async def test_dispatch_user_message_broadcasts_when_no_asks_but_connected():
    daemon = _make_daemon()
    daemon._clients["confer/main"] = _Client(label="confer/main", writer=_writer_mock())
    daemon._clients["myapp/feat"] = _Client(label="myapp/feat", writer=_writer_mock())
    await daemon._dispatch_user_message("stop, reqs changed")
    for label in ("confer/main", "myapp/feat"):
        msgs = list(daemon._queues[label])
        assert len(msgs) == 1
        assert msgs[0].source == "broadcast"
        assert msgs[0].tag is None
    daemon._transport.notify.assert_not_awaited()


async def test_dispatch_user_message_ambiguous_lists_tags():
    daemon = _make_daemon()
    w1, p1 = await _register_ask(daemon, request_id="r1", label="confer/main")
    w2 = await _hello_and_get_writer(daemon, label="myapp/feat")
    await daemon._handle_ask_begin(
        AskBegin(request_id="r2", question="merge?", give_up_after_seconds=60,
                 on_timeout="use_best_judgment"),
        w2, "myapp/feat",
    )
    daemon._transport.notify.reset_mock()
    await daemon._dispatch_user_message("hello")
    body = daemon._transport.notify.await_args.args[0]
    assert "Multiple questions are waiting" in body
    assert p1.tag in body
    assert daemon._pending_asks["r2"].tag in body
    await daemon._handle_ask_cancel("r1")
    await daemon._handle_ask_cancel("r2")


async def test_dispatch_user_message_concierge_stub_bounces():
    daemon = _make_daemon()
    await daemon._dispatch_user_message(".threads")
    body = daemon._transport.notify.await_args.args[0]
    assert "concierge commands aren't available yet" in body


# ─── notify-replyable threads ───────────────────────────────────────────────


async def test_notify_creates_tagged_replyable_thread():
    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon, "confer/main")
    await daemon._handle_notify(
        Notify(request_id="n1", message="deploy finished"), writer, "confer/main"
    )
    body = daemon._transport.notify.await_args.args[0]
    # Body is "[tag] label: message"; the tag is now a live notify-thread.
    assert body.startswith("[")
    assert "confer/main: deploy finished" in body
    assert len(daemon._notify_threads) == 1
    tag = next(iter(daemon._notify_threads))
    # Reply to the notify tag enqueues an interjection.
    await daemon._dispatch_user_message(f"re {tag} roll it back")
    msgs = list(daemon._queues["confer/main"])
    assert len(msgs) == 1
    assert msgs[0].source == "notify_reply"
    assert msgs[0].tag == tag
    assert msgs[0].content == "roll it back"


async def test_notify_thread_dropped_on_disconnect():
    daemon = _make_daemon()
    reader = _reader_with([
        Hello(request_id="r1", label_preferred="confer/main", pid=1),
        Notify(request_id="n1", message="done"),
    ])
    writer = _writer_mock()
    await daemon._handle_client(reader, writer)
    # After the client disconnects (reader EOF), its notify-thread is gone.
    assert daemon._notify_threads == {}


async def test_notify_thread_cap_evicts_oldest_per_label(monkeypatch):
    daemon = _make_daemon()
    # Force deterministic, unique tags.
    seq = iter([f"t{n:03d}"[:4] for n in range(100)])
    monkeypatch.setattr("confer.daemon.core._make_thread_tag", lambda: next(seq))
    writer = await _hello_and_get_writer(daemon, "confer/main")
    # Register one more than the cap.
    from confer.daemon.core import _NOTIFY_TAGS_PER_LABEL
    for i in range(_NOTIFY_TAGS_PER_LABEL + 1):
        await daemon._handle_notify(
            Notify(request_id=f"n{i}", message=f"m{i}"), writer, "confer/main"
        )
    assert len(daemon._notify_threads) == _NOTIFY_TAGS_PER_LABEL


# ─── check_messages (G3 formatting) ─────────────────────────────────────────


async def test_check_messages_formats_sources_with_tags_and_clears():
    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon)
    daemon._enqueue_message("confer/main", "everyone stop", source="broadcast", tag=None)
    daemon._enqueue_message("confer/main", "roll back", source="notify_reply", tag="m4rs")
    daemon._enqueue_message("confer/main", "late answer", source="late_reply", tag="k3qp")
    await daemon._handle_check_messages("req", "confer/main", writer)
    result = next(m for m in _written_messages(writer) if isinstance(m, CheckMessagesResult))
    assert result.count == 3
    assert "[broadcast] everyone stop" in result.formatted
    assert "[re m4rs] roll back" in result.formatted
    assert "[re k3qp] late answer" in result.formatted
    assert not daemon._queues["confer/main"]


async def test_check_messages_late_reply_without_tag_uses_fallback_label():
    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon)
    daemon._enqueue_message("confer/main", "x", source="late_reply", tag=None)
    await daemon._handle_check_messages("req", "confer/main", writer)
    result = next(m for m in _written_messages(writer) if isinstance(m, CheckMessagesResult))
    assert "[late-reply] x" in result.formatted


async def test_check_messages_empty_directive():
    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon)
    await daemon._handle_check_messages("req", "confer/main", writer)
    result = next(m for m in _written_messages(writer) if isinstance(m, CheckMessagesResult))
    assert result.count == 0
    assert "No new messages" in result.formatted


async def test_check_messages_through_full_dispatch_path():
    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon)
    daemon._enqueue_message("confer/main", "hi", source="broadcast", tag=None)
    await daemon._dispatch(CheckMessages(request_id="r"), writer, "confer/main")
    assert any(isinstance(m, CheckMessagesResult) for m in _written_messages(writer))


async def test_queue_evicts_oldest_when_full(caplog):
    import logging
    daemon = _make_daemon()
    with caplog.at_level(logging.WARNING, logger="confer.daemon.core"):
        for i in range(101):
            daemon._enqueue_message("confer/main", f"m{i}", source="broadcast", tag=None)
    q = daemon._queues["confer/main"]
    assert len(q) == 100
    assert q[0].content == "m1"
    assert any("queue full" in r.getMessage() for r in caplog.records)


# ─── orphan drop on disconnect ──────────────────────────────────────────────


async def test_disconnect_drops_asks_with_lost_contact_dm():
    daemon = _make_daemon()
    writer, pending = await _register_ask(daemon)
    tag = pending.tag
    daemon._transport.notify.reset_mock()
    await daemon._drop_asks_for_writer(writer, "confer/main")
    assert pending.request_id not in daemon._pending_asks
    body = daemon._transport.notify.await_args.args[0]
    assert body == f"Re: {tag} — lost contact with the agent that asked."


# ─── re-ping ─────────────────────────────────────────────────────────────────


def test_should_skip_reping_across_60s_boundary():
    # Pure-function test of the skip arithmetic at the real 60s constant (TST-F3):
    # this is what the old give_up=0.1 test could never exercise.
    from confer.daemon.core import _SKIP_REPING_NEAR_DEADLINE, _should_skip_reping
    deadline = 1000.0
    assert _should_skip_reping(deadline - (_SKIP_REPING_NEAR_DEADLINE + 1), deadline) is False
    assert _should_skip_reping(deadline - _SKIP_REPING_NEAR_DEADLINE, deadline) is False  # exactly 60: not < 60
    assert _should_skip_reping(deadline - (_SKIP_REPING_NEAR_DEADLINE - 1), deadline) is True


async def test_re_ping_fires_each_cadence_until_near_deadline_then_skips():
    # give_up=120, cadence=15: re-pings land at t=15,30,45,60 (remaining 105..60,
    # never < 60), then the t=75 tick has remaining 45 < 60 → skip+return.
    daemon, fc = _clock_daemon(re_ping_every_seconds=15)
    writer = await _hello_and_get_writer(daemon)
    pending = _insert_pending(daemon, writer, give_up_after_seconds=120, tag="rp01")
    daemon._transport.notify.reset_mock()
    await daemon._re_ping_loop(pending)
    bodies = [c.args[0] for c in daemon._transport.notify.await_args_list]
    assert len(bodies) == 4
    assert all(b.startswith("Re: rp01 — still waiting") for b in bodies)
    assert fc.now == 75


async def test_re_ping_send_failure_non_fatal(caplog):
    import logging
    daemon, fc = _clock_daemon(re_ping_every_seconds=15)
    daemon._transport.notify = AsyncMock(side_effect=RuntimeError("boom"))
    writer = await _hello_and_get_writer(daemon)
    pending = _insert_pending(daemon, writer, give_up_after_seconds=120, tag="rp02")
    with caplog.at_level(logging.WARNING, logger="confer.daemon.core"):
        await daemon._re_ping_loop(pending)
    # The loop logged each failure and kept going; the ask is still pending.
    assert pending.request_id in daemon._pending_asks
    assert any("re-ping send failed" in r.getMessage() for r in caplog.records)


async def test_re_ping_loop_cancelled_returns_cleanly():
    daemon = Daemon(transport=_mocked_transport(), re_ping_every_seconds=10)
    writer, pending = await _register_ask(daemon, give_up_after_seconds=60)
    pending.re_ping_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending.re_ping_task
    await daemon._handle_ask_cancel(pending.request_id)


async def test_timeout_loop_cancelled_returns_cleanly():
    daemon = _make_daemon()
    writer, pending = await _register_ask(daemon, give_up_after_seconds=60)
    pending.timeout_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending.timeout_task
    await daemon._handle_ask_cancel(pending.request_id)


async def test_timeout_loop_no_op_when_already_resolved():
    daemon, fc = _clock_daemon()
    writer = await _hello_and_get_writer(daemon)
    pending = _insert_pending(daemon, writer, give_up_after_seconds=30, tag="no01")
    daemon._pending_asks.pop(pending.request_id)  # resolved before the timeout fires
    await daemon._timeout_loop(pending)
    assert not any(isinstance(m, AskTimeout) for m in _written_messages(writer))


async def test_timeout_loop_handles_none_re_ping_task():
    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon)
    pending = _PendingAsk(
        request_id="r-manual", label="confer/main", question="q?",
        on_timeout="use_best_judgment", give_up_after_seconds=0,
        started_at=time.monotonic(), writer=writer, tag="zzzz", re_ping_task=None,
    )
    daemon._pending_asks["r-manual"] = pending
    await daemon._timeout_loop(pending)
    assert "r-manual" not in daemon._pending_asks
    assert any(isinstance(m, AskTimeout) for m in _written_messages(writer))


async def test_cancel_ask_tasks_handles_none_and_done():
    daemon = _make_daemon()
    pending = _PendingAsk(
        request_id="r1", label="x", question="?", on_timeout="use_best_judgment",
        give_up_after_seconds=60, started_at=time.monotonic(), writer=_writer_mock(),
        tag="zzzz", re_ping_task=None, timeout_task=None,
    )
    await daemon._cancel_ask_tasks(pending)

    async def done():
        return None
    t = asyncio.create_task(done())
    await t
    pending.timeout_task = t
    await daemon._cancel_ask_tasks(pending)


# ─── deliver-by-tag race ────────────────────────────────────────────────────


async def test_deliver_by_tag_enqueues_late_reply_when_ask_gone():
    daemon = _make_daemon()
    await daemon._deliver_reply_by_tag("k3qp", "late content", "confer/main")
    q = list(daemon._queues["confer/main"])
    assert len(q) == 1
    assert q[0].source == "late_reply"
    assert q[0].tag == "k3qp"
    assert q[0].content == "late content"


# ─── routing through _dispatch (HELLO-exempt CLI + protocol path) ───────────


async def test_ask_begin_requires_hello():
    daemon = _make_daemon()
    writer = _writer_mock()
    await daemon._dispatch(
        AskBegin(request_id="r1", question="q?", give_up_after_seconds=60,
                 on_timeout="use_best_judgment"),
        writer, client_label=None,
    )
    assert any(
        isinstance(m, Error) and m.code == "hello_required"
        for m in _written_messages(writer)
    )


async def test_ask_cancel_through_dispatch():
    daemon = _make_daemon()
    writer, pending = await _register_ask(daemon)
    await daemon._dispatch(AskCancel(request_id=pending.request_id), writer, "confer/main")
    assert pending.request_id not in daemon._pending_asks


async def test_ask_begin_through_dispatch():
    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon)
    await daemon._dispatch(
        AskBegin(request_id="rf", question="q?", give_up_after_seconds=60,
                 on_timeout="use_best_judgment"),
        writer, "confer/main",
    )
    assert "rf" in daemon._pending_asks
    await daemon._handle_ask_cancel("rf")


# ─── CLI inject path (F-A: closing DM on CLI-resolve) ───────────────────────


async def test_inject_delivered_sends_cli_answered_closing_dm():
    daemon = _make_daemon()
    writer, pending = await _register_ask(daemon)
    tag = pending.tag
    cli_writer = _writer_mock()
    await daemon._handle_inject("cli-r", "yes go", cli_writer)
    # Agent got the reply.
    assert any(isinstance(m, AskReply) for m in _written_messages(writer))
    # CLI got the InjectResult.
    result = next(m for m in _written_messages(cli_writer) if isinstance(m, InjectResult))
    assert result.outcome == "delivered"
    # And a Discord closing DM was sent (F-A fix).
    bodies = [c.args[0] for c in daemon._transport.notify.await_args_list]
    assert f"Re: {tag} — answered from the laptop." in bodies


async def test_inject_bounced_no_discord_dm():
    daemon = _make_daemon()
    cli_writer = _writer_mock()
    await daemon._handle_inject("cli-r", "anyone?", cli_writer)
    result = next(m for m in _written_messages(cli_writer) if isinstance(m, InjectResult))
    assert result.outcome == "bounced"
    daemon._transport.notify.assert_not_awaited()


async def test_inject_broadcast():
    daemon = _make_daemon()
    daemon._clients["confer/main"] = _Client(label="confer/main", writer=_writer_mock())
    cli_writer = _writer_mock()
    await daemon._handle_inject("cli-r", "everyone stop", cli_writer)
    result = next(m for m in _written_messages(cli_writer) if isinstance(m, InjectResult))
    assert result.outcome == "broadcast"
    assert list(daemon._queues["confer/main"])[0].source == "broadcast"


async def test_inject_notify_reply_outcome():
    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon, "confer/main")
    await daemon._handle_notify(
        Notify(request_id="n1", message="done"), writer, "confer/main"
    )
    tag = next(iter(daemon._notify_threads))
    cli_writer = _writer_mock()
    await daemon._handle_inject("cli-r", f"re {tag} roll back", cli_writer)
    result = next(m for m in _written_messages(cli_writer) if isinstance(m, InjectResult))
    assert result.outcome == "queued_notify_reply"


async def test_inject_concierge_outcome():
    daemon = _make_daemon()
    cli_writer = _writer_mock()
    await daemon._handle_inject("cli-r", ".threads", cli_writer)
    result = next(m for m in _written_messages(cli_writer) if isinstance(m, InjectResult))
    assert result.outcome == "concierge"


async def test_inject_ambiguous_outcome():
    daemon = _make_daemon()
    w1, p1 = await _register_ask(daemon, request_id="r1", label="confer/main")
    w2 = await _hello_and_get_writer(daemon, label="myapp/feat")
    await daemon._handle_ask_begin(
        AskBegin(request_id="r2", question="merge?", give_up_after_seconds=60,
                 on_timeout="use_best_judgment"),
        w2, "myapp/feat",
    )
    cli_writer = _writer_mock()
    await daemon._handle_inject("cli-r", "hello", cli_writer)
    result = next(m for m in _written_messages(cli_writer) if isinstance(m, InjectResult))
    assert result.outcome == "ambiguous"
    await daemon._handle_ask_cancel("r1")
    await daemon._handle_ask_cancel("r2")


async def test_inject_through_dispatch_hello_exempt():
    daemon = _make_daemon()
    writer = _writer_mock()
    await daemon._dispatch(Inject(request_id="r1", content="hi"), writer, None)
    sent = _written_messages(writer)
    assert not any(isinstance(m, Error) and m.code == "hello_required" for m in sent)
    assert any(isinstance(m, InjectResult) for m in sent)


# ─── confer list ─────────────────────────────────────────────────────────────


async def test_list_asks_empty():
    daemon = _make_daemon()
    writer = _writer_mock()
    await daemon._handle_list_asks("r1", writer)
    result = next(m for m in _written_messages(writer) if isinstance(m, ListAsksResult))
    assert result.count == 0
    assert "No pending asks" in result.formatted


async def test_list_asks_shows_tags_newest_first():
    daemon = _make_daemon()
    w1, p1 = await _register_ask(daemon, request_id="r1", question="rebase?",
                                 label="confer/main")
    w2 = await _hello_and_get_writer(daemon, label="myapp/feat")
    await daemon._handle_ask_begin(
        AskBegin(request_id="r2", question="drop table?", give_up_after_seconds=60,
                 on_timeout="abort"),
        w2, "myapp/feat",
    )
    p2 = daemon._pending_asks["r2"]
    cli_writer = _writer_mock()
    await daemon._handle_list_asks("r", cli_writer)
    result = next(m for m in _written_messages(cli_writer) if isinstance(m, ListAsksResult))
    assert result.count == 2
    assert p1.tag in result.formatted
    assert p2.tag in result.formatted
    lines = result.formatted.splitlines()
    feat_idx = next(i for i, ln in enumerate(lines) if "myapp/feat" in ln)
    main_idx = next(i for i, ln in enumerate(lines) if "confer/main" in ln)
    assert feat_idx < main_idx
    await daemon._handle_ask_cancel("r1")
    await daemon._handle_ask_cancel("r2")


async def test_list_asks_through_dispatch_hello_exempt():
    daemon = _make_daemon()
    writer = _writer_mock()
    await daemon._dispatch(ListAsks(request_id="r1"), writer, None)
    sent = _written_messages(writer)
    assert not any(isinstance(m, Error) and m.code == "hello_required" for m in sent)
    assert any(isinstance(m, ListAsksResult) for m in sent)


# ─── helpers ─────────────────────────────────────────────────────────────────


async def test_send_dm_best_effort_logs_on_exception(caplog):
    import logging
    daemon = _make_daemon()
    daemon._transport.notify = AsyncMock(side_effect=RuntimeError("boom"))
    with caplog.at_level(logging.WARNING, logger="confer.daemon.core"):
        await daemon._send_dm_best_effort("hi")
    assert any("daemon DM send raised" in r.getMessage() for r in caplog.records)


async def test_send_dm_best_effort_logs_on_failure_sentinel(caplog):
    import logging
    daemon = _make_daemon()
    daemon._transport.notify = AsyncMock(return_value=f"{FAILURE_PREFIX}x>")
    with caplog.at_level(logging.WARNING, logger="confer.daemon.core"):
        await daemon._send_dm_best_effort("hi")
    assert any("daemon DM send failed" in r.getMessage() for r in caplog.records)


def test_closing_dm_text_all_reasons():
    assert "best judgment" in _closing_dm_text("use_best_judgment", "k3qp")
    assert "surface task state" in _closing_dm_text("abort", "k3qp")
    assert "withdrawn" in _closing_dm_text("withdrawn", "k3qp")
    assert "lost contact" in _closing_dm_text("lost_contact", "k3qp")
    assert "answered from the laptop" in _closing_dm_text("cli_answered", "k3qp")
    assert "k3qp" in _closing_dm_text("use_best_judgment", "k3qp")


def test_make_thread_tag_is_4_base32_chars():
    from confer.daemon.core import _make_thread_tag
    tag = _make_thread_tag()
    assert len(tag) == 4
    assert all(c in "abcdefghijklmnopqrstuvwxyz234567" for c in tag)


# ─── piggyback hint (pb7nqm4x) ──────────────────────────────────────────────


async def test_notify_info_appends_pending_hint_when_queue_nonempty():
    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon, "confer/main")
    daemon._enqueue_message("confer/main", "earlier broadcast", source="broadcast", tag=None)
    await daemon._handle_notify(
        Notify(request_id="n1", message="build done"), writer, "confer/main"
    )
    nr = next(m for m in _written_messages(writer) if isinstance(m, NotifyResult))
    assert "1 message waiting — call check_messages" in nr.info


async def test_notify_info_no_hint_when_queue_empty():
    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon, "confer/main")
    await daemon._handle_notify(
        Notify(request_id="n1", message="build done"), writer, "confer/main"
    )
    nr = next(m for m in _written_messages(writer) if isinstance(m, NotifyResult))
    assert "waiting" not in nr.info


async def test_notify_failure_status_skips_hint():
    daemon = _make_daemon()
    daemon._transport.notify = AsyncMock(return_value=f"{FAILURE_PREFIX}boom>")
    writer = await _hello_and_get_writer(daemon, "confer/main")
    daemon._enqueue_message("confer/main", "x", source="broadcast", tag=None)
    await daemon._handle_notify(
        Notify(request_id="n1", message="build done"), writer, "confer/main"
    )
    nr = next(m for m in _written_messages(writer) if isinstance(m, NotifyResult))
    assert nr.status == "failed"
    assert "waiting" not in nr.info


async def test_ask_reply_carries_pending_count():
    daemon = _make_daemon()
    writer, pending = await _register_ask(daemon)
    # A broadcast arrived for this label while the ask was open.
    daemon._enqueue_message("confer/main", "stop", source="broadcast", tag=None)
    await daemon._dispatch_user_message(f"re {pending.tag} ok")
    reply = next(m for m in _written_messages(writer) if isinstance(m, AskReply))
    assert reply.pending_count == 1


async def test_ask_timeout_carries_pending_count():
    daemon, fc = _clock_daemon()
    writer = await _hello_and_get_writer(daemon)
    pending = _insert_pending(daemon, writer, give_up_after_seconds=30, tag="pc01")
    daemon._enqueue_message("confer/main", "stop", source="broadcast", tag=None)
    await daemon._timeout_loop(pending)
    to = next(m for m in _written_messages(writer) if isinstance(m, AskTimeout))
    assert to.pending_count == 1


async def test_every_route_and_act_outcome_is_declared_in_inject_literal():
    # TST-F2 guard: enumerate every outcome _route_and_act emits and assert each
    # is a declared InjectResult.outcome Literal member (and the dropped
    # "queued_labeled" is gone). Pins the protocol/daemon/CLI contract.
    from typing import get_args, get_type_hints
    from confer.protocol import InjectResult

    allowed = set(get_args(get_type_hints(InjectResult)["outcome"]))
    outcomes = set()

    d = _make_daemon()
    outcomes.add((await d._route_and_act("."))[0])  # concierge

    d = _make_daemon()
    outcomes.add((await d._route_and_act("hello"))[0])  # bounced (no agents)

    d = _make_daemon()
    d._clients["confer/main"] = _Client(label="confer/main", writer=_writer_mock())
    outcomes.add((await d._route_and_act("everyone stop"))[0])  # broadcast

    d = _make_daemon()
    await _register_ask(d, request_id="r1", label="confer/main")
    w2 = await _hello_and_get_writer(d, "myapp/feat")
    await d._handle_ask_begin(
        AskBegin(request_id="r2", question="q", give_up_after_seconds=60,
                 on_timeout="use_best_judgment"), w2, "myapp/feat")
    outcomes.add((await d._route_and_act("hello"))[0])  # ambiguous
    await d._handle_ask_cancel("r1")
    await d._handle_ask_cancel("r2")

    d = _make_daemon()
    _, p = await _register_ask(d, request_id="r3", label="confer/main")
    outcomes.add((await d._route_and_act(f"re {p.tag} yes"))[0])  # delivered

    d = _make_daemon()
    w = await _hello_and_get_writer(d, "confer/main")
    await d._handle_notify(Notify(request_id="n1", message="done"), w, "confer/main")
    tag = next(iter(d._notify_threads))
    outcomes.add((await d._route_and_act(f"re {tag} roll back"))[0])  # queued_notify_reply

    assert outcomes == {
        "concierge", "bounced", "broadcast", "ambiguous", "delivered",
        "queued_notify_reply",
    }
    assert outcomes <= allowed
    assert "queued_labeled" not in allowed


def test_pending_count_and_hint_helpers():
    daemon = _make_daemon()
    assert daemon._pending_count("nope") == 0
    assert daemon._pending_hint("nope") == ""
    daemon._enqueue_message("L", "a", source="broadcast", tag=None)
    daemon._enqueue_message("L", "b", source="broadcast", tag=None)
    assert daemon._pending_count("L") == 2
    assert "2 messages waiting" in daemon._pending_hint("L")
    daemon._queues["L"].clear()
    daemon._enqueue_message("L", "c", source="broadcast", tag=None)
    assert "1 message waiting" in daemon._pending_hint("L")


# ─── interaction audit log (dg7vnq4x) ───────────────────────────────────────


def _audit_records(caplog):
    return [r for r in caplog.records if r.levelname == "INFO"]


async def test_audit_log_notify(caplog):
    import logging

    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon)
    with caplog.at_level(logging.INFO, logger="confer.daemon.core"):
        await daemon._handle_notify(
            Notify(request_id="r", message="hi"), writer, "confer/main"
        )
    tag = next(iter(daemon._notify_threads))
    assert any(
        m == f"notify: label=confer/main tag={tag} status=ok"
        for m in (r.getMessage() for r in _audit_records(caplog))
    )


async def test_audit_log_notify_failed_status(caplog):
    import logging

    daemon = _make_daemon()
    daemon._transport.notify = AsyncMock(
        return_value=f"{FAILURE_PREFIX}boom>"
    )
    writer = await _hello_and_get_writer(daemon)
    with caplog.at_level(logging.INFO, logger="confer.daemon.core"):
        await daemon._handle_notify(
            Notify(request_id="r", message="hi"), writer, "confer/main"
        )
    assert any(
        "notify: label=confer/main" in m and "status=failed" in m
        for m in (r.getMessage() for r in _audit_records(caplog))
    )


async def test_audit_log_ask_begin(caplog):
    import logging

    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon)
    with caplog.at_level(logging.INFO, logger="confer.daemon.core"):
        _, pending = await _register_ask(daemon, give_up_after_seconds=120)
    assert any(
        m == (
            f"ask begin: label=confer/main tag={pending.tag} "
            f"give_up=120s on_timeout=use_best_judgment"
        )
        for m in (r.getMessage() for r in _audit_records(caplog))
    )
    await daemon._handle_ask_cancel(pending.request_id)


async def test_audit_log_route_outcome_delivered(caplog):
    import logging

    daemon = _make_daemon()
    writer, pending = await _register_ask(daemon)
    with caplog.at_level(logging.INFO, logger="confer.daemon.core"):
        await daemon._dispatch_user_message("rebase please")
    assert any(
        m == "routed user message: outcome=delivered"
        for m in (r.getMessage() for r in _audit_records(caplog))
    )


async def test_audit_log_route_outcome_broadcast(caplog):
    import logging

    daemon = _make_daemon()
    daemon._clients["confer/main"] = _Client(
        label="confer/main", writer=_writer_mock()
    )
    with caplog.at_level(logging.INFO, logger="confer.daemon.core"):
        await daemon._dispatch_user_message("everyone stop")
    assert any(
        m == "routed user message: outcome=broadcast"
        for m in (r.getMessage() for r in _audit_records(caplog))
    )


async def test_audit_log_ask_timeout(caplog):
    import logging

    daemon, fc = _clock_daemon()
    writer = await _hello_and_get_writer(daemon)
    pending = _insert_pending(
        daemon, writer, give_up_after_seconds=30, tag="tm01", on_timeout="abort"
    )
    with caplog.at_level(logging.INFO, logger="confer.daemon.core"):
        await daemon._timeout_loop(pending)
    assert any(
        m == "ask timeout: label=confer/main tag=tm01 disposition=abort"
        for m in (r.getMessage() for r in _audit_records(caplog))
    )


async def test_audit_log_ask_withdrawn(caplog):
    import logging

    daemon = _make_daemon()
    writer, pending = await _register_ask(daemon)
    with caplog.at_level(logging.INFO, logger="confer.daemon.core"):
        await daemon._handle_ask_cancel(pending.request_id)
    assert any(
        m == f"ask withdrawn: label=confer/main tag={pending.tag}"
        for m in (r.getMessage() for r in _audit_records(caplog))
    )


async def test_audit_log_ask_dropped_on_disconnect(caplog):
    import logging

    daemon = _make_daemon()
    writer, pending = await _register_ask(daemon)
    with caplog.at_level(logging.INFO, logger="confer.daemon.core"):
        await daemon._drop_asks_for_writer(writer, "confer/main")
    assert any(
        m == (
            f"ask dropped (lost contact): label=confer/main tag={pending.tag}"
        )
        for m in (r.getMessage() for r in _audit_records(caplog))
    )


async def test_audit_log_check_messages(caplog):
    import logging

    daemon = _make_daemon()
    writer = await _hello_and_get_writer(daemon)
    daemon._enqueue_message("confer/main", "hi", source="broadcast", tag=None)
    daemon._enqueue_message("confer/main", "ho", source="broadcast", tag=None)
    with caplog.at_level(logging.INFO, logger="confer.daemon.core"):
        await daemon._handle_check_messages("r", "confer/main", writer)
    assert any(
        m == "check_messages: label=confer/main count=2"
        for m in (r.getMessage() for r in _audit_records(caplog))
    )
