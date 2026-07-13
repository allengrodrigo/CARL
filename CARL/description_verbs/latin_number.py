"""Rule-based number resolution for scientific Latin/Greek nouns.

The engine is deliberately *conservative*: it only asserts a number for endings
that are distinctly Latin/Greek and reliably unambiguous. Genuinely ambiguous
endings -- above all ``-a`` (feminine singular *seta* vs. neuter plural
*sigilla*), plus ``-ia``, ``-ina``, ``-en`` and ``-es`` -- are left to the
curated :mod:`lexicon` (loaded from ``lexicon.json``) or deferred to the English
fallback in :mod:`number`. This keeps the classifier general across the wider
biological domain without over-guessing.
"""
from __future__ import annotations

import json
import os
from typing import Optional, Tuple

_LEX: Optional[dict] = None


def _load_lexicon() -> dict:
    global _LEX
    if _LEX is None:
        path = os.path.join(os.path.dirname(__file__), "lexicon.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        lex = {}
        for w in data.get("singular", []):
            lex[w.lower()] = "singular"
        for w in data.get("plural", []):
            lex[w.lower()] = "plural"
        _LEX = lex
    return _LEX


# Endings that are safe to treat as plural. Ordered most-specific first so that
# e.g. "-ices" wins over a bare "-i" check.
_PLURAL_SUFFIXES = ("ices", "ae", "i")
# Endings that are safe to treat as singular. (No "-on": English "-ion" words
# swamp the Greek "-on" nouns, which inflect handles as singular anyway and the
# common ones -- ganglion, criterion -- are in the lexicon.)
_SINGULAR_SUFFIXES = ("um", "us", "is", "ix", "ex")

# Minimum characters that must precede a suffix for the rule to fire, so short
# function words ("us", "is", "on") are never mistaken for Latin nouns.
_MIN_STEM = 2


def latin_number(word: str) -> Tuple[Optional[str], str]:
    """Classify *word* as ``"singular"``/``"plural"`` by Latin morphology.

    Returns ``(label, method)`` where *label* is ``None`` when the engine
    declines to guess (the caller then falls back to English detection), and
    *method* is one of ``"lexicon"``, ``"suffix:<end>"`` or ``"unknown"``.
    """
    w = word.lower().strip("'’\".,;:()")
    if not w:
        return None, "unknown"

    lex = _load_lexicon()
    if w in lex:
        return lex[w], "lexicon"

    for suf in _PLURAL_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= _MIN_STEM:
            return "plural", f"suffix:-{suf}"

    for suf in _SINGULAR_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= _MIN_STEM:
            return "singular", f"suffix:-{suf}"

    return None, "unknown"
