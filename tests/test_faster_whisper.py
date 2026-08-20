"""The local backend, exercised against a fake faster-whisper."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from ytscript.config import Config
from ytscript.transcribers import build_transcriber
from ytscript.transcribers.base import TranscriptionError
from ytscript.transcribers.faster_whisper import FasterWhisperTranscriber

AUDIO = Path("video.m4a")


class FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start, self.end, self.text = start, end, text


class FakeInfo:
    language = "zh"


class FakeEngine:
    """Stands in for WhisperModel and for BatchedInferencePipeline alike."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.raises = raises

    def transcribe(self, audio: str, **kwargs):
        self.calls.append(kwargs)
        raises = self.raises

        def segments():
            # The real iterator is lazy: decoding, and any failure, happens here.
            if raises is not None:
                raise raises
            yield FakeSegment(0.0, 2.0, " 今天我们来聊聊。 ")
            yield FakeSegment(2.0, 4.0, "先从背景开始。")

        return segments(), FakeInfo()


def install_fake(
    monkeypatch: pytest.MonkeyPatch,
    sequential: FakeEngine | None = None,
    batched: FakeEngine | None = None,
    with_batching: bool = True,
) -> tuple[FakeEngine, FakeEngine]:
    """Put a fake ``faster_whisper`` module in place and hand back its engines."""
    sequential = sequential or FakeEngine()
    batched = batched or FakeEngine()
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = lambda *args, **kwargs: sequential
    if with_batching:
        module.BatchedInferencePipeline = lambda model: batched
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return sequential, batched


def test_batching_is_used_and_the_batch_size_is_passed_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sequential, batched = install_fake(monkeypatch)
    transcriber = FasterWhisperTranscriber(batch_size=8, initial_prompt="以下是普通话的句子。")

    segments, language = transcriber.transcribe(AUDIO, language="zh")

    assert [s.text for s in segments] == ["今天我们来聊聊。", "先从背景开始。"]
    assert language == "zh"
    assert sequential.calls == []
    assert batched.calls[0]["batch_size"] == 8
    assert batched.calls[0]["initial_prompt"] == "以下是普通话的句子。"
    assert batched.calls[0]["language"] == "zh"


def test_batch_size_of_one_stays_sequential(monkeypatch: pytest.MonkeyPatch) -> None:
    sequential, batched = install_fake(monkeypatch)
    FasterWhisperTranscriber(batch_size=1).transcribe(AUDIO)

    assert batched.calls == []
    # The sequential API has no batch_size parameter, so it must not be passed.
    assert "batch_size" not in sequential.calls[0]


def test_an_old_faster_whisper_falls_back_to_sequential(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sequential, _ = install_fake(monkeypatch, with_batching=False)
    segments, _ = FasterWhisperTranscriber(batch_size=8).transcribe(AUDIO)

    assert len(segments) == 2
    assert "batch_size" not in sequential.calls[0]
    assert "no batched pipeline" in caplog.text


def test_out_of_memory_retries_one_clip_at_a_time(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    oom = RuntimeError("CUDA failed with error out of memory")
    sequential, batched = install_fake(monkeypatch, batched=FakeEngine(raises=oom))

    segments, _ = FasterWhisperTranscriber(batch_size=8).transcribe(AUDIO)

    assert len(segments) == 2, "the retry should still produce a transcript"
    assert len(batched.calls) == 1 and len(sequential.calls) == 1
    assert "out of memory" in caplog.text


def test_other_failures_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    boom = RuntimeError("the audio file is corrupt")
    sequential, _ = install_fake(monkeypatch, batched=FakeEngine(raises=boom))

    with pytest.raises(TranscriptionError, match="corrupt"):
        FasterWhisperTranscriber(batch_size=8).transcribe(AUDIO)
    assert sequential.calls == []


def test_the_model_is_loaded_once_across_videos(monkeypatch: pytest.MonkeyPatch) -> None:
    loads = []
    sequential, batched = install_fake(monkeypatch)
    module = sys.modules["faster_whisper"]

    def counting_model(*args, **kwargs):
        loads.append(args)
        return sequential

    module.WhisperModel = counting_model
    transcriber = FasterWhisperTranscriber(batch_size=8)
    transcriber.transcribe(AUDIO)
    transcriber.transcribe(AUDIO)

    assert len(loads) == 1
    assert len(batched.calls) == 2


def test_a_missing_faster_whisper_says_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(TranscriptionError, match="not installed"):
        FasterWhisperTranscriber().transcribe(AUDIO)


def test_build_transcriber_passes_the_configuration_through() -> None:
    config = Config(
        channel="@x",
        whisper_model="large-v3",
        whisper_device="cuda",
        whisper_compute_type="float16",
        whisper_batch_size=4,
        whisper_initial_prompt="以下是普通话的句子。",
    )
    transcriber = build_transcriber(config)

    assert isinstance(transcriber, FasterWhisperTranscriber)
    assert transcriber.model_name == "large-v3"
    assert transcriber.device == "cuda"
    assert transcriber.compute_type == "float16"
    assert transcriber.batch_size == 4
    assert transcriber.initial_prompt == "以下是普通话的句子。"
