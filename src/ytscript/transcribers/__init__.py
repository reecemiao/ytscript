"""Speech-to-text backends."""

from __future__ import annotations

from ..config import Config
from .base import Transcriber, TranscriptionError
from .faster_whisper import FasterWhisperTranscriber
from .openai_api import OpenAITranscriber

__all__ = [
    "FasterWhisperTranscriber",
    "OpenAITranscriber",
    "Transcriber",
    "TranscriptionError",
    "build_transcriber",
]


def build_transcriber(config: Config) -> Transcriber:
    """Instantiate the backend named in the configuration."""
    if config.backend == "faster-whisper":
        return FasterWhisperTranscriber(
            model=config.whisper_model,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
        )
    if config.backend == "openai":
        return OpenAITranscriber(
            model=config.openai_model,
            api_key_env=config.openai_api_key_env,
        )
    raise TranscriptionError(f"unknown backend {config.backend!r}")
