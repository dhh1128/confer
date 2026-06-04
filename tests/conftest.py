"""Shared pytest fixtures for the confer test suite."""

import os
from datetime import date

import pytest

import freshness

# Set true once any integration-marked test passes its call phase, so the
# auto-stamp hook (this.i m4xq7npk) refreshes the freshness stamp only when the
# integration tier actually ran green — not on a plain unit run.
_integration_passed = False


def pytest_runtest_logreport(report):
    global _integration_passed
    if (
        report.when == "call"
        and report.passed
        and "integration" in report.keywords
        and "interactive" not in report.keywords
    ):
        _integration_passed = True


def pytest_sessionfinish(session):
    """Auto-refresh the integration freshness stamp (this.i m4xq7npk) when the
    integration tier ran AND the whole session was clean. A failed or flaky run
    (session.testsfailed > 0) never refreshes the stamp."""
    if _integration_passed and not session.testsfailed:
        freshness.write_stamp(date.today())


def pytest_addoption(parser):
    """--interactive activates the human-in-the-loop tier (this.i k4n7pqx2):
    tests that DM you on real Discord and wait for you to act. Off by default
    so a normal run never blocks on a human."""
    parser.addoption(
        "--interactive",
        action="store_true",
        default=False,
        help="Run confer human-in-the-loop tests (you act in Discord).",
    )


def pytest_collection_modifyitems(config, items):
    """Gate the two opt-in tiers, each independently (this.i 7vpm2qkx):
      - integration: real bot, automatable -> CONFER_INTEGRATION=1
      - interactive: real bot + a human in Discord -> --interactive
    Anything not opted into is skipped, never failed."""
    run_integration = os.environ.get("CONFER_INTEGRATION") == "1"
    run_interactive = config.getoption("--interactive")
    skip_integration = pytest.mark.skip(
        reason="integration tests require CONFER_INTEGRATION=1"
    )
    skip_interactive = pytest.mark.skip(
        reason="interactive tests require --interactive (you must act in Discord)"
    )
    for item in items:
        if "interactive" in item.keywords:
            if not run_interactive:
                item.add_marker(skip_interactive)
        elif "integration" in item.keywords:
            if not run_integration:
                item.add_marker(skip_integration)


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Patch the daemon CLI's path helpers to return tmp_path locations.

    Yields a dict with keys: pid, sock, log.
    """
    from confer.daemon import __main__ as cli

    pid = tmp_path / "confer.pid"
    sock = tmp_path / "confer.sock"
    log = tmp_path / "daemon.log"
    monkeypatch.setattr(cli, "pid_file", lambda: pid)
    monkeypatch.setattr(cli, "socket_path", lambda: sock)
    monkeypatch.setattr(cli, "log_file", lambda: log)
    return {"pid": pid, "sock": sock, "log": log}


@pytest.fixture
def client_socket(tmp_path, monkeypatch):
    """Patch the DaemonClient module's socket_path to a tmp_path location."""
    from confer import client as client_mod

    sock = tmp_path / "confer.sock"
    monkeypatch.setattr(client_mod, "socket_path", lambda: sock)
    return sock


