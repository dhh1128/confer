"""Shared pytest fixtures for the confer test suite."""

import pytest


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


