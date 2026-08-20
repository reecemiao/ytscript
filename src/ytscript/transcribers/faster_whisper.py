"""Local speech-to-text with faster-whisper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..models import Segment
from .base import TranscriptionError

log = logging.getLogger("ytscript")


def _is_out_of_memory(exc: Exception) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or "cuda_error_out_of_memory" in text


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
        initial_prompt: str | None = None,
        batch_size: int = 4,
    ) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.vad_filter = vad_filter
        self.beam_size = beam_size
        self.initial_prompt = initial_prompt
        self.batch_size = batch_size
        self._model: Any = None
        self._batched: Any = None

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415 - optional dependency
        except ImportError as exc:
            raise TranscriptionError(
                "faster-whisper is not installed; add it with "
                "'uv sync --extra local' or switch backend to 'openai'"
            ) from exc
        try:
            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type
            )
        except Exception as exc:
            raise TranscriptionError(
                f"could not load whisper model {self.model_name!r}: {exc}"
            ) from exc
        if self.batch_size > 1:
            self._batched = self._wrap_batched(self._model)
        return self._model

    def _wrap_batched(self, model: Any) -> Any:
        """Decode several clips at once. ``None`` falls back to one clip at a time."""
        try:
            from faster_whisper import (  # noqa: PLC0415 - optional dependency
                BatchedInferencePipeline,
            )
        except ImportError:
            log.warning(
                "the installed faster-whisper has no batched pipeline; transcribing "
                "sequentially. Upgrade to 1.1 or newer for the speedup."
            )
            return None
        return BatchedInferencePipeline(model=model)

    def _run(
        self, engine: Any, audio_path: Path, language: str | None, **extra: Any
    ) -> tuple[list[Segment], Any]:
        raw_segments, info = engine.transcribe(
            str(audio_path),
            language=language,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            initial_prompt=self.initial_prompt,
            **extra,
        )
        # The segment iterator is lazy — this is where the decoding actually runs,
        # so it is also where an out-of-memory error surfaces.
        segments = [
            Segment(start=float(s.start), end=float(s.end), text=s.text.strip())
            for s in raw_segments
        ]
        return segments, info

    def transcribe(
        self, audio_path: Path, language: str | None = None
    ) -> tuple[list[Segment], str | None]:
        model = self._load_model()
        try:
            if self._batched is None:
                segments, info = self._run(model, audio_path, language)
            else:
                try:
                    segments, info = self._run(
                        self._batched, audio_path, language, batch_size=self.batch_size
                    )
                except Exception as exc:
                    if not _is_out_of_memory(exc):
                        raise
                    # A batch that does not fit is worth one slow retry rather than
                    # a failed video the next run has to download again.
                    log.warning(
                        "%s: out of memory at batch_size=%d, retrying one clip at a "
                        "time; lower whisper_batch_size to avoid the retry",
                        audio_path.name,
                        self.batch_size,
                    )
                    segments, info = self._run(model, audio_path, language)
        except Exception as exc:
            raise TranscriptionError(f"transcription of {audio_path.name} failed: {exc}") from exc
        detected = language or getattr(info, "language", None)
        return segments, detected
