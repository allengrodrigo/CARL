"""Choose the predicate phrase joining a character name to its state.

The is/are decision in :mod:`number` reflects the *character name's*
grammatical number and is always correct as far as it goes -- but composing
it unconditionally onto every state value produces clumsy English whenever
the value itself starts with "with"/"without"/"having": "Leaves are without
auricular setae" instead of "Leaves do not have auricular setae". This
module adds a value-inspection step layered on top of the number decision;
it does not change how number/head selection works.
"""
from __future__ import annotations

import re

_SIMPLE_RE = re.compile(r"^(with|without|having)\s+(.+)$")
_COMPOUND_RE = re.compile(
    r"^(with|without)\s+(.+?)\s+and\s+(with|without)\s+(.+)$"
)


def render_predicate(number: str, value: str) -> str:
    """Return the ``"<predicate> <value>"`` string to follow the character
    name (compound "with X and without Y" values are rewritten, not just
    prefixed). *number* is ``"singular"`` or ``"plural"`` (as returned by
    :func:`number.classify`)."""
    have     = "has" if number != "plural" else "have"
    have_not = "does not have" if number != "plural" else "do not have"

    m = _COMPOUND_RE.match(value)
    if m:
        w1, part1, w2, part2 = m.groups()
        if w1 == w2 == "without":
            return f"{have_not} {part1} or {part2}"
        if w1 == w2 == "with":
            return f"{have} {part1} and {part2}"
        v1 = have if w1 == "with" else have_not
        v2 = have if w2 == "with" else have_not
        return f"{v1} {part1} but {v2} {part2}"

    m = _SIMPLE_RE.match(value)
    if m:
        word, rest = m.groups()
        if word == "without":
            return f"{have_not} {rest}"
        return f"{have} {rest}"   # "with" or "having"

    verb = "are" if number == "plural" else "is"
    return f"{verb} {value}"
