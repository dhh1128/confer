import os
from pathlib import Path


def _xdg_state_home() -> Path:
    val = os.environ.get("XDG_STATE_HOME")
    if val:
        return Path(val)
    return Path.home() / ".local" / "state"


def _xdg_runtime_dir() -> Path:
    val = os.environ.get("XDG_RUNTIME_DIR")
    if val:
        return Path(val)
    return _xdg_state_home() / "confer"


def socket_path() -> Path:
    return _xdg_runtime_dir() / "confer.sock"


def pid_file() -> Path:
    return _xdg_runtime_dir() / "confer.pid"


def log_file() -> Path:
    return _xdg_state_home() / "confer" / "daemon.log"
