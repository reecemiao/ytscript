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
