"""Configuration loading: TOML file, environment variables, then CLI overrides."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_NAMES = ("ytscript.toml", ".ytscript.toml")
ENV_PREFIX = "YTSCRIPT_"

BACKENDS = ("faster-whisper", "openai")
OUTPUT_FORMATS = ("txt", "md", "json")


class ConfigError(ValueError):
    """Raised when the configuration is missing something or self-contradictory."""


@dataclass
class Config:
    # --- what to watch -------------------------------------------------
    channel: str = ""
    """Channel handle (``@handle``), channel id (``UC...``) or any channel URL."""

    # --- language ------------------------------------------------------
    language: str | None = "en"
    """Main spoken language as an ISO 639-1 code. ``None``/``"auto"`` detects it."""

    # --- how much to do ------------------------------------------------
    initial_backfill: int = 30
    """Videos to transcribe on the very first run (empty state file)."""

    check_limit: int = 5
    """Newest videos inspected on later runs; unseen ones get transcribed."""

    # --- speech-to-text -------------------------------------------------
    backend: str = "faster-whisper"
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str = "default"
    openai_model: str = "whisper-1"
    openai_api_key_env: str = "OPENAI_API_KEY"

    # --- output ---------------------------------------------------------
    output_dir: Path = Path("scripts")
    output_formats: tuple[str, ...] = ("txt",)
    timestamps: bool = False
    """Prefix each paragraph of the script with its ``[hh:mm:ss]`` start time."""

    paragraph_gap: float = 2.0
    """Silence in seconds between segments that starts a new paragraph."""

    # --- plumbing --------------------------------------------------------
    state_file: Path = Path(".ytscript-state.json")
    audio_dir: Path | None = None
    """Where downloaded audio is kept. ``None`` uses a temporary directory."""

    keep_audio: bool = False
    audio_format: str = "bestaudio[ext=m4a]/bestaudio/best"
    cookies_file: Path | None = None

    extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.language in ("auto", ""):
            self.language = None
        self.output_dir = Path(self.output_dir)
        self.state_file = Path(self.state_file)
        if self.audio_dir is not None:
            self.audio_dir = Path(self.audio_dir)
        if self.cookies_file is not None:
            self.cookies_file = Path(self.cookies_file)
        if isinstance(self.output_formats, str):
            self.output_formats = tuple(
                part.strip() for part in self.output_formats.split(",") if part.strip()
            )
        else:
            self.output_formats = tuple(self.output_formats)

    def validate(self) -> None:
        if not self.channel:
            raise ConfigError(
                "no channel configured; set 'channel' in ytscript.toml, "
                "export YTSCRIPT_CHANNEL, or pass --channel"
            )
        if self.backend not in BACKENDS:
            raise ConfigError(f"unknown backend {self.backend!r}; expected one of {', '.join(BACKENDS)}")
        unknown = [fmt for fmt in self.output_formats if fmt not in OUTPUT_FORMATS]
        if unknown:
            raise ConfigError(
                f"unknown output format(s) {', '.join(unknown)}; "
                f"expected any of {', '.join(OUTPUT_FORMATS)}"
            )
        if not self.output_formats:
            raise ConfigError("output_formats is empty; expected at least one of " + ", ".join(OUTPUT_FORMATS))
        if self.initial_backfill < 1:
            raise ConfigError("initial_backfill must be at least 1")
        if self.check_limit < 1:
            raise ConfigError("check_limit must be at least 1")


_FIELD_TYPES = {f.name: f.type for f in fields(Config)}


def _coerce(name: str, raw: str) -> Any:
    """Turn an environment string into the type the matching field expects."""
    declared = str(_FIELD_TYPES.get(name, "str"))
    if "bool" in declared:
        lowered = raw.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise ConfigError(f"{ENV_PREFIX}{name.upper()}: expected a boolean, got {raw!r}")
    if "int" in declared:
        return int(raw)
    if "float" in declared:
        return float(raw)
    if name == "output_formats":
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    return raw


def find_config_file(start: Path | None = None) -> Path | None:
    """Look for a config file in ``start`` and each parent directory."""
    directory = (start or Path.cwd()).resolve()
    for candidate_dir in (directory, *directory.parents):
        for name in DEFAULT_CONFIG_NAMES:
            candidate = candidate_dir / name
            if candidate.is_file():
                return candidate
    return None


def load_config(
    path: Path | None = None,
    overrides: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    search_from: Path | None = None,
) -> Config:
    """Build a :class:`Config` from file, then environment, then overrides."""
    env = os.environ if env is None else env
    values: dict[str, Any] = {}

    config_path = path if path is not None else find_config_file(search_from)
    if path is not None and not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    if config_path is not None:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
        # Both a flat table and a [ytscript] section are accepted.
        data = data.get("ytscript", data)
        known = {key: value for key, value in data.items() if key in _FIELD_TYPES}
        values.update(known)
        leftover = {key: value for key, value in data.items() if key not in _FIELD_TYPES}
        if leftover:
            values["extra"] = leftover

    for name in _FIELD_TYPES:
        if name == "extra":
            continue
        raw = env.get(f"{ENV_PREFIX}{name.upper()}")
        if raw is not None:
            values[name] = _coerce(name, raw)

    for name, value in (overrides or {}).items():
        if value is None:
            continue
        if name not in _FIELD_TYPES:
            raise ConfigError(f"unknown setting {name!r}")
        values[name] = value

    return Config(**values)


SAMPLE_CONFIG = """\
# ytscript configuration

# Channel handle, channel id or any channel URL.
channel = "@channelhandle"

# Main spoken language (ISO 639-1). Use "auto" to let the model detect it.
language = "en"

# The first run transcribes this many of the newest videos; later runs only
# look at the newest `check_limit` and pick up whatever is not in the state file.
initial_backfill = 30
check_limit = 5

# "faster-whisper" runs locally, "openai" calls the hosted transcription API.
backend = "faster-whisper"
whisper_model = "small"
whisper_device = "auto"
whisper_compute_type = "default"

output_dir = "scripts"
output_formats = ["txt"]
timestamps = false

state_file = ".ytscript-state.json"
keep_audio = false
"""
