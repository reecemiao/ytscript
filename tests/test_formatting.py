from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ytscript.formatting import (
    format_timestamp,
    group_paragraphs,
    output_stem,
    render_json,
    render_md,
    render_txt,
    slugify,
    write_outputs,
)
from ytscript.models import Segment, Transcript, Video

VIDEO = Video(
    id="abc123",
    title="How to: cook / rice!",
    url="https://www.youtube.com/watch?v=abc123",
    channel="Test Channel",
    upload_date=date(2024, 5, 1),
    duration=3725.0,
)
SEGMENTS = [
    Segment(0.0, 2.0, "Welcome back."),
    Segment(2.1, 4.0, "Today we cook rice."),
    Segment(9.0, 11.0, "Step one."),
]
TRANSCRIPT = Transcript(video=VIDEO, segments=SEGMENTS, language="en", backend="fake")


def test_format_timestamp() -> None:
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(3725) == "01:02:05"
    assert format_timestamp(-4) == "00:00:00"


def test_slugify_and_stem() -> None:
    assert slugify("How to: cook / rice!") == "How-to-cook-rice"
    assert output_stem(TRANSCRIPT) == "2024-05-01_How-to-cook-rice_abc123"


def test_group_paragraphs_splits_on_pause_after_sentence_end() -> None:
    paragraphs = group_paragraphs(SEGMENTS, gap=2.0)
    assert paragraphs == [
        (0.0, "Welcome back. Today we cook rice."),
        (9.0, "Step one."),
    ]


def test_group_paragraphs_keeps_mid_sentence_pauses_together() -> None:
    segments = [Segment(0.0, 2.0, "We were saying,"), Segment(9.0, 11.0, "before the pause.")]
    assert len(group_paragraphs(segments, gap=2.0)) == 1


def test_render_txt_has_header_and_optional_timestamps() -> None:
    plain = render_txt(TRANSCRIPT)
    assert plain.startswith("How to: cook / rice!\n")
    assert "Test Channel" in plain and "language: en" in plain
    assert "[00:00:00]" not in plain
    assert "[00:00:09] Step one." in render_txt(TRANSCRIPT, timestamps=True)


def test_render_md_and_json() -> None:
    markdown = render_md(TRANSCRIPT)
    assert markdown.startswith("# How to: cook / rice!")
    assert "- **Transcribed with:** fake" in markdown

    payload = json.loads(render_json(TRANSCRIPT))
    assert payload["video"]["id"] == "abc123"
    assert payload["language"] == "en"
    assert len(payload["segments"]) == 3
    assert payload["text"].startswith("Welcome back.")


def test_write_outputs(tmp_path: Path) -> None:
    paths = write_outputs(TRANSCRIPT, tmp_path / "scripts", formats=("txt", "json"))
    assert [p.name for p in paths] == [
        "2024-05-01_How-to-cook-rice_abc123.txt",
        "2024-05-01_How-to-cook-rice_abc123.json",
    ]
    assert all(p.is_file() for p in paths)


CHINESE = [
    Segment(0.0, 2.0, "今天我们来聊聊这个话题。"),
    Segment(2.1, 4.0, "先从背景开始。"),
    Segment(9.0, 11.0, "第一步。"),
]


def test_chinese_segments_join_without_spaces() -> None:
    paragraphs = group_paragraphs(CHINESE, gap=2.0)
    assert paragraphs == [
        (0.0, "今天我们来聊聊这个话题。先从背景开始。"),
        (9.0, "第一步。"),
    ]


def test_latin_words_still_get_their_spaces() -> None:
    assert group_paragraphs(SEGMENTS, gap=2.0)[0][1] == "Welcome back. Today we cook rice."


def test_mixed_chinese_and_latin_keeps_the_seam_readable() -> None:
    segments = [
        Segment(0.0, 2.0, "我们用"),
        Segment(2.0, 4.0, "Python"),
        Segment(4.0, 6.0, "写一个脚本。"),
    ]
    assert group_paragraphs(segments)[0][1] == "我们用 Python 写一个脚本。"


def test_transcript_text_joins_chinese_without_spaces() -> None:
    transcript = Transcript(video=VIDEO, segments=CHINESE, language="zh", backend="fake")
    assert transcript.text == "今天我们来聊聊这个话题。先从背景开始。第一步。"
