import asyncio
import io
import json
import stat
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
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


@pytest.mark.parametrize(
    "outcome,expected_exit",
    [
        ("delivered", 0),
        ("queued_notify_reply", 0),
        ("broadcast", 0),
        ("bounced", 1),
        ("ambiguous", 1),
        ("concierge", 1),
    ],
)
async def test_cmd_answer_exit_code_per_daemon_outcome(tmp_path, monkeypatch, outcome, expected_exit):
    """TST-F4: every outcome the daemon can emit maps to a defined exit code,
    so a script branching on `confer answer` status behaves correctly."""
    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(cli_mod, "socket_path", lambda: sock)

    async def handler(reader, writer):
        msg = decode(await reader.readline())
        assert isinstance(msg, Inject)
        writer.write(encode(InjectResult(
            request_id=msg.request_id, outcome=outcome, detail="x",
        )))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with _fake_daemon(handler, sock):
        rc = await cli_mod._cmd_answer("anything")
    assert rc == expected_exit


# ─── confer setup (st7nqkp4) ────────────────────────────────────────────────


def _scripted_input(*responses):
    """Build a fake input() that returns the given responses in order."""
    it = iter(responses)
    return lambda prompt="": next(it)


def test_parser_setup_parses_defaults():
    args = _build_parser().parse_args(["setup"])
    assert args.cmd == "setup"
    assert args.token is None
    assert args.user_id is None
    assert args.force is False
    assert args.register is True  # --no-register defaults to register=True


def test_parser_setup_parses_flags():
    args = _build_parser().parse_args(
        ["setup", "--token", "T", "--user-id", "42", "--force", "--no-register"]
    )
    assert args.token == "T"
    assert args.user_id == "42"
    assert args.force is True
    assert args.register is False


def test_toml_escape_handles_quote_and_backslash():
    assert cli_mod._toml_escape(r'a"b\c') == r'a\"b\\c'


def _point_config_at(monkeypatch, tmp_path):
    path = tmp_path / "confer" / "config.toml"
    monkeypatch.setattr(cli_mod, "default_config_path", lambda: path)
    return path


