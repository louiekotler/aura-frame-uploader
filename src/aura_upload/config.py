"""Configuration loading and the frame allowlist.

The allowlist is the tool's central safety control. An Aura account commonly
holds frames belonging to other people, and the same credentials can write to
all of them. So writes are refused unless a frame is explicitly allowlisted:
absent or empty configuration means refuse, never allow-all.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError, FrameNotAllowed

APP_NAME = "aura-upload"

DEFAULT_MAX_LONG_EDGE = 2048
DEFAULT_JPEG_QUALITY = 90

# Aura rejects images above this; their web uploader enforces the same ceiling.
MAX_UPLOAD_BYTES = int(9.5 * 1024 * 1024)


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME


def config_path() -> Path:
    override = os.environ.get("AURA_UPLOAD_CONFIG")
    return Path(override) if override else config_dir() / "config.toml"


@dataclass
class Config:
    allowed_frame_ids: list[str] = field(default_factory=list)
    default_frame_id: str | None = None
    max_long_edge: int = DEFAULT_MAX_LONG_EDGE
    jpeg_quality: int = DEFAULT_JPEG_QUALITY
    account_email: str | None = None
    path: Path | None = None

    def resolve_frame(self, requested: str | None) -> str:
        """Return the frame id to write to, or refuse.

        Deliberately never falls back to "the only frame" or a name match —
        both are silent-mistake generators when other people's frames are
        reachable with the same credentials.
        """
        if not self.allowed_frame_ids:
            raise FrameNotAllowed(
                f"No allowed_frame_ids configured in {self.path or config_path()}.\n"
                "Writes are refused until you list the frame id(s) this tool may "
                "publish to. Run `aura-upload frames` to see the ids on your account."
            )

        frame_id = requested or self.default_frame_id
        if not frame_id:
            if len(self.allowed_frame_ids) == 1:
                frame_id = self.allowed_frame_ids[0]
            else:
                raise FrameNotAllowed(
                    "Multiple frames are allowlisted and no --frame was given. "
                    "Pass --frame explicitly or set defaults.frame_id."
                )

        if frame_id not in self.allowed_frame_ids:
            raise FrameNotAllowed(
                f"Frame {frame_id} is not in allowed_frame_ids. Refusing to write.\n"
                f"Allowed: {', '.join(self.allowed_frame_ids)}"
            )
        return frame_id

    def is_allowed(self, frame_id: str) -> bool:
        return frame_id in self.allowed_frame_ids


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        return Config(path=path)

    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}") from e

    allowed = raw.get("allowed_frame_ids", [])
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        raise ConfigError(f"{path}: allowed_frame_ids must be a list of strings.")

    defaults = raw.get("defaults", {}) or {}
    cfg = Config(
        allowed_frame_ids=allowed,
        default_frame_id=defaults.get("frame_id"),
        max_long_edge=int(defaults.get("max_long_edge", DEFAULT_MAX_LONG_EDGE)),
        jpeg_quality=int(defaults.get("jpeg_quality", DEFAULT_JPEG_QUALITY)),
        account_email=raw.get("account", {}).get("email"),
        path=path,
    )

    if cfg.default_frame_id and cfg.default_frame_id not in cfg.allowed_frame_ids:
        raise ConfigError(
            f"{path}: defaults.frame_id ({cfg.default_frame_id}) is not in "
            "allowed_frame_ids."
        )
    return cfg
