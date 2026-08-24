"""Configuration loading: TOML file, environment variables, then CLI overrides."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .vocabulary import VocabularyError, load_vocabulary

DEFAULT_CONFIG_NAMES = ("ytscript.toml", ".ytscript.toml")
ENV_PREFIX = "YTSCRIPT_"

BACKENDS = ("faster-whisper", "openai")
OUTPUT_FORMATS = ("txt", "md", "json")
DRIVE_SCOPES = ("drive.file", "drive")


class ConfigError(ValueError):
    """Raised when the configuration is missing something or self-contradictory."""


@dataclass
class Config:
    # --- what to watch -------------------------------------------------
    channel: str = ""
    """Channel handle (``@handle``), channel id (``UC...``) or any channel URL."""

    # --- language ------------------------------------------------------
    language: str | None = "zh"
    """Main spoken language as an ISO 639-1 code. ``None``/``"auto"`` detects it."""

    # --- how much to do ------------------------------------------------
    initial_backfill: int = 30
    """Videos to transcribe on the very first run (empty state file)."""

    check_limit: int = 5
    """Newest videos inspected on later runs; unseen ones get transcribed."""

    # --- when something goes wrong ---------------------------------------
    download_retries: int = 3
    """Extra attempts a YouTube request gets when the connection drops. ``0`` means one try.

    This is the fix for ``('Connection aborted.', ConnectionResetError(10054, ...))``
    and its friends: the download starts again and yt-dlp resumes the part it has."""

    retry_backoff: float = 5.0
    """Seconds before the second attempt; each further wait doubles it (5, 10, 20...)."""

    socket_timeout: float = 30.0
    """Seconds a stalled connection is given before it counts as a failed attempt."""

    retry_failed: bool = False
    """Also re-attempt the videos recorded as failed, even when they have fallen out of
    the ``check_limit`` window. ``--retry-failed`` turns it on for a single run."""

    retry_max_attempts: int = 3
    """How many times a failed video is picked up again before it is left alone.
    ``ytscript run --only-failed`` retries it regardless, and ``ytscript failures --clear``
    starts the count over."""

    # --- speech-to-text -------------------------------------------------
    backend: str = "faster-whisper"
    whisper_model: str = "large-v3"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    """Defaults target an 8 GB NVIDIA card; see the README for the CPU-only settings."""

    whisper_initial_prompt: str | None = None
    """Seed text that steers spelling and register — for Chinese, simplified vs traditional.

    ``None`` uses the stock sentence for ``language``; set it to ``""`` for no seed."""

    whisper_condition_on_previous_text: bool = False
    """Feed each clip the previous clip's text. Whisper's own default is on, and it is
    what makes the model repeat a phrase for a minute once it starts. Batched decoding
    turns it off regardless, so leaving it off also keeps the two paths in step."""

    prompt_from_metadata: bool = True
    """Prime each video with its own title and description, so the day's tickers and
    names are words the model is already expecting."""

    vocabulary: str | None = None
    """Terms the channel says every episode, and rewrites for what the model gets wrong.
    A built-in name (``"zh-finance"``) or the path to your own file."""

    whisper_batch_size: int = 4
    """Clips decoded at once. ``1`` turns batching off; 4 suits large-v3 on an 8 GB card."""

    openai_model: str = "whisper-1"
    openai_api_key_env: str = "OPENAI_API_KEY"

    # --- output ---------------------------------------------------------
    output_dir: Path = Path("scripts")
    output_formats: tuple[str, ...] = ("txt",)
    timestamps: bool = False
    """Prefix each paragraph of the script with its ``[hh:mm:ss]`` start time."""

    paragraph_gap: float = 2.0
    """Silence in seconds between segments that starts a new paragraph."""

    polish: bool = True
    """Tidy the recognised text before writing it: fullwidth punctuation for Chinese
    sentences, one copy of a looped phrase, and the vocabulary's rewrites."""

    convert_to_simplified: bool = False
    """Rewrite traditional characters as simplified ones. Needs 'uv sync --extra zh'."""

    # --- Google Drive (optional) -----------------------------------------
    drive_upload: bool = False
    """Also copy every finished script into Google Drive. Local files are written either way."""

    drive_folder_id: str | None = None
    """Folder the scripts land in, as an id or a folder URL. ``None`` uses ``drive_folder_name``."""

    drive_folder_name: str | None = "ytscript"
    """Folder created in My Drive when no ``drive_folder_id`` is set. Empty uploads to the root."""

    drive_credentials_file: Path | None = None
    """OAuth client secrets JSON for a desktop app, downloaded from the Google Cloud console."""

    drive_token_file: Path = Path(".ytscript-drive-token.json")
    """Where ``ytscript drive-auth`` caches the sign-in so later runs need no browser."""

    drive_service_account_file: Path | None = None
    """Service account key, for unattended runs. Needs a folder shared with the account."""

    drive_scope: str = "drive.file"
    """``drive.file`` only sees what ytscript uploads; ``drive`` is needed for a folder it
    did not create itself."""

    # --- plumbing --------------------------------------------------------
    state_file: Path = Path(".ytscript-state.json")
    audio_dir: Path | None = None
    """Where downloaded audio is kept. ``None`` uses a temporary directory."""

    keep_audio: bool = False
    audio_format: str = "bestaudio[ext=m4a]/bestaudio/best"
    cookies_file: Path | None = None
    """Netscape-format cookies.txt exported from a signed-in browser session."""

    cookies_from_browser: str | None = None
    """Read cookies straight out of a browser: ``BROWSER[+KEYRING][:PROFILE][::CONTAINER]``."""

    include_members_only: bool = False
    """Also transcribe members-only videos. Needs cookies from an account that is a member."""

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
        self.drive_token_file = Path(self.drive_token_file)
        if self.drive_credentials_file is not None:
            self.drive_credentials_file = Path(self.drive_credentials_file)
        if self.drive_service_account_file is not None:
            self.drive_service_account_file = Path(self.drive_service_account_file)
        if not self.drive_folder_name:
            self.drive_folder_name = None
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
            raise ConfigError(
                f"unknown backend {self.backend!r}; expected one of {', '.join(BACKENDS)}"
            )
        unknown = [fmt for fmt in self.output_formats if fmt not in OUTPUT_FORMATS]
        if unknown:
            raise ConfigError(
                f"unknown output format(s) {', '.join(unknown)}; "
                f"expected any of {', '.join(OUTPUT_FORMATS)}"
            )
        if not self.output_formats:
            raise ConfigError(
                "output_formats is empty; expected at least one of " + ", ".join(OUTPUT_FORMATS)
            )
        if self.initial_backfill < 1:
            raise ConfigError("initial_backfill must be at least 1")
        if self.check_limit < 1:
            raise ConfigError("check_limit must be at least 1")
        if self.whisper_batch_size < 1:
            raise ConfigError("whisper_batch_size must be at least 1 (1 turns batching off)")
        if self.download_retries < 0:
            raise ConfigError("download_retries cannot be negative (0 means one attempt)")
        if self.retry_backoff < 0:
            raise ConfigError("retry_backoff cannot be negative")
        if self.socket_timeout <= 0:
            raise ConfigError("socket_timeout must be greater than 0")
        if self.retry_max_attempts < 1:
            raise ConfigError("retry_max_attempts must be at least 1")
        # Reading the file now means a typo fails the command, not the first video.
        try:
            load_vocabulary(self.vocabulary)
        except VocabularyError as exc:
            raise ConfigError(str(exc)) from exc
        if self.include_members_only and not (self.cookies_file or self.cookies_from_browser):
            raise ConfigError(
                "include_members_only needs a signed-in session: set cookies_file or "
                "cookies_from_browser to an account that holds the channel's membership"
            )
        if self.drive_upload:
            self.validate_drive()

    def validate_drive(self) -> None:
        """Check the Google Drive settings on their own, whether or not uploads are on."""
        if self.drive_scope not in DRIVE_SCOPES:
            raise ConfigError(
                f"unknown drive_scope {self.drive_scope!r}; "
                f"expected one of {', '.join(DRIVE_SCOPES)}"
            )
        if self.drive_credentials_file and self.drive_service_account_file:
            raise ConfigError(
                "set drive_credentials_file or drive_service_account_file, not both: "
                "the first signs in as you, the second as a robot account"
            )
        if not (self.drive_credentials_file or self.drive_service_account_file):
            raise ConfigError(
                "Google Drive uploads need credentials: set drive_credentials_file to the "
                "OAuth client secrets JSON from the Google Cloud console, or "
                "drive_service_account_file to a service account key"
            )
        if self.drive_service_account_file and not self.drive_folder_id:
            raise ConfigError(
                "a service account has no Drive of its own: share a folder with the account's "
                "address and set drive_folder_id to it"
            )


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

