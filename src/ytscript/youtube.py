"""Talking to YouTube: listing a channel's uploads and fetching audio."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypeVar

from .models import Video

log = logging.getLogger("ytscript")

T = TypeVar("T")

_CHANNEL_ID = re.compile(r"^UC[\w-]{22}$")
_WATCH_URL = "https://www.youtube.com/watch?v={id}"

# yt-dlp's name for "this channel's members only"; it is on flat listing entries too,
# read off the "Members only" badge, so a listing tells us before a download tries.
MEMBERS_ONLY_AVAILABILITY = "subscriber_only"

# What YouTube says when the request is not signed in as a member of the channel.
_MEMBERS_ONLY_ERRORS = ("members-only", "members only", "join this channel")

# Network trouble that another attempt can get past. Matched against the whole
# exception chain in lower case, so a localised OS message ("远程主机强迫关闭了一个现有
# 的连接。") is still caught by the English class name Python wraps it in.
_TRANSIENT_HINTS = (
    "connection aborted",
    "connection reset",
    "connectionreseterror",
    "connection broken",
    "connection refused",
    "connectionerror",
    "remote end closed connection",
    "incompleteread",
    "timed out",
    "timeout",
    "temporary failure in name resolution",
    "unable to download webpage",
    "unable to download api page",
    "giving up after",
    "content too short",
    "http error 429",
    "http error 500",
    "http error 502",
    "http error 503",
    "http error 504",
    "eof occurred in violation of protocol",
)

_MEMBERSHIP_HINT = (
    "sign in as a member: set cookies_file (a cookies.txt export) or "
    'cookies_from_browser (e.g. "firefox") to an account that holds the membership'
)

# yt-dlp's --cookies-from-browser syntax: BROWSER[+KEYRING][:PROFILE][::CONTAINER].
_BROWSER_SPEC = re.compile(
    r"""(?x)
    (?P<name>[^+:]+)
    (?:\s*\+\s*(?P<keyring>[^:]+))?
    (?:\s*:\s*(?!:)(?P<profile>.+?))?
    (?:\s*::\s*(?P<container>.+))?
    """
)


class YouTubeError(RuntimeError):
    """Raised when yt-dlp cannot list a channel or fetch a video."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient
        """Whether the same call has a fair chance of working on another try."""


def _causes(exc: BaseException) -> Iterator[BaseException]:
    """Walk an exception and everything it was raised from."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def is_transient(exc: BaseException) -> bool:
    """Whether ``exc`` looks like network trouble rather than a refusal.

    A dropped connection mid-download is the common one:
    ``('Connection aborted.', ConnectionResetError(10054, ...))``.
    """
    for error in _causes(exc):
        if isinstance(error, ConnectionError | TimeoutError):
            return True
        if isinstance(error, OSError) and error.errno in (54, 60, 104, 110, 10054, 10060):
            return True
        lowered = str(error).lower()
        if any(hint in lowered for hint in _TRANSIENT_HINTS):
            return True
    return False


def _load_yt_dlp() -> Any:
    try:
        import yt_dlp  # noqa: PLC0415 - optional at import time, required at call time
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise YouTubeError(
            "yt-dlp is not installed; it is a required dependency, so 'uv sync' fixes it"
        ) from exc
    return yt_dlp


def parse_browser_spec(spec: str) -> tuple[str, str | None, str | None, str | None]:
    """Split ``BROWSER[+KEYRING][:PROFILE][::CONTAINER]`` the way the yt-dlp flag does."""
    match = _BROWSER_SPEC.fullmatch(spec.strip())
    if match is None:
        raise YouTubeError(
            f"could not parse cookies_from_browser {spec!r}; "
            "expected BROWSER[+KEYRING][:PROFILE][::CONTAINER]"
        )
    name, keyring, profile, container = match.group("name", "keyring", "profile", "container")
    # yt-dlp validates the browser and keyring names; the order below is what it expects.
    return name.strip().lower(), profile, keyring.strip().upper() if keyring else None, container


def is_members_only(info: dict[str, Any]) -> bool:
    return info.get("availability") == MEMBERS_ONLY_AVAILABILITY


def _mentions_membership(message: str) -> bool:
    lowered = message.lower()
    return any(hint in lowered for hint in _MEMBERS_ONLY_ERRORS)


def channel_uploads_url(channel: str) -> str:
    """Normalise a handle, channel id or URL into the channel's uploads tab."""
    value = channel.strip()
    if not value:
        raise YouTubeError("channel is empty")

    if value.startswith("@"):
        url = f"https://www.youtube.com/{value}"
    elif _CHANNEL_ID.match(value):
        url = f"https://www.youtube.com/channel/{value}"
    elif value.startswith(("http://", "https://")):
        url = value
    elif value.startswith("www.") or value.startswith("youtube.com"):
        url = f"https://{value}"
    else:
        # A bare name is treated as a handle, which is how YouTube resolves it today.
        url = f"https://www.youtube.com/@{value}"

    url = url.rstrip("/")
    tail = url.rsplit("/", 1)[-1]
    if tail in ("videos", "streams", "shorts", "featured"):
        return url
    return f"{url}/videos"


def _parse_upload_date(info: dict[str, Any]) -> date | None:
    raw = info.get("upload_date")
    if raw:
        try:
            return datetime.strptime(str(raw), "%Y%m%d").date()
        except ValueError:
            pass
    for key in ("release_timestamp", "timestamp"):
        stamp = info.get(key)
        if stamp:
            try:
                return datetime.fromtimestamp(float(stamp)).date()
            except (OverflowError, OSError, ValueError):
                continue
    return None


