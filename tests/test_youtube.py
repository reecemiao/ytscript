from __future__ import annotations

from datetime import date

import pytest
from ytscript.youtube import YouTubeError, _iter_entries, _to_video, channel_uploads_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("@handle", "https://www.youtube.com/@handle/videos"),
        ("handle", "https://www.youtube.com/@handle/videos"),
        ("UCabcdefghijklmnopqrstuv", "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv/videos"),
        ("https://www.youtube.com/@handle", "https://www.youtube.com/@handle/videos"),
        ("https://www.youtube.com/@handle/videos", "https://www.youtube.com/@handle/videos"),
        ("https://www.youtube.com/@handle/streams", "https://www.youtube.com/@handle/streams"),
        ("youtube.com/c/Name", "https://youtube.com/c/Name/videos"),
    ],
)
def test_channel_uploads_url(value: str, expected: str) -> None:
    assert channel_uploads_url(value) == expected


def test_channel_uploads_url_rejects_empty() -> None:
    with pytest.raises(YouTubeError):
        channel_uploads_url("   ")


def test_to_video_reads_upload_date_and_falls_back_to_watch_url() -> None:
    video = _to_video({"id": "abc123", "title": "T", "upload_date": "20240501"})
    assert video.upload_date == date(2024, 5, 1)
    assert video.url == "https://www.youtube.com/watch?v=abc123"


def test_to_video_ignores_unparsable_date() -> None:
    assert _to_video({"id": "x", "upload_date": "not-a-date"}).upload_date is None


def test_iter_entries_flattens_nested_tabs() -> None:
    info = {
        "_type": "playlist",
        "entries": [
            {"_type": "playlist", "entries": [{"id": "a"}, {"id": "b"}]},
            {"id": "c"},
            None,
        ],
    }
    assert [entry["id"] for entry in _iter_entries(info)] == ["a", "b", "c"]