# Main spoken language (ISO 639-1). Setting it beats "auto": it skips the
# detection pass and keeps the model from drifting into Japanese on unclear
# Mandarin audio.
language = "zh"

# The first run transcribes this many of the newest videos; later runs only
# look at the newest `check_limit` and pick up whatever is not in the state file.
initial_backfill = 30
check_limit = 5

# A dropped connection mid-download ("Connection aborted", ConnectionResetError) is
# retried this many extra times, waiting 5s, then 10s, then 20s between attempts.
download_retries = 3
retry_backoff = 5.0
socket_timeout = 30.0

# A video that still fails is written to the state file's "failures" list. Turn this
# on to re-attempt those on every run, even once they are older than `check_limit`;
# `ytscript run --retry-failed` does it for one run, and `ytscript failures` shows
# what is on the list. Each one is picked up at most `retry_max_attempts` times.
retry_failed = false
retry_max_attempts = 3

# "faster-whisper" runs locally, "openai" calls the hosted transcription API.
backend = "faster-whisper"

# large-v3 at float16 needs about 5 GB of VRAM and is the best Chinese accuracy
# an 8 GB card can hold. Out of memory -> "int8_float16" before a smaller model.
# No NVIDIA GPU -> whisper_device = "cpu", whisper_compute_type = "int8".
whisper_model = "large-v3"
whisper_device = "cuda"
whisper_compute_type = "float16"

