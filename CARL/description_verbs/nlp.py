"""Lazy, process-wide spaCy pipeline loader.

We keep the tagger, morphologizer and parser (needed for POS, ``Number`` and the
dependency root cross-check) but disable the NER and lemmatizer components we do
not use, for speed. The model (``en_core_web_sm``, ~12 MB) must be installed
once; thereafter everything runs offline.
"""
from __future__ import annotations

_NLP = None
_MODEL = "en_core_web_sm"


class ModelNotInstalled(RuntimeError):
    """Raised when the spaCy English model has not been downloaded."""


def get_nlp():
    """Return a cached spaCy ``Language`` pipeline, loading it on first use."""
    global _NLP
    if _NLP is None:
        try:
            import spacy
        except ImportError as exc:  # pragma: no cover - env guard
            raise ModelNotInstalled(
                "spaCy is not installed. Run: pip install spacy"
            ) from exc
        try:
            _NLP = spacy.load(_MODEL, disable=["ner", "lemmatizer"])
        except OSError as exc:
            raise ModelNotInstalled(
                f"spaCy model {_MODEL!r} is not installed. Run: "
                f"python -m spacy download {_MODEL}"
            ) from exc
    return _NLP
