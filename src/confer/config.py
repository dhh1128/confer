import tomllib
from dataclasses import dataclass
from pathlib import Path


def default_config_path() -> Path:
    return Path.home() / ".config" / "confer" / "config.toml"


@dataclass(frozen=True)
class Settings:
    discord_bot_token: str
    confer_user_id: int

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path if path is not None else default_config_path()
        with path.open("rb") as f:
            data = tomllib.load(f)
        try:
            return cls(
                discord_bot_token=data["discord_bot_token"],
                confer_user_id=int(data["confer_user_id"]),
            )
        except KeyError as e:
            raise ValueError(
                f"Missing required config key '{e.args[0]}' in {path}"
            ) from e