# Whisper transcribes Mandarin into traditional characters about as readily as
# simplified. A simplified-character seed sentence settles it. Leave it unset to
# get the stock sentence for `language`, or set it to "" for no seed at all.
whisper_initial_prompt = "以下是普通话的句子。"

# The seed is followed by the video's own title and description, so the tickers
# and names that episode is about are words the model already expects.
prompt_from_metadata = true

# Terms the channel says every episode, plus rewrites for the ones the model
# keeps getting wrong ("对中基金 => 对冲基金"). "zh-finance" ships with ytscript
# and suits a Mandarin US-market channel; point this at your own file to extend
# it — `python -c "import ytscript.vocabulary as v; print(v.DATA_DIR)"` finds the
# built-in to copy. Leave it out for no vocabulary.
vocabulary = "zh-finance"

# Whisper's own default feeds each clip the text of the one before it, which is
# what makes it repeat a phrase for a minute when the audio goes quiet. Off also
# matches what batched decoding does, so both paths sound the same.
whisper_condition_on_previous_text = false

# Clips decoded at once — several times faster than one at a time, at the cost
# of VRAM. 4 leaves headroom on an 8 GB card; a 12 GB or larger card can take
# 8 or 16. Drop to 1 to turn batching off.
whisper_batch_size = 4

output_dir = "scripts"
output_formats = ["txt"]
timestamps = false

# Tidy the text before writing: fullwidth punctuation for Chinese sentences, one
# copy of a phrase the model looped on, and the vocabulary's rewrites.
polish = true

# Rewrite traditional characters as simplified. Needs `uv sync --extra zh`.
convert_to_simplified = false

state_file = ".ytscript-state.json"
keep_audio = false

# Optional: also copy every finished script into Google Drive. Install the extra
# with `uv sync --extra drive`, point drive_credentials_file at the OAuth client
# secrets JSON from the Google Cloud console, then run `ytscript drive-auth` once.
drive_upload = false
# drive_credentials_file = "drive-credentials.json"
drive_folder_name = "ytscript"          # folder made in My Drive for the scripts
# drive_folder_id = "1AbC..."           # an existing folder instead; needs drive_scope = "drive"
# drive_service_account_file = "drive-service-account.json"   # unattended runs

# Members-only videos are skipped unless you sign in. Point one of the two cookie
# settings at an account that holds the membership, then turn the flag on.
# cookies_file = "cookies.txt"
# cookies_from_browser = "firefox"          # BROWSER[+KEYRING][:PROFILE][::CONTAINER]
include_members_only = false
"""
