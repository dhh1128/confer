import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


def default_config_path() -> Path:
    return Path.home() / ".config" / "confer" / "config.toml"


def _warn_if_loose_perms(path: Path) -> None:
    """Best-effort warning if config.toml has group/other bits set; doesn't
    refuse to load because that would create a hostile failure mode where
    a typo locks the user out."""
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return
    if mode & 0o077:
        log.warning(
            "Config file %s has loose permissions (mode 0o%o); the Discord "
            "bot token may be readable by other users on this machine. "
            "Run: chmod 600 %s",
            path,
            mode,
            path,
        )


_DEFAULT_RE_PING_EVERY_SECONDS = 900


@dataclass(frozen=True)
class Settings:
    discord_bot_token: str
    confer_user_id: int
    re_ping_every_seconds: int = _DEFAULT_RE_PING_EVERY_SECONDS

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path if path is not None else default_config_path()
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Config file not found at {path}. "
                f"Copy config.toml.example from the confer repo to {path}, "
                f"chmod 600 it, and fill in your bot token and Discord user ID."
            ) from e
        _warn_if_loose_perms(path)
        try:
            ask_table = data.get("ask", {})
            re_ping = int(
                ask_table.get(
                    "re_ping_every_seconds", _DEFAULT_RE_PING_EVERY_SECONDS
                )
            )
            if re_ping < 1:
                raise ValueError(
                    f"re_ping_every_seconds must be >= 1 (got {re_ping})"
                )
            return cls(
                discord_bot_token=data["discord_bot_token"],
                confer_user_id=int(data["confer_user_id"]),
                re_ping_every_seconds=re_ping,
            )
        except KeyError as e:
            raise ValueError(
                f"Missing required config key '{e.args[0]}' in {path}"
            ) from e
