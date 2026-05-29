import asyncio
import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from confer.daemon import __main__ as cli
from confer.protocol import Error, Hello, StatusResult, encode


def fake_async_run(result):
    """Mock for asyncio.run that closes the passed-in coroutine cleanly
    (no RuntimeWarning) and returns the given result."""
    def _fake(coro):
        coro.close()
        return result
    return _fake


def test_main_no_subcommand_runs_daemon():
    with patch.object(cli, "_cmd_run", return_value=0) as mock_run:
        assert cli.main([]) == 0
    mock_run.assert_called_once()


def test_main_stop_subcommand():
    with patch.object(cli, "_cmd_stop", return_value=0) as mock_stop:
        assert cli.main(["stop"]) == 0
    mock_stop.assert_called_once()


def test_main_status_subcommand():
    with patch.object(cli, "_cmd_status", return_value=0) as mock_status:
        assert cli.main(["status"]) == 0
    mock_status.assert_called_once()


def test_cmd_run_configures_logging_and_runs_daemon(paths):
    """asyncio.run is mocked via fake_async_run so the coroutine returned
    by _run_daemon() is closed cleanly (no RuntimeWarning)."""
    with patch.object(cli, "_configure_logging") as mock_cfg, patch.object(
        cli.asyncio, "run", side_effect=fake_async_run(None)
    ) as mock_run:
        assert cli._cmd_run() == 0
    mock_cfg.assert_called_once()
    mock_run.assert_called_once()


async def test_run_daemon_loads_settings_and_wires_token_into_transport(paths):
    """Asserts that Settings fields flow through to DiscordTransport so a
    field rename in Settings would surface as a test failure (S9). Also
    verifies that on_user_message is wired through to the daemon's
    dispatcher per On Message Handler Wiring (m4kpvn7q)."""
    fake_settings = MagicMock(
        discord_bot_token="real-tok",
        confer_user_id=98765,
        re_ping_every_seconds=900,
    )
    fake_transport = MagicMock()
    fake_daemon = MagicMock()
    fake_daemon.serve = AsyncMock()
    fake_daemon._dispatch_user_message = AsyncMock()

    with patch.object(
        cli.Settings, "load", return_value=fake_settings
    ), patch.object(
        cli, "DiscordTransport", return_value=fake_transport
    ) as mock_transport_cls, patch.object(cli, "Daemon", return_value=fake_daemon) as mock_daemon_cls:
        await cli._run_daemon()

    call_kwargs = mock_transport_cls.call_args.kwargs
    assert call_kwargs["token"] == "real-tok"
    assert call_kwargs["user_id"] == 98765
    assert "on_user_message" in call_kwargs
    # Verify the wired-up closure actually calls into the daemon's dispatcher.
    await call_kwargs["on_user_message"]("hello from user")
    fake_daemon._dispatch_user_message.assert_awaited_once_with("hello from user")

    mock_daemon_cls.assert_called_once_with(
        transport=fake_transport, re_ping_every_seconds=900
    )
    fake_daemon.serve.assert_awaited_once_with(paths["sock"], paths["pid"])


async def test_run_daemon_on_user_message_is_noop_before_daemon_assignment(paths):
    """The closure handles the race where on_user_message fires before the
    daemon reference is assigned — must not crash."""
    fake_settings = MagicMock(
        discord_bot_token="t",
        confer_user_id=1,
        re_ping_every_seconds=900,
    )
    fake_transport = MagicMock()
    fake_daemon = MagicMock()
    fake_daemon.serve = AsyncMock()
    captured_callback: list = []

    def capture_transport(**kwargs):
        captured_callback.append(kwargs["on_user_message"])
        return fake_transport

    with patch.object(
        cli.Settings, "load", return_value=fake_settings
    ), patch.object(
        cli, "DiscordTransport", side_effect=capture_transport
    ), patch.object(cli, "Daemon", return_value=fake_daemon):
        # Patch serve to invoke the callback BEFORE the daemon-ref is
        # populated. Actually the assignment happens before serve() in the
        # current code, so we exercise the no-daemon-yet branch by directly
        # calling the captured callback while clearing daemon_ref.
        await cli._run_daemon()

    # After _run_daemon returns, daemon_ref has been assigned and cleared
    # from the enclosing scope. Directly invoke captured callback against a
    # fresh closure scenario by patching the callback's __closure__.
    callback = captured_callback[0]
    # Inspect the closure cell: it should reference daemon_ref dict.
    closure_vars = {
        name: cell.cell_contents
        for name, cell in zip(callback.__code__.co_freevars, callback.__closure__)
    }
    # If we artificially empty the dict, the callback should be a no-op.
    closure_vars["daemon_ref"].clear()
    await callback("anything")  # must not raise


