import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from confer import cli as cli_mod
from confer.cli import _build_parser, main
from confer.protocol import (
    Inject,
    InjectResult,
    ListAsks,
    ListAsksResult,
    decode,
    encode,
)


@asynccontextmanager
async def _fake_daemon(handler, sock_path: Path):
    server = await asyncio.start_unix_server(handler, path=str(sock_path))
    try:
        yield server
    finally:
        server.close()
        await server.wait_closed()


def test_parser_requires_subcommand():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_answer_requires_text():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["answer"])


def test_parser_list_parses():
    parser = _build_parser()
    args = parser.parse_args(["list"])
    assert args.cmd == "list"


def test_parser_answer_parses():
    parser = _build_parser()
    args = parser.parse_args(["answer", "yes please"])
    assert args.cmd == "answer"
    assert args.text == "yes please"


async def test_cmd_list_prints_formatted(tmp_path, monkeypatch, capsys):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(cli_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        msg = decode(await reader.readline())
        assert isinstance(msg, ListAsks)
        writer.write(encode(ListAsksResult(
            request_id=msg.request_id,
            formatted="2 pending ask(s):\n  1. [a] q1\n  2. [b] q2",
            count=2,
        )))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        rc = await cli_mod._cmd_list()
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 pending ask" in out


async def test_cmd_list_unexpected_response_exits_2(tmp_path, monkeypatch, capsys):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(cli_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        msg = decode(await reader.readline())
        # Reply with an InjectResult instead of ListAsksResult — mismatch.
        writer.write(encode(InjectResult(
            request_id=msg.request_id, outcome="delivered", detail="x",
        )))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        rc = await cli_mod._cmd_list()
    assert rc == 2
    err = capsys.readouterr().err
    assert "unexpected response" in err


async def test_cmd_answer_delivered_returns_0(tmp_path, monkeypatch, capsys):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(cli_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        msg = decode(await reader.readline())
        assert isinstance(msg, Inject)
        assert msg.content == "yes please"
        writer.write(encode(InjectResult(
            request_id=msg.request_id,
            outcome="delivered",
            detail="Delivered to confer/main.",
        )))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        rc = await cli_mod._cmd_answer("yes please")
    assert rc == 0
    assert "Delivered to confer/main." in capsys.readouterr().out


async def test_cmd_answer_bounced_returns_1(tmp_path, monkeypatch, capsys):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(cli_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        msg = decode(await reader.readline())
        writer.write(encode(InjectResult(
            request_id=msg.request_id,
            outcome="bounced",
            detail="No agent is connected.",
        )))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        rc = await cli_mod._cmd_answer("hi")
    assert rc == 1


async def test_cmd_answer_ambiguous_returns_1(tmp_path, monkeypatch, capsys):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(cli_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        msg = decode(await reader.readline())
        writer.write(encode(InjectResult(
            request_id=msg.request_id,
            outcome="ambiguous",
            detail="Multiple asks waiting...",
        )))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        rc = await cli_mod._cmd_answer("yes")
    assert rc == 1


async def test_cmd_answer_unexpected_response_exits_2(tmp_path, monkeypatch, capsys):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(cli_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        msg = decode(await reader.readline())
        writer.write(encode(ListAsksResult(
            request_id=msg.request_id, formatted="x", count=0,
        )))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        rc = await cli_mod._cmd_answer("hi")
    assert rc == 2


async def test_send_one_exits_2_when_socket_missing(tmp_path, monkeypatch, capsys):
    sock = tmp_path / "nonexistent.sock"
    monkeypatch.setattr(cli_mod, "socket_path", lambda: sock)

    with pytest.raises(SystemExit) as exc_info:
        await cli_mod._send_one(ListAsks(request_id="r1"))
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "cannot reach daemon" in err


async def test_send_one_exits_2_when_daemon_closes_before_response(tmp_path, monkeypatch, capsys):
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(cli_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        # Close immediately without responding.
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        with pytest.raises(SystemExit) as exc_info:
            await cli_mod._send_one(ListAsks(request_id="r1"))
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "daemon closed connection" in err


def test_main_list_dispatches(monkeypatch):
    called = []

    async def fake_cmd_list():
        called.append("list")
        return 0

    monkeypatch.setattr(cli_mod, "_cmd_list", fake_cmd_list)
    rc = main(["list"])
    assert rc == 0
    assert called == ["list"]


def test_main_answer_dispatches(monkeypatch):
    called = []

    async def fake_cmd_answer(text):
        called.append(("answer", text))
        return 0

    monkeypatch.setattr(cli_mod, "_cmd_answer", fake_cmd_answer)
    rc = main(["answer", "yes please"])
    assert rc == 0
    assert called == [("answer", "yes please")]
