"""Find the grammatical head noun of a character-name noun phrase.

spaCy does the tokenisation and POS/dependency parsing (the "first call"), but
its raw dependency *root* is unreliable on these telegraphic, Latin-heavy
fragments: it mis-handles coordinated NPs ("Legs I and-or II scopulae" -> root
*Legs*), trailing heads after a prepositional phrase ("Metatarsi of Legs I and
II chaetotaxy" -> root *Metatarsi*), and hyphen artifacts ("sub-equal" ->
*sub*). So head *selection* is governed by a deterministic structural rule
applied over spaCy's tags, which exploits the strong regularity of descriptive
terminology:

    head = the content word after the last numeral (a trailing head such as
           "... of leg III >>chaetotaxy<<"), else
           the last content word before the first preposition
           ("Type of burrow entrance" -> Type), else
           the last content word overall ("Anterior lateral spinnerets").

spaCy's raw root is still computed and returned as a cross-check so callers/the
report can flag disagreements.
"""
from __future__ import annotations

import re
from typing import NamedTuple

from .nlp import get_nlp

_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^()]*\)")

# Closed-class safety nets in case the tagger mislabels a token.
_PREP_WORDS = {
    "of", "in", "on", "with", "at", "to", "from", "between", "among", "along",
    "near", "by", "for", "without", "than", "into", "onto", "over", "under",
    "above", "below", "behind", "beside", "around", "about", "beneath",
    "relative",  # "relative to"
}
_CONJ_WORDS = {"and", "or", "and-or", "and/or", "nor", "plus"}

# POS tags that are never a head. Everything else (NOUN, PROPN, ADJ, VERB, X,
# ADV...) is selectable -- we trust *position* over spaCy's POS because it
# routinely mis-tags Latin/coined heads as VERB ("lobe", "cuspules", "pustules").
_SKIP_POS = {
    "ADP", "CCONJ", "CONJ", "DET", "PART", "PRON", "SCONJ",
    "SYM", "PUNCT", "NUM", "SPACE", "AUX",
}


class Head(NamedTuple):
    text: str          # selected head noun (surface form)
    token: object      # spaCy Token for the head (for morph fallback)
    method: str        # how it was selected
    spacy_root: str    # spaCy's raw dependency-root text (cross-check)
    agreed: bool       # whether spaCy's root matched the selected head


def _strip_parentheticals(name: str) -> str:
    prev = None
    out = name
    while prev != out:  # collapse nested parentheses
        prev = out
        out = _PAREN_RE.sub(" ", out)
    return re.sub(r"\s+", " ", out).strip()


def _is_numeral(tok) -> bool:
    return tok.pos_ == "NUM" or bool(_ROMAN_RE.match(tok.text))


def _is_prep(tok) -> bool:
    return tok.pos_ == "ADP" or tok.lower_ in _PREP_WORDS


def _is_conj(tok) -> bool:
    return tok.pos_ in {"CCONJ", "CONJ"} or tok.lower_ in _CONJ_WORDS


def _selectable(tok) -> bool:
    if _is_numeral(tok) or _is_prep(tok) or _is_conj(tok):
        return False
    return tok.pos_ not in _SKIP_POS


def _last_content(tokens):
    """Rightmost selectable token -- the head of an English NP is its last
    non-functional word, regardless of how spaCy tagged it."""
    for tok in reversed(tokens):
        if _selectable(tok):
            return tok
    return tokens[-1] if tokens else None


def find_head(name: str) -> Head:
    nlp = get_nlp()
    clean = _strip_parentheticals(name)
    doc = nlp(clean)
    toks = [t for t in doc if not (t.is_punct or t.is_space)]

    roots = [t for t in doc if t.head == t]
    spacy_root = roots[0].text if roots else ""

    head = None
    method = "last-content"

    num_idxs = [i for i, t in enumerate(toks) if _is_numeral(t)]
    prep_idxs = [i for i, t in enumerate(toks) if _is_prep(t)]

    if num_idxs:
        trailing = _last_content(toks[num_idxs[-1] + 1:])
        if trailing is not None:
            head, method = trailing, "trailing-after-numeral"

    if head is None and prep_idxs:
        before = _last_content(toks[: prep_idxs[0]])
        if before is not None:
            head, method = before, "before-first-preposition"

    if head is None:
        head = _last_content(toks)
        method = "last-content"

    text = head.text if head is not None else clean
    agreed = bool(spacy_root) and spacy_root.lower() == text.lower()
    return Head(text=text, token=head, method=method,
                spacy_root=spacy_root, agreed=agreed)
