"""Fixtures for the live integration + interactive tiers (this.i 7vpm2qkx,
5nqx7pmw, k4n7pqx2).

These tests hit a real Discord bot, so they borrow the operator's real config
credentials. Gating (CONFER_INTEGRATION=1 / --interactive) is handled centrally
in tests/conftest.py; here we only borrow creds (skipping when none exist) and
spin an isolated daemon.
"""

import os
import subprocess
import time
from contextlib import contextmanager, suppress

import pytest

from confer.config import Settings
from confer.paths import socket_path

# Generous: a cold Discord Gateway handshake (login + READY) can take several
# seconds, and serve() binds the socket only AFTER wait_for_ready() returns —
# so the socket appearing is itself proof the Gateway is up.
_DAEMON_READY_TIMEOUT = 45.0
_POLL_INTERVAL = 0.2


def _borrow_real_settings() -> Settings:
    """Load the operator's real config to reuse its bot creds; skip (not fail)
    the test when there is no usable config to borrow from."""
    try:
        return Settings.load()
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"no usable real confer config to borrow creds from: {exc}")


@contextmanager
def _isolated_daemon(tmp_path, monkeypatch, *, user_id=None):
    """Spawn a real confer-daemon against an isolated config + runtime dir.

    Borrows the real bot creds (optionally overriding confer_user_id to force a
    specific failure mode), points the daemon at a throwaway config.toml via
    CONFER_CONFIG (w3kq7nxp), and redirects socket/pid/log into tmp via
    XDG_RUNTIME_DIR / XDG_STATE_HOME so nothing collides with a real daemon.
    Yields once the daemon has bound its socket (== Gateway ready), then tears
    it down.
    """
    settings = _borrow_real_settings()
    uid = settings.confer_user_id if user_id is None else user_id

    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    state = tmp_path / "state"
    state.mkdir()
    config = tmp_path / "config.toml"
    config.write_text(
        f'discord_bot_token = "{settings.discord_bot_token}"\n'
        f"confer_user_id = {uid}\n"
        "[ask]\n"
        f"re_ping_every_seconds = {settings.re_ping_every_seconds}\n"
    )
    config.chmod(0o600)

    monkeypatch.setenv("CONFER_CONFIG", str(config))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))

    # Spawn the daemon ourselves (rather than via DaemonClient auto-spawn) so we
    # own teardown and can wait out a slow handshake without the client's
    # shorter spawn timeout giving up.
    out_path = state / "daemon.out"
    log_fh = open(out_path, "a")
    proc = subprocess.Popen(
        ["confer-daemon"],
        stdout=log_fh,
        stderr=log_fh,
        stdin=subprocess.DEVNULL,
    )
    try:
        sock = socket_path()
        deadline = time.monotonic() + _DAEMON_READY_TIMEOUT
        while time.monotonic() < deadline:
            if sock.exists():
                break
            if proc.poll() is not None:
                raise RuntimeError(
                    f"confer-daemon exited early (code {proc.returncode}); "
                    f"see {out_path}"
                )
            time.sleep(_POLL_INTERVAL)
        else:
            raise RuntimeError(
                f"confer-daemon did not bind {sock} within "
                f"{_DAEMON_READY_TIMEOUT}s; Gateway likely never became ready "
                f"(bad token? no shared guild?). See {out_path}."
            )
        yield
    finally:
        with suppress(Exception):
            subprocess.run(["confer-daemon", "stop"], timeout=10)
        if proc.poll() is None:
            with suppress(Exception):
                proc.terminate()
                proc.wait(timeout=10)
        log_fh.close()


@pytest.fixture
def integration_daemon(tmp_path, monkeypatch):
    """Real daemon wired to the operator's real bot identity."""
    with _isolated_daemon(tmp_path, monkeypatch):
        yield


@pytest.fixture
def integration_daemon_bad_user(tmp_path, monkeypatch):
    """Real daemon + real token but a bogus confer_user_id, to exercise the
    notify failure path (discord.NotFound -> sentinel) against real Discord."""
    with _isolated_daemon(tmp_path, monkeypatch, user_id=1):
        yield
