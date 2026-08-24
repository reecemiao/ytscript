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
    is_transient,
    parse_browser_spec,
)

# What yt-dlp prints when YouTube drops the connection part-way through, here on a
# Chinese Windows: "the remote host forcibly closed an existing connection".
CONNECTION_RESET = (
    "[download] Got error: ('Connection aborted.', "
    "ConnectionResetError(10054, '远程主机强迫关闭了一个现有的连接。', None, 10054, None))"
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


def test_a_dropped_connection_counts_as_transient() -> None:
    assert is_transient(RuntimeError(CONNECTION_RESET))
    assert is_transient(ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。"))
    assert is_transient(TimeoutError("The read operation timed out"))
    assert is_transient(OSError("HTTP Error 503: Service Unavailable"))


def test_a_refusal_is_not_transient() -> None:
    assert not is_transient(RuntimeError("Video unavailable"))
    assert not is_transient(RuntimeError("Join this channel to get access to members-only content"))


def test_transient_causes_are_seen_through_the_wrapper() -> None:
    try:
        try:
            raise ConnectionResetError(10054, "closed")
        except ConnectionResetError as reset:
            raise RuntimeError("could not download audio for x") from reset
    except RuntimeError as exc:
        assert is_transient(exc)


def test_a_dropped_download_is_tried_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = Video(id="x", title="T", url="https://y/watch?v=x")
    waits: list[float] = []
    client = YouTubeClient(retries=2, retry_backoff=1.0, sleep=waits.append)
    attempts: list[str] = []

    def flaky(video: Video, dest_dir: Path) -> tuple[Path, Video]:
        attempts.append(video.id)
        if len(attempts) < 3:
            raise YouTubeError(
                f"could not download audio for x: {CONNECTION_RESET}", transient=True
            )
        return dest_dir / "x.m4a", video

    monkeypatch.setattr(client, "_download_audio_once", flaky)
    path, got = client.download_audio(video, tmp_path)

    assert path == tmp_path / "x.m4a" and got is video
    assert len(attempts) == 3
    # The pause widens, so a blip costs a second and an outage is not hammered.
    assert waits == [1.0, 2.0]


def test_retries_run_out_and_the_last_error_is_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = Video(id="x", title="T", url="https://y/watch?v=x")
    attempts: list[str] = []
    client = YouTubeClient(retries=1, retry_backoff=0.0, sleep=lambda _: None)

    def always_drops(video: Video, dest_dir: Path) -> tuple[Path, Video]:
        attempts.append(video.id)
        raise YouTubeError("could not download audio for x: connection reset", transient=True)

    monkeypatch.setattr(client, "_download_audio_once", always_drops)
    with pytest.raises(YouTubeError, match="connection reset"):
        client.download_audio(video, tmp_path)
    assert len(attempts) == 2


def test_a_refused_download_is_not_tried_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = Video(id="x", title="T", url="https://y/watch?v=x")
    attempts: list[str] = []
    client = YouTubeClient(retries=3, retry_backoff=0.0, sleep=lambda _: None)

    def refused(video: Video, dest_dir: Path) -> tuple[Path, Video]:
        attempts.append(video.id)
        raise YouTubeError("x is members-only; sign in as a member")

    monkeypatch.setattr(client, "_download_audio_once", refused)
    with pytest.raises(YouTubeError, match="members-only"):
        client.download_audio(video, tmp_path)
    assert len(attempts) == 1


def test_a_dropped_listing_is_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    client = YouTubeClient(retries=1, retry_backoff=0.0, sleep=lambda _: None)
    attempts: list[int] = []

    def flaky(channel: str, limit: int) -> list[Video]:
        attempts.append(limit)
        if len(attempts) == 1:
            raise YouTubeError("could not list videos: connection aborted", transient=True)
        return [Video(id="a", title="A", url="https://y/watch?v=a")]

    monkeypatch.setattr(client, "_list_videos_once", flaky)
    assert [video.id for video in client.latest_videos("@chan", 5)] == ["a"]
    assert attempts == [5, 5]


def test_retry_settings_reach_yt_dlp() -> None:
    opts = YouTubeClient(retries=7, socket_timeout=12.0)._base_opts()
    assert opts["retries"] == 7 and opts["fragment_retries"] == 7
    assert opts["socket_timeout"] == 12.0
    assert opts["continuedl"] is True
