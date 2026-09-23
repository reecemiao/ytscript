from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ytscript.models import Video
from ytscript.vocabulary import (
    VocabularyError,
    _is_builtin_name,
    load_vocabulary,
    parse_vocabulary,
    seed_prompt,
)


def make_video(title: str = "美股 半导体 AVGO", description: str | None = None) -> Video:
    return Video(
        id="vid001",
        title=title,
        url="https://www.youtube.com/watch?v=vid001",
        channel="视野环球财经",
        upload_date=date(2026, 8, 22),
        description=description,
    )


def test_plain_lines_are_terms_and_arrows_are_corrections() -> None:
    vocabulary = parse_vocabulary("# a comment\n对中基金 => 对冲基金\nNVDA\n\n")
    assert vocabulary.terms == ("对冲基金", "NVDA")
    assert vocabulary.correct("今天对中基金的仓位") == "今天对冲基金的仓位"


def test_an_arrow_line_needs_both_sides() -> None:
    with pytest.raises(VocabularyError):
        parse_vocabulary("=> 对冲基金", source="glossary.txt")


def test_ascii_corrections_only_match_whole_words() -> None:
    vocabulary = parse_vocabulary("CTS => CDS")
    assert vocabulary.correct("它的CTS飙升") == "它的CDS飙升"
    assert vocabulary.correct("CTSX不是缩写") == "CTSX不是缩写"


def test_chinese_corrections_match_inside_a_run_of_characters() -> None:
    vocabulary = parse_vocabulary("飞班 => 费半")
    assert vocabulary.correct("今天飞班收跌") == "今天费半收跌"


def test_prompt_leads_with_seed_and_hashtags() -> None:
    vocabulary = parse_vocabulary("NVDA\nhedge fund")
    video = make_video(title="Ordinary title #AVGO", description="Ignored prose\n#TSM")
    prompt = vocabulary.prompt(video, seed="Seed. ")
    assert prompt is not None
    assert prompt.startswith("Seed.#AVGO #TSM")
    assert "hedge fund" in prompt
    assert "Ordinary title" not in prompt
    assert "Ignored prose" not in prompt


def test_hashtags_are_unicode_deduplicated_and_exclude_url_fragments() -> None:
    video = make_video(
        title="Title #AVGO",
        description="Prose\n#\u534a\u5bfc\u4f53 #AVGO #TSM, #AI_2026! "
        "https://example.com/#fragment plain#word",
    )
    assert video.hashtags == ["#AVGO", "#\u534a\u5bfc\u4f53", "#TSM", "#AI_2026"]
    assert parse_vocabulary("").prompt(video) == " ".join(video.hashtags)


@pytest.mark.parametrize("description", [None, "", "Ordinary description without tags"])
def test_missing_hashtags_do_not_fall_back_to_title_or_description(description) -> None:
    video = make_video(description=description)
    assert video.hashtags == []
    assert parse_vocabulary("").prompt(video) is None


def test_prompt_stays_inside_budget_and_prefers_terms_from_hashtags() -> None:
    vocabulary = parse_vocabulary("\n".join([f"filler{i:02d}" for i in range(40)] + ["AVGO"]))
    prompt = vocabulary.prompt(make_video(description="#AVGO"), seed="Seed.", max_chars=60)
    assert prompt is not None
    assert len(prompt) <= 60
    # The matching vocabulary term is retained as well as the hashtag itself.
    assert prompt.count("AVGO") == 2


def test_prompt_is_none_when_there_is_nothing_to_say() -> None:
    assert parse_vocabulary("").prompt(None, seed=None) is None


def test_seed_prompt_is_language_specific() -> None:
    assert seed_prompt("zh") == "以下是普通话的句子。"
    assert seed_prompt("zh-CN") == "以下是普通话的句子。"
    assert seed_prompt("en") is None
    assert seed_prompt(None) is None


def test_load_vocabulary_finds_the_builtin_and_a_path(tmp_path: Path) -> None:
    builtin = load_vocabulary("zh-finance")
    assert "对冲基金" in builtin.terms
    assert builtin.correct("自然负债表") == "资产负债表"

    path = tmp_path / "mine.txt"
    path.write_text("蜂蜜 => 蜂蜜柠檬\n", encoding="utf-8")
    assert load_vocabulary(path).correct("蜂蜜") == "蜂蜜柠檬"
    # A path out of a config file arrives as a string, not a Path.
    assert load_vocabulary(str(path)).correct("蜂蜜") == "蜂蜜柠檬"

    assert not load_vocabulary(None)
    assert not load_vocabulary("")


def test_only_a_bare_stem_names_a_builtin() -> None:
    # Checked on every platform: a Windows path holds no forward slash, so
    # looking for one alone read C:\scripts\mine.txt as the name of a built-in.
    assert _is_builtin_name("zh-finance")
    assert not _is_builtin_name(r"C:\scripts\mine.txt")
    assert not _is_builtin_name("scripts/mine.txt")
    assert not _is_builtin_name("mine.txt")


def test_load_vocabulary_says_what_it_expected() -> None:
    with pytest.raises(VocabularyError, match="zh-finance"):
        load_vocabulary("zh-finanace")
