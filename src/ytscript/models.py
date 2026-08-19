"""Plain data types shared across the package."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

# Scripts that are written without spaces between words: CJK ideographs and the
# kana, plus the fullwidth punctuation that goes with them. Hangul is left out —
# Korean does space its words.
_UNSPACED = re.compile(
    r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uff65]"
)


def join_text(parts: list[str]) -> str:
    """Join chunks of recognised speech, leaving out the space where a script has none.

    Whisper returns Chinese one clause per segment, and joining those with a space
    gives ``今天 我们 来聊聊`` — spaces the language does not use. A space is only
    inserted when the characters on both sides of the seam belong to a script that
    writes them, so mixed passages like ``用 Python 写`` keep theirs.
    """
    joined = ""
    for part in parts:
        if not joined:
            joined = part
            continue
        separator = "" if _UNSPACED.match(joined[-1]) and _UNSPACED.match(part[0]) else " "
        joined += separator + part
    return joined


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
        return join_text([text for s in self.segments if (text := s.text.strip())])


@dataclass
class RunReport:
    """What a single ``ytscript run`` did."""

    checked: int = 0
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
