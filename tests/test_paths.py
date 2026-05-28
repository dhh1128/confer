from pathlib import Path

from confer import paths


def test_socket_path_uses_xdg_runtime_dir(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert paths.socket_path() == Path("/run/user/1000/confer.sock")


def test_socket_path_falls_back_when_xdg_runtime_dir_unset(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", "/tmp/state")
    assert paths.socket_path() == Path("/tmp/state/confer/confer.sock")


def test_pid_file_uses_xdg_runtime_dir(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert paths.pid_file() == Path("/run/user/1000/confer.pid")


def test_log_file_uses_xdg_state_home(monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", "/tmp/state")
    assert paths.log_file() == Path("/tmp/state/confer/daemon.log")


def test_state_home_falls_back_to_home_when_unset(monkeypatch):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    expected = Path.home() / ".local" / "state" / "confer" / "daemon.log"
    assert paths.log_file() == expected


def test_runtime_dir_falls_back_to_state_home_when_unset(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    expected = Path.home() / ".local" / "state" / "confer" / "confer.sock"
    assert paths.socket_path() == expected
