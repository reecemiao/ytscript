"""Plain data types shared across the package."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Video:
    """A single video on a channel's uploads feed."""

    id: str
    title: str
    url: str
    channel: str | None = None
    upload_date: date | None = None
    duration: float | None = None
    description: str | None = None


@dataclass(frozen=True)
class Segment:
    """One timed chunk of recognised speech."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    """The full speech-to-text result for one video."""

    video: Video
    segments: list[Segment]
    language: str | None = None
    backend: str = ""

    @property
    def text(self) -> str:
        return " ".join(segment.text.strip() for segment in self.segments if segment.text.strip())


@dataclass
class RunReport:
    """What a single ``ytscript run`` did."""

    checked: int = 0
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
