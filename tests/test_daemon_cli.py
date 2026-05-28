import asyncio
import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from confer.daemon import __main__ as cli
from confer.protocol import Error, Hello, StatusResult, encode


@pytest.fixture
def paths(tmp_path, monkeypatch):
    pid = tmp_path / "confer.pid"
    sock = tmp_path / "confer.sock"
    log = tmp_path / "daemon.log"
    monkeypatch.setattr(cli, "pid_file", lambda: pid)
    monkeypatch.setattr(cli, "socket_path", lambda: sock)
    monkeypatch.setattr(cli, "log_file", lambda: log)
    return {"pid": pid, "sock": sock, "log": log}


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
    with patch.object(cli, "_configure_logging") as mock_cfg, patch.object(
        cli.asyncio, "run"
    ) as mock_run:
        assert cli._cmd_run() == 0
    mock_cfg.assert_called_once()
    mock_run.assert_called_once()


async def test_run_daemon_loads_settings_constructs_transport_and_serves(paths):
    fake_settings = MagicMock(discord_bot_token="tok", confer_user_id=42)
    fake_transport = MagicMock()
    fake_daemon = MagicMock()
    fake_daemon.serve = AsyncMock()

    with patch.object(cli.Settings, "load", return_value=fake_settings), patch.object(
        cli, "DiscordTransport", return_value=fake_transport
    ), patch.object(cli, "Daemon", return_value=fake_daemon):
        await cli._run_daemon()

    fake_daemon.serve.assert_awaited_once_with(paths["sock"], paths["pid"])


def test_configure_logging_creates_directory(paths):
    cli._configure_logging()
    assert paths["log"].parent.exists()


def test_cmd_stop_returns_0_when_no_pid_file(paths, capsys):
    assert cli._cmd_stop() == 0
    err = capsys.readouterr().err
    assert "nothing to stop" in err


def test_cmd_stop_returns_1_on_malformed_pid_file(paths, capsys):
    paths["pid"].write_text("not a number")
    assert cli._cmd_stop() == 1
    assert "Malformed" in capsys.readouterr().err


def test_cmd_stop_returns_0_when_process_does_not_exist(paths, capsys):
    paths["pid"].write_text("99999")
    with patch.object(cli.os, "kill", side_effect=ProcessLookupError):
        assert cli._cmd_stop() == 0
    out = capsys.readouterr().out
    assert "stale" in out
    assert not paths["pid"].exists()


def test_cmd_stop_returns_0_when_daemon_exits_cleanly(paths, capsys):
    paths["pid"].write_text("12345")
    call_count = {"n": 0}

    def fake_sleep(_):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            paths["pid"].unlink()

    with patch.object(cli.os, "kill") as mock_kill, patch.object(
        cli.time, "sleep", side_effect=fake_sleep
    ):
        assert cli._cmd_stop() == 0
    mock_kill.assert_called_once_with(12345, signal.SIGTERM)
    assert "stopped" in capsys.readouterr().out


def test_cmd_stop_returns_1_when_daemon_does_not_exit(paths, capsys):
    paths["pid"].write_text("12345")
    with patch.object(cli.os, "kill"), patch.object(cli.time, "sleep"):
        assert cli._cmd_stop() == 1
    assert "did not exit" in capsys.readouterr().err


def test_cmd_status_returns_0_when_no_pid_file(paths, capsys):
    assert cli._cmd_status() == 0
    assert "No daemon running" in capsys.readouterr().out


def test_cmd_status_returns_1_on_malformed_pid_file(paths, capsys):
    paths["pid"].write_text("xxx")
    assert cli._cmd_status() == 1
    assert "Malformed" in capsys.readouterr().err


def test_cmd_status_returns_1_when_daemon_does_not_respond(paths, capsys):
    paths["pid"].write_text("12345")
    with patch.object(cli.asyncio, "run", return_value=None):
        assert cli._cmd_status() == 1
    assert "did not respond" in capsys.readouterr().err


def test_cmd_status_prints_state_and_log_tail(paths, capsys):
    paths["pid"].write_text("12345")
    paths["log"].write_text("line one\nline two\nline three\n")
    result = StatusResult(
        request_id="status",
        uptime_seconds=125.0,
        gateway_state="ready",
        clients=["confer/main", "myapp/main#a3f1"],
    )
    with patch.object(cli.asyncio, "run", return_value=result):
        assert cli._cmd_status() == 0
    out = capsys.readouterr().out
    assert "PID: 12345" in out
    assert "Uptime: 2m 5s" in out
    assert "Gateway: ready" in out
    assert "confer/main" in out
    assert "myapp/main#a3f1" in out
    assert "line two" in out


def test_cmd_status_omits_log_section_when_log_file_missing(paths, capsys):
    paths["pid"].write_text("12345")
    result = StatusResult(
        request_id="status",
        uptime_seconds=0.5,
        gateway_state="ready",
        clients=[],
    )
    with patch.object(cli.asyncio, "run", return_value=result):
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


async def test_query_status_returns_none_when_socket_unreachable(paths):
    result = await cli._query_status()
    assert result is None


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