def test_configure_logging_creates_directory(paths):
    cli._configure_logging()
    assert paths["log"].parent.exists()


def _stub_live_pid(monkeypatch, pid: int) -> None:
    """Make _read_live_pid return the given PID regardless of /proc state."""
    monkeypatch.setattr(cli, "_read_live_pid", lambda _pf: pid)


# ───── _read_live_pid ──────────────────────────────────────────────────────

def test_read_live_pid_returns_pid_for_running_confer_daemon_process(tmp_path, monkeypatch):
    pf = tmp_path / "confer.pid"
    pf.write_text(str(os.getpid()))
    # Fake /proc/<pid>/cmdline lookup
    fake_cmdline = b"confer-daemon\x00"
    monkeypatch.setattr(
        cli.Path, "read_bytes", lambda self: fake_cmdline if "cmdline" in str(self) else b""
    )
    assert cli._read_live_pid(pf) == os.getpid()


def test_read_live_pid_returns_none_when_file_missing(tmp_path):
    assert cli._read_live_pid(tmp_path / "absent.pid") is None


def test_read_live_pid_returns_none_when_pid_malformed(tmp_path):
    pf = tmp_path / "confer.pid"
    pf.write_text("not a number")
    assert cli._read_live_pid(pf) is None


def test_read_live_pid_returns_none_when_proc_entry_missing(tmp_path, monkeypatch):
    pf = tmp_path / "confer.pid"
    pf.write_text("99999")

    def raise_fnfe(self):
        raise FileNotFoundError(str(self))

    monkeypatch.setattr(cli.Path, "read_bytes", raise_fnfe)
    assert cli._read_live_pid(pf) is None


def test_read_live_pid_returns_none_when_cmdline_is_a_different_program(tmp_path, monkeypatch):
    pf = tmp_path / "confer.pid"
    pf.write_text(str(os.getpid()))
    monkeypatch.setattr(cli.Path, "read_bytes", lambda self: b"vim\x00main.py\x00")
    assert cli._read_live_pid(pf) is None


# ───── _cmd_stop ───────────────────────────────────────────────────────────

def test_cmd_stop_returns_0_when_no_pid_file(paths, capsys):
    assert cli._cmd_stop() == 0
    err = capsys.readouterr().err
    assert "nothing to stop" in err


def test_cmd_stop_treats_malformed_pid_file_as_stale_and_removes_it(paths, capsys):
    paths["pid"].write_text("not a number")
    assert cli._cmd_stop() == 0
    out = capsys.readouterr().out
    assert "Stale PID file" in out
    assert not paths["pid"].exists()


def test_cmd_stop_treats_dead_pid_as_stale_and_removes_pid_file(paths, capsys, monkeypatch):
    paths["pid"].write_text("99999")
    # _read_live_pid returns None because /proc/99999 doesn't exist
    assert cli._cmd_stop() == 0
    out = capsys.readouterr().out
    assert "Stale PID file" in out
    assert not paths["pid"].exists()


def test_cmd_stop_handles_kill_process_lookup_error(paths, capsys, monkeypatch):
    paths["pid"].write_text("12345")
    _stub_live_pid(monkeypatch, 12345)
    with patch.object(cli.os, "kill", side_effect=ProcessLookupError):
        assert cli._cmd_stop() == 0
    out = capsys.readouterr().out
    assert "stale" in out.lower()
    assert not paths["pid"].exists()


def test_cmd_stop_returns_0_when_daemon_exits_cleanly(paths, capsys, monkeypatch):
    """The daemon's finally: clause removes the PID file on shutdown.
    We simulate that by removing it pre-emptively, so the polling loop
    sees the file gone regardless of internal poll/sleep order — robust
    to refactoring _cmd_stop's loop (TM-H3 finding)."""
    paths["pid"].write_text("12345")
    _stub_live_pid(monkeypatch, 12345)
    paths["pid"].unlink()  # simulate the daemon already cleaning up

    with patch.object(cli.os, "kill") as mock_kill, patch.object(
        cli.time, "sleep"
    ):
        assert cli._cmd_stop() == 0
    mock_kill.assert_called_once_with(12345, signal.SIGTERM)
    assert "stopped" in capsys.readouterr().out


def test_cmd_stop_returns_1_when_daemon_does_not_exit(paths, capsys, monkeypatch):
    paths["pid"].write_text("12345")
    _stub_live_pid(monkeypatch, 12345)
    with patch.object(cli.os, "kill"), patch.object(cli.time, "sleep"):
        assert cli._cmd_stop() == 1
    assert "did not exit" in capsys.readouterr().err


# ───── _cmd_status ─────────────────────────────────────────────────────────

def test_cmd_status_returns_0_when_no_pid_file(paths, capsys):
    assert cli._cmd_status() == 0
    assert "No daemon running" in capsys.readouterr().out


