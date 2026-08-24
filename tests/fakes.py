"""Stand-ins for YouTube and the speech-to-text backend."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from ytscript.models import Segment, Video


def make_videos(count: int, start: int = 0) -> list[Video]:
    """Newest first, the same order the real listing returns."""
    base = date(2024, 5, 1)
    return [
        Video(
            id=f"vid{start + i:03d}",
            title=f"Episode {start + i}",
            url=f"https://www.youtube.com/watch?v=vid{start + i:03d}",
            channel="Test Channel",
            upload_date=base - timedelta(days=start + i),
            duration=60.0,
        )
        for i in range(count)
    ]


class FakeYouTubeClient:
    def __init__(self, videos: list[Video]) -> None:
        self.videos = videos
        self.listed: list[tuple[str, int]] = []
        self.downloaded: list[str] = []

    def latest_videos(self, channel: str, limit: int) -> list[Video]:
        self.listed.append((channel, limit))
        return self.videos[:limit]

    def download_audio(self, video: Video, dest_dir: Path) -> tuple[Path, Video]:
        self.downloaded.append(video.id)
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"{video.id}.m4a"
        path.write_bytes(b"fake audio")
        return path, video


class FakeTranscriber:
    name = "fake"

    def __init__(self, language: str | None = "en", fail_on: set[str] | None = None) -> None:
        self.language = language
        self.fail_on = fail_on or set()
        self.calls: list[tuple[Path, str | None]] = []

    def transcribe(self, audio_path: Path, language: str | None = None):
        self.calls.append((audio_path, language))
        if audio_path.stem in self.fail_on:
            from ytscript.transcribers import TranscriptionError

            raise TranscriptionError("backend exploded")
        return (
            [
                Segment(0.0, 2.0, "Hello there."),
                Segment(6.0, 8.0, "Second paragraph starts here."),
            ],
            language or self.language,
        )


class FakeDriveUploader:
    """Records what a run would have pushed to Drive, without any Google client."""

    name = "google-drive"

    def __init__(self, fail_on: set[str] | None = None, connect_error: str | None = None) -> None:
        self.fail_on = fail_on or set()
        self.connect_error = connect_error
        self.connected = 0
        self.uploaded: list[str] = []

    def connect(self, interactive: bool = False) -> None:
        self.connected += 1
        if self.connect_error:
            from ytscript.drive import DriveError

            raise DriveError(self.connect_error)

    @property
    def folder(self) -> str | None:
        return "folder-id"

    def upload(self, path: Path):
        from ytscript.drive import DriveError, DriveFile

        path = Path(path)
        if path.name in self.fail_on:
            raise DriveError("drive said no")
        self.uploaded.append(path.name)
        return DriveFile(
            id=f"file-{len(self.uploaded)}",
            name=path.name,
            link=f"https://drive.google.com/file/d/file-{len(self.uploaded)}/view",
        )

    def upload_all(self, paths: list[Path]):
        return [self.upload(path) for path in paths]
