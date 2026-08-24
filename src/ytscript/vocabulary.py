"""Domain vocabulary: what the model should expect, and what it keeps getting wrong.

Whisper decodes a word it has been primed for far more reliably than one it has
not, and it accepts a short prompt to be primed with. Two things go in there: the
video's own title and description, which name the day's subject, and a glossary of
terms the channel says every episode. Whatever still comes out wrong is rewritten
afterwards from the same file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import Video

DATA_DIR = Path(__file__).parent / "data"

# Whisper conditions on at most 224 tokens of prompt and drops the rest without
# saying so. A Chinese character is roughly a token, so this is the safe ceiling.
MAX_PROMPT_CHARS = 200

_SEEDS = {
    # A simplified-character sentence settles which script the output is written in.
    "zh": "以下是普通话的句子。",
}

_ASCII = re.compile(r"^[\w&.\- ]+$", re.ASCII)
_TERM_SEPARATOR = "、"
_ARROW = re.compile(r"\s*(?:=>|->)\s*")


class VocabularyError(ValueError):
    """Raised when a vocabulary file is missing or a line cannot be read."""


def seed_prompt(language: str | None) -> str | None:
    """The stock priming sentence for a language, if there is one."""
    if not language:
        return None
    return _SEEDS.get(language.split("-")[0].lower())


@dataclass(frozen=True)
class Correction:
    """One ``wrong => right`` rewrite."""

    wrong: str
    right: str
    pattern: re.Pattern[str]

    @classmethod
    def build(cls, wrong: str, right: str) -> Correction:
        body = re.escape(wrong)
        if _ASCII.match(wrong):
            # "CDS" should not fire inside "CDSX"; Chinese has no such boundary, and
            # \b is no use here because Python counts Han characters as word ones.
            body = rf"(?<![A-Za-z0-9_]){body}(?![A-Za-z0-9_])"
        return cls(wrong=wrong, right=right, pattern=re.compile(body))

    def apply(self, text: str) -> str:
        # A plain replacement: the right-hand side is a word, not a regex template.
        return self.pattern.sub(lambda _: self.right, text)


@dataclass(frozen=True)
class Vocabulary:
    """Terms to prime the model with, and rewrites for what it still gets wrong."""

    terms: tuple[str, ...] = ()
    corrections: tuple[Correction, ...] = ()
    source: str = ""

    def __bool__(self) -> bool:
        return bool(self.terms or self.corrections)

    def correct(self, text: str) -> str:
        for correction in self.corrections:
            text = correction.apply(text)
        return text

    def prompt(
        self,
        video: Video | None = None,
        seed: str | None = None,
        max_chars: int = MAX_PROMPT_CHARS,
    ) -> str | None:
        """Build the priming text: seed sentence, this video's subject, then terms.

        Terms named in the title or description come first — they are the ones the
        episode actually says — and the rest fill whatever budget is left.
        """
        pieces: list[str] = []
        if seed:
            pieces.append(seed.strip())
        subject = _subject(video)
        if subject:
            pieces.append(subject)

        used = sum(len(piece) for piece in pieces)
        haystack = (subject or "").lower()
        ranked = sorted(self.terms, key=lambda term: term.lower() not in haystack)
        chosen: list[str] = []
        for term in ranked:
            cost = len(term) + len(_TERM_SEPARATOR)
            if used + cost > max_chars:
                continue
            chosen.append(term)
            used += cost
        if chosen:
            pieces.append(_TERM_SEPARATOR.join(chosen) + "。")

        prompt = "".join(pieces).strip()
        return prompt[:max_chars] or None


def _subject(video: Video | None) -> str:
    """The video's own words about itself: title first, then a slice of the blurb."""
    if video is None:
        return ""
    parts = [video.title.strip()] if video.title else []
    description = (video.description or "").strip()
    if description:
        # Descriptions run to link dumps and boilerplate; the opening line is the
        # part that says what the episode is about.
        first = description.splitlines()[0].strip()
        if first:
            parts.append(first)
    return " ".join(parts)


def parse_vocabulary(text: str, source: str = "") -> Vocabulary:
    """Read the ``term`` / ``wrong => right`` lines of a vocabulary file."""
    terms: list[str] = []
    corrections: list[Correction] = []
    seen: set[str] = set()

    def remember(term: str) -> None:
        if term and term not in seen:
            seen.add(term)
            terms.append(term)

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if _ARROW.search(line):
            wrong, right = (part.strip() for part in _ARROW.split(line, maxsplit=1))
            if not wrong or not right:
                raise VocabularyError(
                    f"{source or 'vocabulary'} line {number}: expected 'wrong => right'"
                )
            corrections.append(Correction.build(wrong, right))
            # What the correction produces is also what the model should expect.
            remember(right)
            continue
        remember(line)

    return Vocabulary(terms=tuple(terms), corrections=tuple(corrections), source=source)


def builtin_names() -> list[str]:
    return sorted(path.stem for path in DATA_DIR.glob("*.txt"))


def load_vocabulary(name: str | Path | None) -> Vocabulary:
    """Load a built-in vocabulary by name, or a file by path. ``None`` loads nothing."""
    if name is None or name == "":
        return Vocabulary()
    path = DATA_DIR / f"{name}.txt" if isinstance(name, str) and "/" not in name else Path(name)
    if not path.is_file():
        raise VocabularyError(
            f"no vocabulary {str(name)!r}: expected a file path or one of "
            f"{', '.join(builtin_names())}"
        )
    return parse_vocabulary(path.read_text(encoding="utf-8"), source=str(path))