def _to_video(info: dict[str, Any]) -> Video:
    video_id = info.get("id") or ""
    return Video(
        id=video_id,
        title=info.get("title") or video_id,
        url=info.get("webpage_url") or info.get("url") or _WATCH_URL.format(id=video_id),
        channel=info.get("channel") or info.get("uploader"),
        upload_date=_parse_upload_date(info),
        duration=info.get("duration"),
        description=info.get("description"),
        members_only=is_members_only(info),
    )


class YouTubeClient:
    """Thin wrapper over yt-dlp, kept narrow so it is easy to fake in tests."""

    def __init__(
        self,
        audio_format: str = "bestaudio[ext=m4a]/bestaudio/best",
        cookies_file: Path | None = None,
        cookies_from_browser: str | None = None,
        quiet: bool = True,
        retries: int = 3,
        retry_backoff: float = 5.0,
        socket_timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.audio_format = audio_format
        self.cookies_file = cookies_file
        self.cookies_from_browser = cookies_from_browser
        self.quiet = quiet
        self.retries = max(0, retries)
        """Extra attempts a request gets after network trouble; 0 means one try only."""

        self.retry_backoff = max(0.0, retry_backoff)
        """Seconds before the second attempt; each further wait doubles it."""

        self.socket_timeout = socket_timeout
        self._sleep = sleep

    @property
    def signed_in(self) -> bool:
        """Whether requests carry cookies — members-only downloads need them."""
        return bool(self.cookies_file or self.cookies_from_browser)

    def _base_opts(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "noprogress": self.quiet,
            "ignoreerrors": False,
            # yt-dlp's own retries come first: they resume a half-downloaded file
            # from its .part, where our outer retry starts the request again.
            "retries": self.retries,
            "fragment_retries": self.retries,
            "extractor_retries": self.retries,
            "socket_timeout": self.socket_timeout,
            "continuedl": True,
        }
        if self.cookies_file:
            opts["cookiefile"] = str(self.cookies_file)
        if self.cookies_from_browser:
            opts["cookiesfrombrowser"] = parse_browser_spec(self.cookies_from_browser)
        return opts

    def _attempt(self, what: str, call: Callable[[], T]) -> T:
        """Run ``call``, giving it another go while the failure looks like network trouble."""
        for attempt in range(1, self.retries + 2):
            try:
                return call()
            except YouTubeError as exc:
                if not exc.transient or attempt > self.retries:
                    raise
                delay = self.retry_backoff * 2 ** (attempt - 1)
                log.warning(
                    "%s failed (attempt %d of %d): %s; retrying in %.0fs",
                    what,
                    attempt,
                    self.retries + 1,
                    exc,
                    delay,
                )
                self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def latest_videos(self, channel: str, limit: int) -> list[Video]:
        """Return up to ``limit`` of the channel's newest uploads, newest first."""
        return self._attempt(f"listing {channel}", lambda: self._list_videos_once(channel, limit))

    def _list_videos_once(self, channel: str, limit: int) -> list[Video]:
        yt_dlp = _load_yt_dlp()
        url = channel_uploads_url(channel)
        opts = self._base_opts() | {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "playlistend": max(1, limit),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # yt-dlp raises a family of DownloadError subclasses
            raise YouTubeError(
                f"could not list videos for {channel!r}: {exc}", transient=is_transient(exc)
            ) from exc

        entries = list(_iter_entries(info))
        videos = [_to_video(entry) for entry in entries if entry.get("id")]
        return videos[:limit]

    def download_audio(self, video: Video, dest_dir: Path) -> tuple[Path, Video]:
        """Download the audio track and return its path plus enriched metadata.

        A connection dropped mid-download is retried with a widening pause; yt-dlp
        picks the file up from the part it already has.
        """
        return self._attempt(
            f"downloading {video.id}", lambda: self._download_audio_once(video, dest_dir)
        )

    def _download_audio_once(self, video: Video, dest_dir: Path) -> tuple[Path, Video]:
        yt_dlp = _load_yt_dlp()
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        if video.members_only and not self.signed_in:
            # Saves a request that YouTube would refuse anyway, and says why.
            raise YouTubeError(f"{video.id} is members-only; {_MEMBERSHIP_HINT}")
        opts = self._base_opts() | {
            "format": self.audio_format,
            "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
            "noplaylist": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video.url, download=True)
                path = Path(ydl.prepare_filename(info))
        except Exception as exc:
            if _mentions_membership(str(exc)):
                # A listing without badges (or a video made members-only later) lands here.
                raise YouTubeError(f"{video.id} is members-only; {_MEMBERSHIP_HINT}") from exc
            raise YouTubeError(
                f"could not download audio for {video.id}: {exc}", transient=is_transient(exc)
            ) from exc

        if not path.is_file():
            matches = sorted(dest_dir.glob(f"{video.id}.*"))
            if not matches:
                raise YouTubeError(f"audio file for {video.id} is missing after download")
            path = matches[0]

        enriched = _to_video({**info, "id": video.id}) if isinstance(info, dict) else video
        # Flat listings often lack these, so keep whatever we already had.
        merged = Video(
            id=video.id,
            title=enriched.title or video.title,
            url=video.url or enriched.url,
            channel=enriched.channel or video.channel,
            upload_date=enriched.upload_date or video.upload_date,
            duration=enriched.duration or video.duration,
            description=enriched.description or video.description,
            members_only=enriched.members_only or video.members_only,
        )
        return path, merged


def _iter_entries(info: Any) -> Any:
    """Walk yt-dlp's playlist result, which can nest tabs inside playlists."""
    if not isinstance(info, dict):
        return
    entries = info.get("entries")
    if entries is None:
        if info.get("id"):
            yield info
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("_type") == "playlist" or entry.get("entries") is not None:
            yield from _iter_entries(entry)
        else:
            yield entry
