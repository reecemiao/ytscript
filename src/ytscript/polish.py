"""Cleaning up what the model returns, before it is written out as a script.

Four things, all of them things Whisper does to Mandarin audio and none of them
things it can be talked out of with a prompt: it punctuates Chinese with ASCII
commas half the time, it loops a phrase when the audio underneath goes quiet, it
sometimes signs off with subtitle-credit boilerplate it learned from its training
data, and it spells domain words the way a general model would.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .models import Segment
from .vocabulary import Vocabulary

log = logging.getLogger("ytscript")

# Han, kana and the fullwidth punctuation that goes with them.
_CJK = r"　-〿぀-ヿ㐀-䶿一-鿿＀-･"

_FULLWIDTH = {",": "，", "?": "？", "!": "！", ";": "；", ":": "："}
_ASCII_PUNCTUATION = "".join(re.escape(mark) for mark in _FULLWIDTH)
# Only where a Chinese character is on one side or the other: "1,000" and the
# ":" in a URL keep the ASCII marks they need.
_AFTER_CJK = re.compile(rf"(?<=[{_CJK}])([{_ASCII_PUNCTUATION}])")
_BEFORE_CJK = re.compile(rf"([{_ASCII_PUNCTUATION}])(?=[{_CJK}])")

# Credit lines Whisper has been known to invent over music or silence. None of
# these showed up in the scripts this list was written against — it is a guard,
# not a fix, and a segment only goes if that is the whole of it.
_BOILERPLATE = tuple(
    re.compile(pattern)
    for pattern in (
        r"^字幕(由|志願者|志愿者).{0,30}(提供|製作|制作)[。.]?$",
        r"^.{0,20}(Amara\.org).{0,20}$",
        r"^請不吝點贊.*$",
        r"^请不吝点赞.*$",
        r"^(明鏡與點點欄目|明镜与点点栏目)[。.]?$",
    )
)

# How many identical segments in a row it takes to call it a loop rather than
# someone repeating themselves for effect.
LOOP_LENGTH = 3


def normalize_punctuation(text: str) -> str:
    """Give Chinese sentences the fullwidth marks they are written with."""
    text = _AFTER_CJK.sub(lambda m: _FULLWIDTH[m.group(1)], text)
    return _BEFORE_CJK.sub(lambda m: _FULLWIDTH[m.group(1)], text)


def is_boilerplate(text: str) -> bool:
    stripped = text.strip()
    return any(pattern.match(stripped) for pattern in _BOILERPLATE)


def collapse_loops(segments: list[Segment], length: int = LOOP_LENGTH) -> list[Segment]:
    """Keep one segment out of a run of ``length`` or more identical ones."""
    kept: list[Segment] = []
    run: list[Segment] = []

    def flush() -> None:
        if not run:
            return
        if len(run) >= length:
            # The loop ran from the first repeat to the end of the last one.
            kept.append(Segment(start=run[0].start, end=run[-1].end, text=run[0].text))
            log.info("dropped %d repeats of %r", len(run) - 1, run[0].text[:30])
        else:
            kept.extend(run)
        run.clear()

    for segment in segments:
        if run and segment.text.strip() == run[-1].text.strip():
            run.append(segment)
            continue
        flush()
        run.append(segment)
    flush()
    return kept


def _simplifier() -> Any | None:
    try:
        from opencc import OpenCC  # noqa: PLC0415 - optional dependency
    except ImportError:
        log.warning(
            "convert_to_simplified is on but opencc is not installed; leaving the "
            "characters as the model wrote them. Install it with 'uv sync --extra zh'"
        )
        return None
    return OpenCC("t2s")


def polish_segments(
    segments: list[Segment],
    vocabulary: Vocabulary | None = None,
    punctuation: bool = True,
    simplified: bool = False,
    loops: bool = True,
) -> list[Segment]:
    """Run the whole clean-up over a transcript's segments."""
    convert = _simplifier() if simplified else None
    polished: list[Segment] = []
    for segment in segments:
        text = segment.text.strip()
        if not text or is_boilerplate(text):
            continue
        if convert is not None:
            text = convert.convert(text)
        if vocabulary is not None:
            text = vocabulary.correct(text)
        if punctuation:
            text = normalize_punctuation(text)
        polished.append(Segment(start=segment.start, end=segment.end, text=text))
    return collapse_loops(polished) if loops else polished


def polish_text(
    text: str,
    vocabulary: Vocabulary | None = None,
    punctuation: bool = True,
    simplified: bool = False,
) -> str:
    """The same clean-up over a script that has already been written to disk."""
    convert = _simplifier() if simplified else None
    if convert is not None:
        text = convert.convert(text)
    if vocabulary is not None:
        text = vocabulary.correct(text)
    if punctuation:
        text = normalize_punctuation(text)
    return text
