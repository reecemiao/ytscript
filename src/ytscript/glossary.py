"""Fixed-string corrections applied to a finished transcript.

Whisper mishears the words it has the least training data for — tickers, fund
names, an indicator called RSI — and `whisper_initial_prompt` only shifts the
odds. What it gets wrong, though, it usually gets wrong the same way every
time, so a plain search-and-replace finishes what the prompt starts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import Segment

Rules = tuple[tuple[str, str], ...]


def compile_glossary(mapping: Mapping[str, str]) -> Rules:
    """Order the rules longest match first.

    Otherwise a rule for "费半" would eat the middle of "费半导体" before the
    longer rule that was meant to catch it ever ran.
    """
    return tuple(sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True))


def correct(text: str, rules: Rules) -> tuple[str, int]:
    """Return the corrected text and how many occurrences were replaced."""
    replaced = 0
    for wrong, right in rules:
        found = text.count(wrong)
        if found:
            replaced += found
            text = text.replace(wrong, right)
    return text, replaced


def correct_segments(
    segments: Iterable[Segment], mapping: Mapping[str, str]
) -> tuple[list[Segment], int]:
    """Apply the glossary to every segment, counting the occurrences fixed."""
    rules = compile_glossary(mapping)
    total = 0
    corrected = []
    for segment in segments:
        text, replaced = correct(segment.text, rules)
        total += replaced
        corrected.append(
            segment if not replaced else Segment(start=segment.start, end=segment.end, text=text)
        )
    return corrected, total
