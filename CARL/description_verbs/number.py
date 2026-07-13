"""Resolve the number of a head noun and map it to the verb "is"/"are".

Pipeline (first confident answer wins):

1. Latin/Greek morphology -- curated lexicon then conservative suffix rules
   (:mod:`latin_number`). Owns the scientific vocabulary the English tools get
   wrong (*sigilla*, *scopulae*, *setae*).
2. English detection via ``inflect`` -- handles regular and irregular English
   plurals (*spinnerets, cuspules, teeth* -> plural) and returns singular for
   everything it recognises as already-singular.
3. spaCy's ``Number`` morphological feature, when a token is supplied.
4. Default: singular.
"""
from __future__ import annotations

from typing import NamedTuple, Optional

from .head_noun import Head, find_head
from .latin_number import latin_number

_INFLECT = None


def _inflect():
    global _INFLECT
    if _INFLECT is None:
        try:
            import inflect
            _INFLECT = inflect.engine()
        except ImportError:  # pragma: no cover - env guard
            _INFLECT = False
    return _INFLECT


class Decision(NamedTuple):
    name: str          # the full character name
    head: str          # selected head noun
    number: str        # "singular" | "plural"
    verb: str          # "is" | "are"
    method: str        # how number was decided
    head_method: str   # how the head was selected
    spacy_root: str    # spaCy's raw dependency root
    agreed: bool       # spaCy root vs. selected head


def resolve_number(head: str, token=None) -> tuple[str, str]:
    """Return ``(number, method)`` for a head-noun surface form."""
    label, method = latin_number(head)
    if label:
        return label, method

    eng = _inflect()
    if eng:
        # singular_noun() returns the singular form for a plural, else False.
        if eng.singular_noun(head.lower()):
            return "plural", "inflect"
        return "singular", "inflect"

    if token is not None:
        num = token.morph.get("Number")
        if num == ["Plur"]:
            return "plural", "spacy"
        if num == ["Sing"]:
            return "singular", "spacy"

    return "singular", "default"


def classify(name: str, head: Optional[Head] = None) -> Decision:
    """Full is/are decision for a character *name*."""
    if head is None:
        head = find_head(name)
    number, method = resolve_number(head.text, head.token)
    verb = "are" if number == "plural" else "is"
    return Decision(
        name=name, head=head.text, number=number, verb=verb, method=method,
        head_method=head.method, spacy_root=head.spacy_root, agreed=head.agreed,
    )
