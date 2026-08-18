"""Turning timed segments into a readable script."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Segment, Transcript

_UNSAFE = re.compile(r"[^\w\-. ]+", re.UNICODE)


def format_timestamp(seconds: float) -> str:
    total = int(max(0.0, seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def slugify(text: str, max_length: int = 60) -> str:
    cleaned = _UNSAFE.sub("", text).strip().replace(" ", "-")
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-.")
    return cleaned[:max_length] or "untitled"


def output_stem(transcript: Transcript) -> str:
    """``2024-05-01_video-title_VIDEOID`` — sorts by date, stays unique by id."""
    video = transcript.video
    parts = []
    if video.upload_date:
        parts.append(video.upload_date.isoformat())
    parts.append(slugify(video.title))
    parts.append(video.id)
    return "_".join(parts)


def group_paragraphs(segments: list[Segment], gap: float = 2.0) -> list[tuple[float, str]]:
    """Join consecutive segments into paragraphs, split on pauses and sentence ends."""
    paragraphs: list[tuple[float, str]] = []
    current: list[str] = []
    start = 0.0
    previous_end: float | None = None

    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        pause = previous_end is not None and (segment.start - previous_end) >= gap
        if current and pause and current[-1].endswith((".", "!", "?", "…", "。", "？", "！")):
            paragraphs.append((start, " ".join(current)))
            current = []
        if not current:
            start = segment.start
        current.append(text)
        previous_end = segment.end

    if current:
        paragraphs.append((start, " ".join(current)))
    return paragraphs


def render_txt(transcript: Transcript, timestamps: bool = False, gap: float = 2.0) -> str:
    video = transcript.video
    header = [video.title]
    meta = [video.url]
    if video.channel:
        meta.insert(0, video.channel)
    if video.upload_date:
        meta.append(video.upload_date.isoformat())
    if video.duration:
        meta.append(format_timestamp(video.duration))
    if transcript.language:
        meta.append(f"language: {transcript.language}")
    header.append(" | ".join(meta))
    header.append("=" * max(len(line) for line in header))

    body = [
        f"[{format_timestamp(start)}] {text}" if timestamps else text
        for start, text in group_paragraphs(transcript.segments, gap)
    ]
    return "\n".join(header) + "\n\n" + "\n\n".join(body) + "\n"


def render_md(transcript: Transcript, timestamps: bool = False, gap: float = 2.0) -> str:
    video = transcript.video
    lines = [f"# {video.title}", ""]
    if video.channel:
        lines.append(f"- **Channel:** {video.channel}")
    lines.append(f"- **URL:** {video.url}")
    if video.upload_date:
        lines.append(f"- **Published:** {video.upload_date.isoformat()}")
    if video.duration:
        lines.append(f"- **Duration:** {format_timestamp(video.duration)}")
    if transcript.language:
        lines.append(f"- **Language:** {transcript.language}")
    if transcript.backend:
        lines.append(f"- **Transcribed with:** {transcript.backend}")
    lines.append("")

    for start, text in group_paragraphs(transcript.segments, gap):
        if timestamps:
            lines.append(f"**[{format_timestamp(start)}]** {text}")
        else:
            lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_json(transcript: Transcript, timestamps: bool = False, gap: float = 2.0) -> str:
    video = transcript.video
    payload = {
        "video": {
            "id": video.id,
            "title": video.title,
            "url": video.url,
            "channel": video.channel,
            "upload_date": video.upload_date.isoformat() if video.upload_date else None,
            "duration": video.duration,
        },
        "language": transcript.language,
        "backend": transcript.backend,
        "text": transcript.text,
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text} for s in transcript.segments
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


RENDERERS = {"txt": render_txt, "md": render_md, "json": render_json}


def write_outputs(
    transcript: Transcript,
    output_dir: Path,
    formats: tuple[str, ...] = ("txt",),
    timestamps: bool = False,
    gap: float = 2.0,
) -> list[Path]:
    """Render the transcript in every requested format and return the paths written."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_stem(transcript)
    written: list[Path] = []
    for fmt in formats:
        renderer = RENDERERS.get(fmt)
        if renderer is None:
            raise ValueError(f"unknown output format {fmt!r}")
        path = output_dir / f"{stem}.{fmt}"
        path.write_text(renderer(transcript, timestamps, gap), encoding="utf-8")
        written.append(path)
    return written
