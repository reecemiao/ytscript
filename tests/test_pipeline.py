from __future__ import annotations

import json
from pathlib import Path

from fakes import FakeTranscriber, FakeYouTubeClient, make_videos
from ytscript.config import Config
from ytscript.pipeline import Pipeline, select_videos
from ytscript.state import State


def make_config(tmp_path: Path, **kwargs) -> Config:
    defaults = {
        "channel": "@testchannel",
        "language": "en",
        "output_dir": tmp_path / "scripts",
        "state_file": tmp_path / "state.json",
    }
    defaults.update(kwargs)
    return Config(**defaults)


def build(tmp_path: Path, videos, **kwargs):
    client = FakeYouTubeClient(videos)
    transcriber = FakeTranscriber()
    pipeline = Pipeline(make_config(tmp_path, **kwargs), client=client, transcriber=transcriber)
    return pipeline, client, transcriber


def test_select_videos_returns_unseen_oldest_first(tmp_path: Path) -> None:
    videos = make_videos(3)
    state = State(path=tmp_path / "s.json")
    state.record(videos[0].id)
    assert [v.id for v in select_videos(videos, state)] == ["vid002", "vid001"]


def test_first_run_backfills_thirty(tmp_path: Path) -> None:
    pipeline, client, transcriber = build(tmp_path, make_videos(40))
    report = pipeline.run()

    assert client.listed == [("@testchannel", 30)]
    assert report.checked == 30
    assert len(transcriber.calls) == 30
    assert len(list((tmp_path / "scripts").glob("*.txt"))) == 30
    assert len(State.load(tmp_path / "state.json").videos) == 30


def test_later_runs_only_check_the_newest_few(tmp_path: Path) -> None:
    videos = make_videos(10)
    pipeline, client, _ = build(tmp_path, videos, initial_backfill=3, check_limit=5)
    pipeline.run()
    assert client.listed[-1] == ("@testchannel", 3)

    # A newer video appears on the channel.
    fresh = make_videos(1, start=100)
    client.videos = fresh + videos
    report = pipeline.run()

    # The window now covers vid100, the three already-done ones and vid003,
    # which the smaller backfill never reached.
    assert client.listed[-1] == ("@testchannel", 5)
    assert report.checked == 5
    assert report.skipped == ["vid000", "vid001", "vid002"]
    assert len(report.written) == 2
    assert any("vid100" in path for path in report.written)
    assert any("vid003" in path for path in report.written)


def test_run_with_nothing_new_writes_nothing(tmp_path: Path) -> None:
    pipeline, _, transcriber = build(tmp_path, make_videos(2), initial_backfill=2)
    pipeline.run()
    calls = len(transcriber.calls)
    report = pipeline.run()
    assert report.written == []
    assert len(transcriber.calls) == calls


def test_language_is_passed_to_the_backend(tmp_path: Path) -> None:
    pipeline, _, transcriber = build(tmp_path, make_videos(1), language="ja", initial_backfill=1)
    pipeline.run()
    assert transcriber.calls[0][1] == "ja"

    other = tmp_path / "auto"
    pipeline, _, transcriber = build(
        other,
        make_videos(1),
        language="auto",
        initial_backfill=1,
        output_dir=other / "scripts",
        state_file=other / "state.json",
    )
    pipeline.run()
    assert transcriber.calls[0][1] is None


def test_failures_are_reported_and_not_recorded(tmp_path: Path) -> None:
    client = FakeYouTubeClient(make_videos(3))
    transcriber = FakeTranscriber(fail_on={"vid001"})
    pipeline = Pipeline(
        make_config(tmp_path, initial_backfill=3), client=client, transcriber=transcriber
    )
    report = pipeline.run()

    assert [vid for vid, _ in report.failed] == ["vid001"]
    assert len(report.written) == 2
    state = State.load(tmp_path / "state.json")
    assert not state.seen("vid001")
    assert state.seen("vid000") and state.seen("vid002")


def test_failed_video_is_retried_on_the_next_run(tmp_path: Path) -> None:
    client = FakeYouTubeClient(make_videos(2))
    transcriber = FakeTranscriber(fail_on={"vid001"})
    config = make_config(tmp_path, initial_backfill=2, check_limit=2)
    Pipeline(config, client=client, transcriber=transcriber).run()

    healthy = FakeTranscriber()
    report = Pipeline(config, client=client, transcriber=healthy).run()
    assert [call[0].stem for call in healthy.calls] == ["vid001"]
    assert len(report.written) == 1


def test_dry_run_downloads_nothing(tmp_path: Path) -> None:
    pipeline, client, transcriber = build(tmp_path, make_videos(2), initial_backfill=2)
    report = pipeline.run(dry_run=True)

    assert client.downloaded == [] and transcriber.calls == []
    assert len(report.written) == 2
    assert not (tmp_path / "state.json").exists()


def test_explicit_limit_overrides_the_configured_one(tmp_path: Path) -> None:
    pipeline, client, _ = build(tmp_path, make_videos(10), initial_backfill=30)
    pipeline.run(limit=2)
    assert client.listed == [("@testchannel", 2)]


def test_multiple_output_formats_and_audio_cleanup(tmp_path: Path) -> None:
    pipeline, _, _ = build(
        tmp_path,
        make_videos(1),
        initial_backfill=1,
        output_formats=("txt", "json"),
        timestamps=True,
    )
    pipeline.run()

    scripts = sorted(p.name for p in (tmp_path / "scripts").iterdir())
    assert scripts == ["2024-05-01_Episode-0_vid000.json", "2024-05-01_Episode-0_vid000.txt"]
    payload = json.loads((tmp_path / "scripts" / scripts[0]).read_text(encoding="utf-8"))
    assert payload["backend"] == "fake"
    assert "[00:00:00]" in (tmp_path / "scripts" / scripts[1]).read_text(encoding="utf-8")


def test_keep_audio_leaves_the_file_behind(tmp_path: Path) -> None:
    pipeline, _, _ = build(tmp_path, make_videos(1), initial_backfill=1, keep_audio=True)
    pipeline.run()
    assert (tmp_path / "scripts" / "audio" / "vid000.m4a").is_file()
