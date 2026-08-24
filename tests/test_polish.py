from __future__ import annotations

from ytscript.models import Segment
from ytscript.polish import (
    collapse_loops,
    is_boilerplate,
    normalize_punctuation,
    polish_segments,
    polish_text,
)
from ytscript.vocabulary import parse_vocabulary


def test_chinese_sentences_get_fullwidth_punctuation() -> None:
    assert normalize_punctuation("大家好,欢迎回来!今天呢?") == "大家好，欢迎回来！今天呢？"


def test_punctuation_that_is_not_chinese_is_left_alone() -> None:
    # Thousands separators, clock times and URLs all use the ASCII marks.
    assert normalize_punctuation("营收 1,250 亿") == "营收 1,250 亿"
    assert normalize_punctuation("美东时间 7:35") == "美东时间 7:35"
    assert normalize_punctuation("https://example.com/a,b") == "https://example.com/a,b"


def test_punctuation_converts_between_a_ticker_and_chinese() -> None:
    assert normalize_punctuation("看 AVGO,今天放量") == "看 AVGO，今天放量"


def test_a_looped_phrase_is_kept_once() -> None:
    segments = [Segment(float(i), float(i) + 1, "不要抢") for i in range(5)]
    collapsed = collapse_loops([Segment(0.0, 1.0, "开始"), *segments])
    assert [s.text for s in collapsed] == ["开始", "不要抢"]
    # The one that is kept spans the whole loop, so later timestamps still line up.
    assert collapsed[1].start == 0.0
    assert collapsed[1].end == 5.0


def test_saying_something_twice_is_not_a_loop() -> None:
    segments = [Segment(0.0, 1.0, "不要抢"), Segment(1.0, 2.0, "不要抢")]
    assert collapse_loops(segments) == segments


def test_subtitle_credits_are_boilerplate() -> None:
    assert is_boilerplate("字幕由Amara.org社区提供")
    assert is_boilerplate("请不吝点赞 订阅 转发")
    assert not is_boilerplate("今天的字幕由我自己写")


def test_polish_segments_runs_the_lot() -> None:
    vocabulary = parse_vocabulary("对中基金 => 对冲基金")
    segments = [
        Segment(0.0, 1.0, " 对中基金的仓位,很重 "),
        Segment(1.0, 2.0, "字幕由Amara.org社区提供"),
        Segment(2.0, 3.0, ""),
    ]
    assert polish_segments(segments, vocabulary) == [Segment(0.0, 1.0, "对冲基金的仓位，很重")]


def test_polish_segments_can_be_narrowed_to_one_job() -> None:
    segments = [Segment(0.0, 1.0, "对中基金,重仓")]
    polished = polish_segments(
        segments, parse_vocabulary("对中基金 => 对冲基金"), punctuation=False
    )
    assert polished[0].text == "对冲基金,重仓"


def test_polish_text_rewrites_a_whole_script() -> None:
    vocabulary = parse_vocabulary("飞班 => 费半")
    assert polish_text("飞班收跌,收盘", vocabulary) == "费半收跌，收盘"


def test_simplified_conversion_is_skipped_when_opencc_is_missing(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def no_opencc(name, *args, **kwargs):
        if name == "opencc":
            raise ImportError("no opencc here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_opencc)
    # The characters stay as they were rather than the run failing.
    assert polish_text("這個", simplified=True) == "這個"
