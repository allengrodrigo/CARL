"""Split a description file into transformable ``Name: state`` segments while
leaving everything else (headings, separators, taxon banners, the trailing
``(Not applicable: ...)`` note, blank lines) exactly as-is.

Design: process the text line by line so structural whitespace is preserved
byte-for-byte. Each non-structural line is split into sentences on
``". "`` (a period *followed by whitespace* -- decimals like "1.5x" have no
following space and are never split). Each sentence that contains a ``": "``
character/state colon is a candidate for transformation.
"""
from __future__ import annotations

import re

# A sentence boundary: a period followed by whitespace. Kept as a *capturing*
# split so the whitespace is preserved on rejoin. Only "." counts -- splitting
# on ")"/"]" would wrongly break at a mid-sentence parenthetical, and decimals
# ("1.5x") have no following whitespace so are never split.
_SENT_SPLIT = re.compile(r"((?<=\.)\s+)")


def is_structural(line: str) -> bool:
    """True for lines that must pass through untouched."""
    s = line.strip()
    if not s:
        return True
    if s.startswith("**") or s.startswith("#"):        # markdown headings
        return True
    if s.startswith("==") or s.startswith("--") or s.startswith("__"):  # rules
        return True
    if s.startswith("DESCRIPTION FOR"):                 # taxon banner
        return True
    if s.startswith("(Not applicable") or s.startswith("(not applicable"):
        return True
    return False


def split_sentences(line: str):
    """Yield ``(text, is_sentence)`` chunks; whitespace separators have
    ``is_sentence=False`` so the caller can rejoin losslessly."""
    parts = _SENT_SPLIT.split(line)
    for i, part in enumerate(parts):
        yield part, (i % 2 == 0)


def split_colon(sentence: str):
    """Split a sentence on its first ``:``. Returns ``(name, value)`` or
    ``None`` if there is no character/state colon."""
    if ":" not in sentence:
        return None
    left, right = sentence.split(":", 1)
    name, value = left.strip(), right.strip()
    if not name or not value:
        return None
    return name, value
