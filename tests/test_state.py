from __future__ import annotations

from pathlib import Path

import pytest

from ytscript.state import State


def test_missing_file_gives_empty_state(tmp_path: Path) -> None:
    state = State.load(tmp_path / "state.json")
    assert state.is_empty
    assert not state.seen("abc")


def test_record_and_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "state.json"
    state = State.load(path)
    state.channel = "@chan"
    state.record("abc", title="Hello", outputs=["scripts/abc.txt"], missing=None)
    state.save()

    reloaded = State.load(path)
    assert reloaded.channel == "@chan"
    assert reloaded.seen("abc")
    entry = reloaded.videos["abc"]
    assert entry["title"] == "Hello"
    assert "transcribed_at" in entry
    assert "missing" not in entry


def test_corrupt_state_raises(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        State.load(path)


def test_failures_are_recorded_and_counted(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = State.load(path)
    state.record_failure("abc", "connection reset", title="Hello", url="https://y/abc")
    state.record_failure("abc", "connection reset again", title="Hello")
    state.save()

    entry = State.load(path).failures["abc"]
    assert entry["attempts"] == 2
    assert entry["error"] == "connection reset again"
    assert entry["url"] == "https://y/abc"
    assert entry["first_failed_at"] <= entry["last_failed_at"]


def test_a_finished_video_drops_off_the_failure_list(tmp_path: Path) -> None:
    state = State.load(tmp_path / "state.json")
    state.record_failure("abc", "boom")
    state.record("abc", title="Hello")
    assert state.failures == {}
    assert state.failed_videos() == []


def test_failed_videos_are_oldest_first_and_respect_the_cap(tmp_path: Path) -> None:
    state = State.load(tmp_path / "state.json")
    state.failures = {
        "new": {"error": "b", "attempts": 1, "first_failed_at": "2024-05-02T00:00:00+00:00"},
        "old": {"error": "a", "attempts": 3, "first_failed_at": "2024-05-01T00:00:00+00:00"},
    }
    assert [entry["id"] for entry in state.failed_videos()] == ["old", "new"]
    assert [entry["id"] for entry in state.failed_videos(max_attempts=3)] == ["new"]
    assert state.attempts("old") == 3 and state.attempts("missing") == 0


def test_forget_failures_clears_all_or_some(tmp_path: Path) -> None:
    state = State.load(tmp_path / "state.json")
    state.record_failure("a", "boom")
    state.record_failure("b", "boom")
    assert state.forget_failures(["a", "never-failed"]) == ["a"]
    assert state.forget_failures() == ["b"]
    assert state.failures == {}


def test_a_version_one_file_loads_without_failures(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"version": 1, "videos": {"abc": {}}}', encoding="utf-8")
    state = State.load(path)
    assert state.seen("abc") and state.failures == {}