def test_setup_refuses_to_overwrite_without_force(tmp_path, monkeypatch, capsys):
    path = _point_config_at(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("discord_bot_token = \"old\"\nconfer_user_id = 1\n")

    rc = cli_mod._cmd_setup(token="new", user_id="2", force=False, register=False)
    assert rc == 1
    assert "refusing to overwrite" in capsys.readouterr().err
    # Untouched.
    assert "old" in path.read_text()


def test_setup_writes_config_0600_and_skips_register(tmp_path, monkeypatch, capsys):
    path = _point_config_at(monkeypatch, tmp_path)

    rc = cli_mod._cmd_setup(
        token="bot.tok", user_id="123456789", force=False, register=False
    )
    assert rc == 0
    body = path.read_text()
    assert 'discord_bot_token = "bot.tok"' in body
    assert "confer_user_id = 123456789" in body
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    out = capsys.readouterr().out
    assert "Skipped Claude registration" in out
    assert "Setup complete" in out


def test_setup_prompts_when_flags_omitted(tmp_path, monkeypatch, capsys):
    path = _point_config_at(monkeypatch, tmp_path)

    rc = cli_mod._cmd_setup(
        token=None,
        user_id=None,
        force=False,
        register=False,
        input_fn=_scripted_input("prompted.tok", "987654321"),
    )
    assert rc == 0
    body = path.read_text()
    assert 'discord_bot_token = "prompted.tok"' in body
    assert "confer_user_id = 987654321" in body


def test_setup_force_overwrites_existing(tmp_path, monkeypatch):
    path = _point_config_at(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("discord_bot_token = \"old\"\nconfer_user_id = 1\n")

    rc = cli_mod._cmd_setup(token="fresh", user_id="5", force=True, register=False)
    assert rc == 0
    assert "fresh" in path.read_text()


def test_setup_empty_token_errors(tmp_path, monkeypatch, capsys):
    _point_config_at(monkeypatch, tmp_path)
    rc = cli_mod._cmd_setup(token="", user_id="1", force=False, register=False)
    assert rc == 1
    assert "non-empty Discord bot token" in capsys.readouterr().err


def test_setup_nondigit_user_id_errors(tmp_path, monkeypatch, capsys):
    _point_config_at(monkeypatch, tmp_path)
    rc = cli_mod._cmd_setup(token="t", user_id="abc", force=False, register=False)
    assert rc == 1
    assert "positive integer snowflake" in capsys.readouterr().err


def test_setup_zero_user_id_errors(tmp_path, monkeypatch, capsys):
    _point_config_at(monkeypatch, tmp_path)
    rc = cli_mod._cmd_setup(token="t", user_id="0", force=False, register=False)
    assert rc == 1
    assert "positive integer snowflake" in capsys.readouterr().err


def test_setup_register_true_when_claude_missing(tmp_path, monkeypatch, capsys):
    _point_config_at(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_mod.shutil, "which", lambda _: None)

    rc = cli_mod._cmd_setup(token="t", user_id="1", force=False, register=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "not found on PATH" in out
    assert "claude mcp add confer -- confer-server" in out


def test_register_with_claude_success(monkeypatch, capsys):
    monkeypatch.setattr(cli_mod.shutil, "which", lambda _: "/usr/bin/claude")
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
    cli_mod._register_with_claude()
    assert calls == [["claude", "mcp", "add", "confer", "--", "confer-server"]]
    assert "Registered confer with Claude Code" in capsys.readouterr().out


def test_register_with_claude_nonzero_exit_warns(monkeypatch, capsys):
    monkeypatch.setattr(cli_mod.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        cli_mod.subprocess, "run", lambda cmd: SimpleNamespace(returncode=1)
    )
    cli_mod._register_with_claude()
    assert "exited 1" in capsys.readouterr().err


def test_main_setup_dispatches(monkeypatch):
    captured = {}

    def fake_setup(*, token, user_id, force, register, with_integrations):
        captured.update(
            token=token, user_id=user_id, force=force, register=register,
            with_integrations=with_integrations,
        )
        return 0

    monkeypatch.setattr(cli_mod, "_cmd_setup", fake_setup)
    rc = main(["setup", "--token", "T", "--user-id", "9", "--force"])
    assert rc == 0
    assert captured == {
        "token": "T",
        "user_id": "9",
        "force": True,
        "register": True,
        "with_integrations": False,
    }


# ─── away mode: presence / hooks / install (aw7nqkp4) ───────────────────────


@pytest.fixture
def cli_presence(tmp_path, monkeypatch):
    from confer import presence as presence_mod
    p = tmp_path / "confer.presence"
    monkeypatch.setattr(presence_mod, "presence_file", lambda: p)
    return p


def test_parser_away_with_note():
    args = _build_parser().parse_args(["away", "--note", "lunch"])
    assert args.cmd == "away" and args.note == "lunch" and args.when == []


def test_parser_away_with_schedule_words():
    args = _build_parser().parse_args(["away", "at", "1100"])
    assert args.cmd == "away" and args.when == ["at", "1100"]


def test_parser_back_with_target_words():
    args = _build_parser().parse_args(["back", "at", "1100"])
    assert args.cmd == "back" and args.target == ["at", "1100"]


def test_parser_hook_rejects_unknown_event():
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["hook", "bogus"])


def test_parser_install_hooks_print_flag():
    args = _build_parser().parse_args(["install-hooks", "--print"])
    assert args.cmd == "install-hooks" and args.dry_run is True


def test_main_away_sets_presence(cli_presence, capsys):
    assert main(["away"]) == 0
    assert cli_presence.exists()
    assert "away mode ON" in capsys.readouterr().out


def test_main_away_with_note_echoes_note(cli_presence, capsys):
    assert main(["away", "--note", "bbl"]) == 0
    assert '"bbl"' in capsys.readouterr().out


def test_main_back_clears_presence(cli_presence, capsys):
    from confer import presence as presence_mod
    presence_mod.set_away(now=1.0)
    assert main(["back"]) == 0
    assert not cli_presence.exists()
    assert "away mode OFF" in capsys.readouterr().out


def test_main_status_present(cli_presence, capsys):
    assert main(["status"]) == 0
    assert capsys.readouterr().out.strip() == "present"


def test_main_status_away_with_note(cli_presence, capsys):
    from confer import presence as presence_mod
    presence_mod.set_away("lunch", now=1.0)
    assert main(["status"]) == 0
    assert capsys.readouterr().out.strip() == 'away — note: "lunch"'


def test_main_status_away_no_note(cli_presence, capsys):
    from confer import presence as presence_mod
    presence_mod.set_away(now=1.0)
    assert main(["status"]) == 0
    assert capsys.readouterr().out.strip() == "away"


# ─── scheduled away (sq7nkp4x) via the CLI ──────────────────────────────────

def test_main_away_in_schedules_future(cli_presence, capsys):
    assert main(["away", "in", "5"]) == 0
    assert "away scheduled for" in capsys.readouterr().out
    from confer import presence as presence_mod
    assert len(presence_mod.read_presence().pending) == 1


def test_main_away_at_schedules_future(cli_presence, capsys):
    assert main(["away", "at", "1800", "--note", "mtg"]) == 0
    out = capsys.readouterr().out
    assert "away scheduled for" in out and '"mtg"' in out


def test_main_away_bad_schedule_word_errors(cli_presence, capsys):
    assert main(["away", "soon"]) == 2
    assert "expected 'in" in capsys.readouterr().err


def test_main_away_bad_in_value_errors(cli_presence, capsys):
    assert main(["away", "in", "soon"]) == 2
    assert "confer:" in capsys.readouterr().err


def test_main_away_bad_at_value_errors(cli_presence, capsys):
    assert main(["away", "at", "2500"]) == 2
    assert "confer:" in capsys.readouterr().err


def test_main_back_all_clears_everything(cli_presence, capsys):
    from confer import presence as presence_mod
    presence_mod.set_away(now=1.0)
    presence_mod.schedule_away(at=9_999_999_999.0)
    assert main(["back", "all"]) == 0
    assert not cli_presence.exists()
    assert "all scheduled aways" in capsys.readouterr().out


def test_main_back_at_cancels_matching(cli_presence, capsys, monkeypatch):
    from confer import awaytime, presence as presence_mod
    at = awaytime.parse_at_clock("1800")
    presence_mod.schedule_away(at=at, note="mtg")
    assert main(["back", "at", "1800"]) == 0
    assert "cancelled the scheduled away" in capsys.readouterr().out
    assert presence_mod.read_presence().pending == ()


def test_main_back_at_no_match_reports(cli_presence, capsys):
    from confer import awaytime, presence as presence_mod
    presence_mod.schedule_away(at=awaytime.parse_at_clock("1800"))
    # 1900 doesn't match the 1800 entry.
    assert main(["back", "at", "1900"]) == 1
    err = capsys.readouterr().err
    assert "no scheduled away" in err and "Pending:" in err


def test_main_back_at_no_match_empty_schedule(cli_presence, capsys):
    assert main(["back", "at", "1900"]) == 1
    assert "nothing is scheduled" in capsys.readouterr().err


def test_main_back_at_bad_time_errors(cli_presence, capsys):
    assert main(["back", "at", "2500"]) == 2
    assert "confer:" in capsys.readouterr().err


def test_main_back_unrecognized_target_errors(cli_presence, capsys):
    assert main(["back", "sideways"]) == 2
    assert "unrecognized" in capsys.readouterr().err


def test_main_status_shows_schedule(cli_presence, capsys):
    from confer import awaytime, presence as presence_mod
    presence_mod.schedule_away(at=awaytime.parse_at_clock("1800"), note="standup")
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "present" in out and "scheduled away:" in out and "standup" in out


def test_main_hook_prompt_clears_presence(cli_presence):
    from confer import presence as presence_mod
    presence_mod.set_away(now=1.0)
    assert main(["hook", "prompt"]) == 0
    assert not cli_presence.exists()


def test_main_hook_stop_allows_when_present(cli_presence, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert main(["hook", "stop"]) == 0
    assert capsys.readouterr().err == ""


def test_main_hook_stop_blocks_when_away(cli_presence, tmp_path, monkeypatch, capsys):
    from confer import presence as presence_mod
    presence_mod.set_away(now=1.0)
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "user", "message": {"content": []}}) + "\n")
    payload = json.dumps({"stop_hook_active": False, "transcript_path": str(t)})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert main(["hook", "stop"]) == 2
    assert "away from the keyboard" in capsys.readouterr().err


