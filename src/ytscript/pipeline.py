"""Wiring: list a channel, transcribe what is new, write the scripts."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from pathlib import Path

from .config import Config
from .formatting import write_outputs
from .models import RunReport, Transcript, Video
from .state import State
from .transcribers import Transcriber, TranscriptionError, build_transcriber
from .youtube import YouTubeClient, YouTubeError

log = logging.getLogger("ytscript")


@contextmanager
def _audio_workspace(config: Config):
    if config.audio_dir is not None:
        config.audio_dir.mkdir(parents=True, exist_ok=True)
        yield config.audio_dir
    elif config.keep_audio:
        directory = config.output_dir / "audio"
        directory.mkdir(parents=True, exist_ok=True)
        yield directory
    else:
        with tempfile.TemporaryDirectory(prefix="ytscript-") as tmp:
            yield Path(tmp)


def select_videos(videos: Iterable[Video], state: State) -> list[Video]:
    """Oldest first, so an interrupted backfill resumes sensibly."""
    pending = [video for video in videos if not state.seen(video.id)]
    pending.reverse()
    return pending


class Pipeline:
    def __init__(
        self,
        config: Config,
        client: YouTubeClient | None = None,
        transcriber: Transcriber | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.client = client or YouTubeClient(
            audio_format=config.audio_format,
            cookies_file=config.cookies_file,
            cookies_from_browser=config.cookies_from_browser,
        )
        self._transcriber = transcriber

    @property
    def transcriber(self) -> Transcriber:
        # Built on demand so `ytscript list` never needs a model on disk.
        if self._transcriber is None:
            self._transcriber = build_transcriber(self.config)
        return self._transcriber

    def list_videos(self, limit: int | None = None) -> list[Video]:
        count = limit if limit is not None else self.config.check_limit
        return self.client.latest_videos(self.config.channel, count)

    def run(
        self,
        limit: int | None = None,
        dry_run: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> RunReport:
        config = self.config
        state = State.load(config.state_file)
        state.channel = state.channel or config.channel

        if limit is None:
            limit = config.initial_backfill if state.is_empty else config.check_limit
        report = RunReport()

        videos = self.client.latest_videos(config.channel, limit)
        report.checked = len(videos)
        if not config.include_members_only:
            report.members_only = [video.id for video in videos if video.members_only]
            videos = [video for video in videos if not video.members_only]
        pending = select_videos(videos, state)
        report.skipped = [video.id for video in videos if state.seen(video.id)]

        if not pending:
            return report
        if dry_run:
            report.written = [f"{video.id} ({video.title})" for video in pending]
            return report

        with _audio_workspace(config) as audio_dir:
            for index, video in enumerate(pending, start=1):
                label = f"[{index}/{len(pending)}] {video.title}"
                if on_progress:
                    on_progress(label)
                try:
                    paths = self._process(video, audio_dir)
                except (YouTubeError, TranscriptionError) as exc:
                    log.warning("%s failed: %s", video.id, exc)
                    report.failed.append((video.id, str(exc)))
                    continue
                report.written.extend(str(path) for path in paths)
                state.record(
                    video.id,
                    title=video.title,
                    url=video.url,
                    upload_date=video.upload_date.isoformat() if video.upload_date else None,
                    outputs=[str(path) for path in paths],
                    backend=self.transcriber.name,
                )
                # Saved per video so an interrupted backfill does not redo work.
                state.save()
        return report

    def _process(self, video: Video, audio_dir: Path) -> list[Path]:
        config = self.config
        audio_path, video = self.client.download_audio(video, audio_dir)
        try:
            segments, language = self.transcriber.transcribe(audio_path, config.language)
            if not segments:
                raise TranscriptionError("no speech was recognised in the audio")
            transcript = Transcript(
                video=video,
                segments=segments,
                language=language or config.language,
                backend=self.transcriber.name,
            )
            return write_outputs(
                transcript,
                config.output_dir,
                formats=config.output_formats,
                timestamps=config.timestamps,
                gap=config.paragraph_gap,
            )
        finally:
            if not config.keep_audio and config.audio_dir is None:
                audio_path.unlink(missing_ok=True)
