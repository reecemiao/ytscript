"""Wiring: list a channel, transcribe what is new, write the scripts."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from .config import Config
from .drive import DriveError, DriveFile, DriveUploader
from .formatting import write_outputs
from .models import RunReport, Transcript, Video
from .polish import polish_segments
from .state import State
from .transcribers import Transcriber, TranscriptionError, build_transcriber
from .vocabulary import load_vocabulary, seed_prompt
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


def _parse_date(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def video_from_failure(entry: dict[str, Any]) -> Video:
    """Rebuild the video a failure record describes, so a retry needs no fresh listing."""
    video_id = str(entry["id"])
    return Video(
        id=video_id,
        title=str(entry.get("title") or video_id),
        url=str(entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"),
        upload_date=_parse_date(entry.get("upload_date")),
        members_only=bool(entry.get("members_only")),
    )


class Pipeline:
    def __init__(
        self,
        config: Config,
        client: YouTubeClient | None = None,
        transcriber: Transcriber | None = None,
        uploader: DriveUploader | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.client = client or YouTubeClient(
            audio_format=config.audio_format,
            cookies_file=config.cookies_file,
            cookies_from_browser=config.cookies_from_browser,
            retries=config.download_retries,
            retry_backoff=config.retry_backoff,
            socket_timeout=config.socket_timeout,
        )
        self._transcriber = transcriber
        self._uploader = uploader
        self.vocabulary = load_vocabulary(config.vocabulary)
        # An unset prompt means "the stock sentence for this language"; an empty
        # one means the caller wants no seed at all.
        self.seed = (
            seed_prompt(config.language)
            if config.whisper_initial_prompt is None
            else config.whisper_initial_prompt
        )

    @property
    def transcriber(self) -> Transcriber:
        # Built on demand so `ytscript list` never needs a model on disk.
        if self._transcriber is None:
            self._transcriber = build_transcriber(self.config)
        return self._transcriber

    @property
    def uploader(self) -> DriveUploader:
        # Built on demand too: a run with drive_upload off never touches the connector.
        if self._uploader is None:
            self._uploader = DriveUploader.from_config(self.config)
        return self._uploader

    def prompt_for(self, video: Video) -> str | None:
        """The priming text this video is transcribed with."""
        subject = video if self.config.prompt_from_metadata else None
        return self.vocabulary.prompt(subject, seed=self.seed)

    def list_videos(self, limit: int | None = None) -> list[Video]:
        count = limit if limit is not None else self.config.check_limit
        return self.client.latest_videos(self.config.channel, count)

    def run(
        self,
        limit: int | None = None,
        dry_run: bool = False,
        on_progress: Callable[[str], None] | None = None,
        retry_failed: bool | None = None,
        only_failed: bool = False,
    ) -> RunReport:
        """Transcribe what the channel has that the state file does not.

        ``retry_failed`` (``retry_failed`` in the config when left unset) also picks up
        the videos an earlier run recorded as failed, however old they are.
        ``only_failed`` does just those, skipping the channel listing entirely, and
        ignores ``retry_max_attempts``.
        """
        config = self.config
        state = State.load(config.state_file)
        state.channel = state.channel or config.channel
        retry = only_failed or (config.retry_failed if retry_failed is None else retry_failed)

        if limit is None:
            limit = config.initial_backfill if state.is_empty else config.check_limit
        report = RunReport()

        videos = [] if only_failed else self.client.latest_videos(config.channel, limit)
        report.checked = len(videos)
        if not config.include_members_only:
            report.members_only = [video.id for video in videos if video.members_only]
            videos = [video for video in videos if not video.members_only]
        pending = select_videos(videos, state)
        report.skipped = [video.id for video in videos if state.seen(video.id)]

        if retry:
            # The failures come first: the oldest stuck video is the one most likely
            # to fall out of the listing window for good.
            pending = self._failed_videos(state, report, pending, force=only_failed) + pending
        if only_failed:
            report.checked = len(pending)

        if not pending:
            return report
        if dry_run:
            report.written = [f"{video.id} ({video.title})" for video in pending]
            return report

        # Sign in before the first download, so a stale token costs a second
        # rather than a whole backfill.
        if config.drive_upload:
            self.uploader.connect()

        with _audio_workspace(config) as audio_dir:
            for index, video in enumerate(pending, start=1):
                label = f"[{index}/{len(pending)}] {video.title}"
                if on_progress:
                    on_progress(label)
                try:
                    paths, uploads = self._process(video, audio_dir)
                except (YouTubeError, TranscriptionError, DriveError) as exc:
                    log.warning("%s failed: %s", video.id, exc)
                    report.failed.append((video.id, str(exc)))
                    # Written down so a later run can pick it up again, even once the
                    # video is older than check_limit: see run(retry_failed=True).
                    state.record_failure(
                        video.id,
                        str(exc),
                        title=video.title,
                        url=video.url,
                        upload_date=video.upload_date.isoformat() if video.upload_date else None,
                        members_only=video.members_only or None,
                    )
                    state.save()
                    continue
                report.written.extend(str(path) for path in paths)
                report.uploaded.extend(str(upload) for upload in uploads)
                drive = [{"id": f.id, "name": f.name, "link": f.link} for f in uploads]
                state.record(
                    video.id,
                    title=video.title,
                    url=video.url,
                    upload_date=video.upload_date.isoformat() if video.upload_date else None,
                    outputs=[str(path) for path in paths],
                    backend=self.transcriber.name,
                    drive=drive or None,
                )
                # Saved per video so an interrupted backfill does not redo work.
                state.save()
        return report

    def _failed_videos(
        self, state: State, report: RunReport, already: list[Video], force: bool
    ) -> list[Video]:
        """The videos on the failure list that this run should try again."""
        config = self.config
        cap = None if force else config.retry_max_attempts
        known = {video.id for video in already}
        pending: list[Video] = []
        for entry in state.failed_videos(max_attempts=cap):
            # One still inside the listing window is already lined up for its turn.
            if entry["id"] in known:
                continue
            video = video_from_failure(entry)
            if video.members_only and not config.include_members_only:
                report.members_only.append(video.id)
                continue
            pending.append(video)
            report.retried.append(video.id)
        if cap is not None:
            report.given_up = [
                entry["id"]
                for entry in state.failed_videos()
                if int(entry.get("attempts", 0)) >= cap
            ]
        return pending

    def _process(self, video: Video, audio_dir: Path) -> tuple[list[Path], list[DriveFile]]:
        config = self.config
        audio_path, video = self.client.download_audio(video, audio_dir)
        try:
            segments, language = self.transcriber.transcribe(
                audio_path, config.language, prompt=self.prompt_for(video)
            )
            if not segments:
                raise TranscriptionError("no speech was recognised in the audio")
            if config.polish or config.convert_to_simplified:
                segments = polish_segments(
                    segments,
                    vocabulary=self.vocabulary if config.polish else None,
                    punctuation=config.polish,
                    simplified=config.convert_to_simplified,
                    loops=config.polish,
                )
            if not segments:
                raise TranscriptionError("every recognised segment was dropped as boilerplate")
            transcript = Transcript(
                video=video,
                segments=segments,
                language=language or config.language,
                backend=self.transcriber.name,
            )
            paths = write_outputs(
                transcript,
                config.output_dir,
                formats=config.output_formats,
                timestamps=config.timestamps,
                gap=config.paragraph_gap,
            )
            uploads = self.uploader.upload_all(paths) if config.drive_upload else []
            return paths, uploads
        finally:
            if not config.keep_audio and config.audio_dir is None:
                audio_path.unlink(missing_ok=True)
