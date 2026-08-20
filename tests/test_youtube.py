from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ytscript.models import Video
from ytscript.youtube import (
    YouTubeClient,
    YouTubeError,
    _iter_entries,
    _mentions_membership,
    _to_video,
    channel_uploads_url,
    parse_browser_spec,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("@handle", "https://www.youtube.com/@handle/videos"),
        ("handle", "https://www.youtube.com/@handle/videos"),
        (
            "UCabcdefghijklmnopqrstuv",
            "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv/videos",
        ),
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


def test_to_video_flags_members_only_from_the_listing_badge() -> None:
    assert _to_video({"id": "a", "availability": "subscriber_only"}).members_only
    assert not _to_video({"id": "a", "availability": "public"}).members_only
    assert not _to_video({"id": "a"}).members_only


def test_membership_error_from_yt_dlp_is_recognised() -> None:
    assert _mentions_membership(
        "ERROR: [youtube] 58iGVbvDu9Q: Join this channel to get access to "
        "members-only content like this video, and other exclusive perks."
    )
    assert not _mentions_membership("ERROR: [youtube] abc: Video unavailable")


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("firefox", ("firefox", None, None, None)),
        ("Chrome", ("chrome", None, None, None)),
        ("chrome:Profile 2", ("chrome", "Profile 2", None, None)),
        ("chromium+gnomekeyring", ("chromium", None, "GNOMEKEYRING", None)),
        ("firefox:dev-edition::personal", ("firefox", "dev-edition", None, "personal")),
    ],
)
def test_parse_browser_spec(spec: str, expected: tuple[str | None, ...]) -> None:
    assert parse_browser_spec(spec) == expected


def test_parse_browser_spec_rejects_nonsense() -> None:
    with pytest.raises(YouTubeError, match="cookies_from_browser"):
        parse_browser_spec(":no-browser-name")


def test_cookie_settings_reach_yt_dlp(tmp_path: Path) -> None:
    client = YouTubeClient(
        cookies_file=tmp_path / "cookies.txt", cookies_from_browser="firefox:dev"
    )
    opts = client._base_opts()
    assert opts["cookiefile"] == str(tmp_path / "cookies.txt")
    assert opts["cookiesfrombrowser"] == ("firefox", "dev", None, None)
    assert client.signed_in

    assert "cookiefile" not in YouTubeClient()._base_opts()


def test_members_only_download_without_cookies_says_what_is_missing(tmp_path: Path) -> None:
    video = Video(id="x", title="T", url="https://y/watch?v=x", members_only=True)
    with pytest.raises(YouTubeError, match="members-only"):
        YouTubeClient().download_audio(video, tmp_path)