def test_main_hook_silences_warning_logging(cli_presence, monkeypatch):
    """Regression for hk7nqp4m: a WARNING logged while the hook runs (e.g. the
    WSL XDG_RUNTIME_DIR fallback in paths.py) must NOT reach stderr via Python's
    lastResort handler, or Claude Code mislabels the whole hook invocation a
    'Stop hook error'. The hook entrypoint must disable warning-level logging so
    the process emits only its intended payload. Asserted via the mechanism
    (warning logging disabled) because pytest's own log capture masks the
    lastResort-to-stderr path this bug rides on."""
    import logging

    captured = {}

    def check_logging_state(_stdin):
        captured["warning_enabled"] = logging.getLogger("confer.paths").isEnabledFor(
            logging.WARNING
        )
        return (0, "")

    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    monkeypatch.setattr("confer.hooks.run_stop_hook", check_logging_state)
    assert main(["hook", "stop"]) == 0
    assert captured["warning_enabled"] is False, (
        "hook entrypoint must disable WARNING logging so paths.py's "
        "XDG fallback warning cannot leak to stderr"
    )


def test_main_install_hooks_applies(monkeypatch, capsys):
    from confer import integrations
    monkeypatch.setattr(
        integrations, "install", lambda **kw: ["add Stop hook -> x"]
    )
    assert main(["install-hooks"]) == 0
    out = capsys.readouterr().out
    assert "Applied:" in out and "add Stop hook" in out


def test_main_install_hooks_dry_run(monkeypatch, capsys):
    from confer import integrations
    monkeypatch.setattr(integrations, "install", lambda **kw: ["x"])
    assert main(["install-hooks", "--print"]) == 0
    assert "Would apply:" in capsys.readouterr().out


def test_main_install_hooks_reports_corrupt_settings(monkeypatch, capsys):
    from confer import integrations

    def boom(**kw):
        raise json.JSONDecodeError("bad", "doc", 0)

    monkeypatch.setattr(integrations, "install", boom)
    assert main(["install-hooks"]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_setup_with_integrations_runs_installer(tmp_path, monkeypatch, capsys):
    _point_config_at(monkeypatch, tmp_path)
    from confer import integrations
    monkeypatch.setattr(integrations, "install", lambda **kw: ["installed X"])
    rc = cli_mod._cmd_setup(
        token="t", user_id="1", force=False, register=False,
        with_integrations=True,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Installing away-mode integrations" in out
    assert "installed X" in out
