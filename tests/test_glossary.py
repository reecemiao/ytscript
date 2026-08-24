from __future__ import annotations

from ytscript.glossary import compile_glossary, correct, correct_segments
from ytscript.models import Segment


def test_longest_rule_wins_over_a_shorter_overlapping_one() -> None:
    rules = compile_glossary({"肺瓣": "费半", "肺瓣导体": "费城半导体"})
    assert correct("今天肺瓣导体和肺瓣", rules) == ("今天费城半导体和费半", 2)


def test_counts_every_occurrence_not_every_rule() -> None:
    rules = compile_glossary({"CIWV": "CRWV"})
    assert correct("CIWV涨了,CIWV又跌了", rules) == ("CRWV涨了,CRWV又跌了", 2)


def test_text_without_a_mishearing_is_left_alone() -> None:
    rules = compile_glossary({"CIWV": "CRWV"})
    assert correct("英伟达再创新高", rules) == ("英伟达再创新高", 0)


def test_segments_keep_their_timings_and_report_the_total() -> None:
    segments = [Segment(0.0, 2.0, "ISI超满了"), Segment(2.0, 4.0, "没有ISI背离")]
    corrected, total = correct_segments(segments, {"ISI": "RSI", "超满": "超买"})

    assert [s.text for s in corrected] == ["RSI超买了", "没有RSI背离"]
    assert [(s.start, s.end) for s in corrected] == [(0.0, 2.0), (2.0, 4.0)]
    assert total == 3


def test_an_empty_glossary_returns_the_segments_unchanged() -> None:
    segments = [Segment(0.0, 2.0, "原文")]
    corrected, total = correct_segments(segments, {})
    assert (corrected, total) == (segments, 0)
