"""The interface every speech-to-text backend implements."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import Segment


class TranscriptionError(RuntimeError):
    """Raised when a backend is unavailable or fails on a file."""


@runtime_checkable
class Transcriber(Protocol):
    """Turns an audio file into timed segments of text."""

    name: str

    def transcribe(
        self, audio_path: Path, language: str | None = None
    ) -> tuple[list[Segment], str | None]:
        """Return the segments and the language that was used or detected."""
        ...
