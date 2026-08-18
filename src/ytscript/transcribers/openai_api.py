"""Hosted speech-to-text through the OpenAI audio transcription endpoint."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..models import Segment
from .base import TranscriptionError

# The endpoint rejects uploads above 25 MB.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class OpenAITranscriber:
    """Uploads the audio file and returns the segments the API reports."""

    name = "openai"

    def __init__(
        self,
        model: str = "whisper-1",
        api_key_env: str = "OPENAI_API_KEY",
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.api_key_env = api_key_env
        self._api_key = api_key
        self._client: Any = None

    def _load_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI  # noqa: PLC0415 - optional dependency
        except ImportError as exc:
            raise TranscriptionError(
                "the openai package is not installed; install it with "
                "'pip install \"ytscript[openai]\"' or switch backend to 'faster-whisper'"
            ) from exc
        api_key = self._api_key or os.environ.get(self.api_key_env)
        if not api_key:
            raise TranscriptionError(f"{self.api_key_env} is not set")
        self._client = OpenAI(api_key=api_key)
        return self._client

    def transcribe(
        self, audio_path: Path, language: str | None = None
    ) -> tuple[list[Segment], str | None]:
        client = self._load_client()
        size = audio_path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            raise TranscriptionError(
                f"{audio_path.name} is {size / 1_048_576:.1f} MB, over the "
                f"{MAX_UPLOAD_BYTES // 1_048_576} MB upload limit; use the "
                "faster-whisper backend for long videos"
            )
        kwargs: dict[str, Any] = {
            "model": self.model,
            "response_format": "verbose_json",
            "timestamp_granularities": ["segment"],
        }
        if language:
            kwargs["language"] = language
        try:
            with audio_path.open("rb") as handle:
                response = client.audio.transcriptions.create(file=handle, **kwargs)
        except Exception as exc:
            raise TranscriptionError(f"transcription of {audio_path.name} failed: {exc}") from exc

        payload = response if isinstance(response, dict) else _to_dict(response)
        raw_segments = payload.get("segments") or []
        segments = [
            Segment(
                start=float(item.get("start", 0.0)),
                end=float(item.get("end", 0.0)),
                text=str(item.get("text", "")).strip(),
            )
            for item in raw_segments
        ]
        if not segments and payload.get("text"):
            segments = [Segment(start=0.0, end=0.0, text=str(payload["text"]).strip())]
        return segments, language or payload.get("language")


def _to_dict(response: Any) -> dict[str, Any]:
    for attr in ("model_dump", "to_dict", "dict"):
        method = getattr(response, attr, None)
        if callable(method):
            try:
                return dict(method())
            except Exception:  # pragma: no cover - SDK version differences
                continue
    return {
        "text": getattr(response, "text", ""),
        "language": getattr(response, "language", None),
        "segments": getattr(response, "segments", None) or [],
    }