def test_cmd_status_treats_malformed_pid_file_as_stale(paths, capsys):
    paths["pid"].write_text("xxx")
    assert cli._cmd_status() == 0
    out = capsys.readouterr().out
    assert "Stale PID file" in out


def test_cmd_status_treats_dead_pid_as_stale(paths, capsys):
    paths["pid"].write_text("99999")
    assert cli._cmd_status() == 0
    assert "Stale PID file" in capsys.readouterr().out


def test_cmd_status_returns_1_when_daemon_does_not_respond(paths, capsys, monkeypatch):
    paths["pid"].write_text("12345")
    _stub_live_pid(monkeypatch, 12345)
    with patch.object(cli.asyncio, "run", side_effect=fake_async_run(None)):
        assert cli._cmd_status() == 1
    assert "did not respond" in capsys.readouterr().err


def test_cmd_status_surfaces_errno_when_socket_unreachable(paths, capsys, monkeypatch):
    paths["pid"].write_text("12345")
    _stub_live_pid(monkeypatch, 12345)
    import errno
    err = ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")
    with patch.object(cli.asyncio, "run", side_effect=fake_async_run(err)):
        assert cli._cmd_status() == 1
    msg = capsys.readouterr().err
    assert "socket unreachable" in msg
    assert "Connection refused" in msg
    assert f"errno {errno.ECONNREFUSED}" in msg


def test_cmd_status_handles_oserror_with_no_errno(paths, capsys, monkeypatch):
    paths["pid"].write_text("12345")
    _stub_live_pid(monkeypatch, 12345)
    err = OSError("strange error")  # no errno
    with patch.object(cli.asyncio, "run", side_effect=fake_async_run(err)):
        assert cli._cmd_status() == 1
    assert "unknown errno" in capsys.readouterr().err


def test_cmd_status_prints_state_and_log_tail(paths, capsys, monkeypatch):
    paths["pid"].write_text("12345")
    _stub_live_pid(monkeypatch, 12345)
    paths["log"].write_text("line one\nline two\nline three\n")
    result = StatusResult(
        request_id="status",
        uptime_seconds=125.0,
        gateway_state="ready",
        clients=["confer/main", "myapp/main#a3f1"],
    )
    with patch.object(cli.asyncio, "run", side_effect=fake_async_run(result)):
        assert cli._cmd_status() == 0
    out = capsys.readouterr().out
    assert "PID: 12345" in out
    assert "Uptime: 2m 5s" in out
    assert "Gateway: ready" in out
    assert "confer/main" in out
    assert "myapp/main#a3f1" in out
    assert "line two" in out


def test_cmd_status_omits_log_section_when_log_file_missing(paths, capsys, monkeypatch):
    paths["pid"].write_text("12345")
    _stub_live_pid(monkeypatch, 12345)
    result = StatusResult(
        request_id="status",
        uptime_seconds=0.5,
        gateway_state="ready",
        clients=[],
    )
    with patch.object(cli.asyncio, "run", side_effect=fake_async_run(result)):
        assert cli._cmd_status() == 0
    out = capsys.readouterr().out
    assert "Recent log tail" not in out


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (5, "5s"),
        (65, "1m 5s"),
        (3725, "1h 2m 5s"),
    ],
)
def test_format_uptime(seconds, expected):
    assert cli._format_uptime(seconds) == expected


async def test_query_status_returns_oserror_when_socket_unreachable(paths):
    result = await cli._query_status()
    assert isinstance(result, OSError)
    assert result.errno is not None


async def test_query_status_returns_result_on_successful_response(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(cli, "socket_path", lambda: sock)

    fake_result = StatusResult(
        request_id="status",
        uptime_seconds=10.0,
        gateway_state="ready",
        clients=[],
    )

    async def handle(reader, writer):
        line = await reader.readline()
        assert line  # got the STATUS message
        writer.write(encode(fake_result))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(handle, path=str(sock))
    try:
        result = await cli._query_status()
    finally:
        server.close()
        await server.wait_closed()
    assert result == fake_result


async def test_query_status_returns_none_on_empty_response(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(cli, "socket_path", lambda: sock)

    async def handle(reader, writer):
        await reader.readline()
        # Close without sending anything
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(handle, path=str(sock))
    try:
        result = await cli._query_status()
    finally:
        server.close()
        await server.wait_closed()
    assert result is None


async def test_query_status_returns_none_on_unexpected_message_type(tmp_path, monkeypatch):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(cli, "socket_path", lambda: sock)

    async def handle(reader, writer):
        await reader.readline()
        writer.write(encode(Error(code="boom", message="boom")))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(handle, path=str(sock))
    try:
        result = await cli._query_status()
    finally:
        server.close()
        await server.wait_closed()
    assert result is None
