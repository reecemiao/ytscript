"""Local speech-to-text with faster-whisper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import Segment
from .base import TranscriptionError


class FasterWhisperTranscriber:
    """Runs Whisper locally through ctranslate2. No network, no API key."""

    name = "faster-whisper"

    def __init__(
        self,
        model: str = "small",
        device: str = "auto",
        compute_type: str = "default",
        vad_filter: bool = True,
        beam_size: int = 5,
    ) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.vad_filter = vad_filter
        self.beam_size = beam_size
        self._model: Any = None

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415 - optional dependency
        except ImportError as exc:
            raise TranscriptionError(
                "faster-whisper is not installed; install it with "
                "'pip install \"ytscript[local]\"' or switch backend to 'openai'"
            ) from exc
        try:
            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type
            )
        except Exception as exc:
            raise TranscriptionError(
                f"could not load whisper model {self.model_name!r}: {exc}"
            ) from exc
        return self._model

    def transcribe(
        self, audio_path: Path, language: str | None = None
    ) -> tuple[list[Segment], str | None]:
        model = self._load_model()
        try:
            raw_segments, info = model.transcribe(
                str(audio_path),
                language=language,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
            )
            segments = [
                Segment(start=float(s.start), end=float(s.end), text=s.text.strip())
                for s in raw_segments
            ]
        except Exception as exc:
            raise TranscriptionError(f"transcription of {audio_path.name} failed: {exc}") from exc
        detected = language or getattr(info, "language", None)
        return segments, detected
