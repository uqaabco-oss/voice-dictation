"""Deterministic, conservative cleanup of raw Whisper transcripts.

The cleanup only ever deletes filler words and tidies punctuation and spacing.
It never rewrites or reorders words, so a real word is never lost:

* Fillers: ``um``, ``uh``, ``erm`` and their stretched spellings (``umm``,
  ``uhh``, ``uhm``...). An ALL-CAPS token such as ``UM`` is treated as an
  acronym and kept, and hyphenated words such as ``uh-huh`` / ``uh-oh`` are
  kept.
* ``you know`` is removed only where it is clearly a filler: at the start of a
  sentence or right after a comma, and followed by a comma, a full stop, an
  exclamation mark or the end of the text. ``you know what I mean``,
  ``as you know``, ``do you know`` and the tag question ``..., you know?`` are
  all left alone.
* Commas around a removed filler belong to it ("I was, um, thinking" becomes
  "I was thinking"), except after a sentence-opening word such as "So" or
  "Okay" where a comma is normal style ("So, um, yes" becomes "So, yes").
* Whitespace is collapsed, stray spaces before punctuation are removed, the
  first letter is capitalised and the text ends with terminal punctuation.
"""

from __future__ import annotations

import re

_OPENERS = "\"'“‘([{"
_CLOSERS = "\"'”’)]}"
_MARKS = ",.;:!?…-–—"
_SOLO_PUNCT = set(",.;:!?…")

_TOKEN = re.compile(
    rf"(?P<lead>[{re.escape(_OPENERS)}]*)"
    rf"(?P<core>.*?)"
    rf"(?P<trail>[{re.escape(_MARKS + _CLOSERS)}]*)",
    re.DOTALL,
)
_FILLER = re.compile(r"u+h*m+|u+h+|e+r+m+", re.IGNORECASE)

_SENTENCE_END = frozenset({".", "!", "?"})
# Punctuation that may follow "you know" for it to count as a filler.
_YOU_KNOW_AFTER = frozenset({",", ".", "!", "...", ";", "-"})
# Words that conventionally take a comma when they open a sentence.
_INTRO_WORDS = frozenset(
    {
        "actually",
        "alright",
        "also",
        "anyway",
        "basically",
        "first",
        "hello",
        "hey",
        "hi",
        "honestly",
        "no",
        "nope",
        "now",
        "oh",
        "ok",
        "okay",
        "right",
        "so",
        "sure",
        "thanks",
        "well",
        "yeah",
        "yep",
        "yes",
    }
)


def clean_transcript(text: str, *, remove_fillers: bool = True) -> str:
    """Return a tidied version of ``text``, or ``""`` if nothing is left.

    Pass ``remove_fillers=False`` for non-English text, where words like "um"
    can be real words (German "um" means "around").
    """
    tokens = _attach_solo_punctuation(text.split())
    if remove_fillers:
        tokens = _drop_fillers(tokens)
    tokens = _drop_leading_punctuation(tokens)
    if not tokens:
        return ""
    result = " ".join(tokens)
    if not any(ch.isalnum() for ch in result):
        return ""
    tokens = result.split(" ")
    first = next(i for i, tok in enumerate(tokens) if _split(tok)[1])
    tokens[first] = _capitalize(tokens[first])
    return _ensure_terminal_punctuation(" ".join(tokens))


def _split(token: str) -> tuple[str, str, str]:
    match = _TOKEN.fullmatch(token)
    assert match is not None  # the pattern can match any string
    return match["lead"], match["core"], match["trail"]


def _mark(trail: str) -> str | None:
    """Classify trailing punctuation; ``None`` means it ends in a quote or bracket."""
    if not trail:
        return ""
    if any(ch in _CLOSERS for ch in trail):
        return None
    for mark in ("?", "!"):
        if mark in trail:
            return mark
    if "…" in trail or ".." in trail:
        return "..."
    for mark in (".", ";", ":", ","):
        if mark in trail:
            return mark
    return "-"


def _token_mark(token: str) -> str | None:
    return _mark(_split(token)[2])


def _attach_solo_punctuation(tokens: list[str]) -> list[str]:
    """Join punctuation-only tokens to the previous word ("hi , there" -> "hi, there")."""
    out: list[str] = []
    for tok in tokens:
        if out and all(ch in _SOLO_PUNCT for ch in tok):
            out[-1] += tok
        else:
            out.append(tok)
    return out


def _drop_leading_punctuation(tokens: list[str]) -> list[str]:
    start = 0
    while start < len(tokens) and all(ch in _MARKS for ch in tokens[start]):
        start += 1
    return tokens[start:]


def _at_sentence_start(out: list[str]) -> bool:
    return not out or _token_mark(out[-1]) in _SENTENCE_END


def _filler_length(tokens: list[str], i: int, out: list[str]) -> int:
    """Number of tokens a filler starting at ``tokens[i]`` spans (0 if none)."""
    lead, core, trail = _split(tokens[i])
    if lead or not core or _mark(trail) is None:
        return 0
    if _FILLER.fullmatch(core):
        is_acronym = len(core) > 1 and core.isupper()
        return 0 if is_acronym else 1
    if core.lower() != "you" or trail or i + 1 >= len(tokens):
        return 0
    lead2, core2, trail2 = _split(tokens[i + 1])
    after = _mark(trail2)
    if lead2 or core2.lower() != "know" or after is None:
        return 0
    is_last = i + 2 == len(tokens)
    if not (after in _YOU_KNOW_AFTER or (after == "" and is_last)):
        return 0
    if _at_sentence_start(out) or _token_mark(out[-1]) == ",":
        return 2
    return 0


def _drop_fillers(tokens: list[str]) -> list[str]:
    out: list[str] = []
    capitalize_next = False
    i = 0
    while i < len(tokens):
        length = _filler_length(tokens, i, out)
        if length:
            filler_mark = _token_mark(tokens[i + length - 1]) or ""
            if _at_sentence_start(out):
                capitalize_next = True
            else:
                out[-1] = _merge_into_previous(out, filler_mark)
            i += length
            continue
        token = tokens[i]
        if capitalize_next:
            token = _capitalize(token)
            capitalize_next = False
        out.append(token)
        i += 1
    return out


def _merge_into_previous(out: list[str], filler_mark: str) -> str:
    """Fold the punctuation of a removed filler into the word before it."""
    prev = out[-1]
    lead, core, trail = _split(prev)
    prev_mark = _mark(trail)
    if not core:
        return prev
    if prev_mark is None:  # ends in a quote or bracket: leave its punctuation alone
        return prev + filler_mark if filler_mark in _SENTENCE_END else prev
    if prev_mark not in ("", ","):
        return prev
    if filler_mark in _SENTENCE_END:
        return lead + core + filler_mark
    had_comma = prev_mark == "," or filler_mark != ""
    opens_sentence = len(out) == 1 or _token_mark(out[-2]) in _SENTENCE_END
    if had_comma and opens_sentence and core.lower() in _INTRO_WORDS:
        return lead + core + ","
    return lead + core


def _capitalize(token: str) -> str:
    """Upper-case the first letter unless the word has its own casing (iPhone, macOS)."""
    lead, core, trail = _split(token)
    if not core or not core[0].isalpha() or not core[0].islower():
        return token
    if any(ch.isupper() for ch in core[1:]):
        return token
    return lead + core[0].upper() + core[1:] + trail


def _ensure_terminal_punctuation(text: str) -> str:
    body = text.rstrip(_CLOSERS)
    closers = text[len(body) :]
    if body.endswith(("...", "…")) or body[-1:] in ".!?:":
        return text
    return body.rstrip(",;-–— ") + "." + closers
