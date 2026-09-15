"""Tie the pieces together: rewrite ``character = / : state`` into
``character is/are state`` for either a **description** or an identification
**key**, and report the per-character decisions.

Both formats share one number/head engine (:func:`number.classify`); they differ
only in how a line is scanned for the ``character <delim> state`` clause. A
handler is chosen by ``mode`` (``"description"``, ``"key"`` or ``"auto"``).
"""
from __future__ import annotations

import os
import re
from typing import Callable, Dict, List, Tuple

from .keys import is_key_line, split_key_line
from .number import Decision, classify
from .predicate import render_predicate
from .segmenter import is_structural, split_colon, split_sentences

_EOL_RE = re.compile(r"(.*?)(\r\n|\r|\n|)$", re.S)

MODES = ("description", "key", "auto")


# --------------------------------------------------------------------------- #
# shared line iteration + memoised classification
# --------------------------------------------------------------------------- #
def _iter_lines(text: str):
    for line in text.splitlines(keepends=True):
        m = _EOL_RE.match(line)
        yield m.group(1), m.group(2)


def _decide(name: str, cache: Dict[str, Decision], order: List[str]) -> Decision:
    d = cache.get(name)
    if d is None:
        d = classify(name)
        cache[name] = d
        order.append(name)
    return d


# --------------------------------------------------------------------------- #
# per-format line handlers: (content, cache, order) -> new_content
# --------------------------------------------------------------------------- #
def _description_line(content, cache, order):
    if is_structural(content):
        return content
    rebuilt = []
    for chunk, is_sentence in split_sentences(content):
        if not is_sentence:
            rebuilt.append(chunk)
            continue
        parsed = split_colon(chunk)
        if parsed is None:
            rebuilt.append(chunk)
            continue
        name, value = parsed
        d = _decide(name, cache, order)
        rebuilt.append(f"{name} {render_predicate(d.number, value)}")
    return "".join(rebuilt)


def _key_line(content, cache, order):
    if is_structural(content):        # protects "====" rules that contain "="
        return content
    parsed = split_key_line(content)
    if parsed is None:
        return content
    prefix, name, rest = parsed
    d = _decide(name, cache, order)
    return f"{prefix}{name} {render_predicate(d.number, rest)}"


_HANDLERS: Dict[str, Callable] = {
    "description": _description_line,
    "key": _key_line,
}


# --------------------------------------------------------------------------- #
# mode detection
# --------------------------------------------------------------------------- #
_COUPLET_LABEL_RE = re.compile(r"^\s*\d+[a-z][.)]\s")


def detect_mode(text: str) -> str:
    """Guess ``"description"`` vs ``"key"`` from line shape."""
    key_hits = desc_hits = label_lines = 0
    for content, _ in _iter_lines(text):
        if _COUPLET_LABEL_RE.match(content):   # "1a.", "10b." -- survives transform
            label_lines += 1
        if is_structural(content):
            continue
        if is_key_line(content):
            key_hits += 1
            continue
        for chunk, is_sentence in split_sentences(content):
            if is_sentence and split_colon(chunk):
                desc_hits += 1
                break
    if label_lines >= 2:                       # strong couplet signal
        return "key"
    return "key" if key_hits > 0 and key_hits >= desc_hits else "description"


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def transform_text(text: str, mode: str = "auto") -> Tuple[str, List[Decision]]:
    """Transform *text*; return ``(new_text, records)``.

    *records* holds one :class:`~description_verbs.number.Decision` per distinct
    character name, in first-seen order. *mode* is ``"description"``, ``"key"``
    or ``"auto"`` (detects from line shape).
    """
    if mode == "auto":
        mode = detect_mode(text)
    if mode not in _HANDLERS:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    handler = _HANDLERS[mode]

    cache: Dict[str, Decision] = {}
    order: List[str] = []
    out_lines = []
    for content, eol in _iter_lines(text):
        out_lines.append(handler(content, cache, order) + eol)

    return "".join(out_lines), [cache[n] for n in order]


def _default_out_path(path: str) -> str:
    root, ext = os.path.splitext(path)
    return f"{root}_rec{ext or '.txt'}"


def write_report(records: List[Decision], report_path: str) -> None:
    """Write a tab-separated audit of every distinct character name."""
    lines = [
        "\t".join([
            "character_name", "head_noun", "number", "verb",
            "number_method", "head_method", "spacy_root", "spacy_agreed",
        ])
    ]
    for d in records:
        lines.append("\t".join([
            d.name, d.head, d.number, d.verb,
            d.method, d.head_method, d.spacy_root, "yes" if d.agreed else "no",
        ]))
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def transform_file(path: str, out_path: str = None, report_path: str = None,
                   mode: str = "auto") -> str:
    """Transform the file at *path*, writing ``<stem>_rec<ext>`` by default.

    Returns the output path actually written.
    """
    # newline="" disables universal-newline translation so the original EOL
    # style (CRLF in keys, LF in descriptions) round-trips byte-for-byte.
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()

    new_text, records = transform_text(text, mode=mode)

    if out_path is None:
        out_path = _default_out_path(path)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(new_text)

    if report_path:
        write_report(records, report_path)

    return out_path
