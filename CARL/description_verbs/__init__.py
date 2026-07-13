"""description_verbs -- replace the ``character <-> state`` delimiter in
taxonomic text with the verb "is"/"are".

Handles two input formats, chosen by ``mode``:

* ``"description"`` -- ``Character name: state.`` -> ``Character name is/are state.``
* ``"key"`` -- ``1a. If character name = state, then ...`` ->
  ``1a. If character name is/are state, then ...``
* ``"auto"`` (default) -- detect the format from line shape.

Either way the verb is chosen from the grammatical number of the *head noun* of
the character name, using programmatic natural-language parsing only (spaCy for
tokenisation/POS + a deterministic structural rule for head selection) and a
rule-based Latin/Greek morphology engine for number -- no LLMs. Everything runs
fully offline once the spaCy model is installed.

Public API
----------
transform_text(text, mode="auto")  -> (new_text, records)
transform_file(path, out_path=None, report_path=None, mode="auto") -> out_path

``records`` is a list of :class:`~description_verbs.number.Decision`-like dicts
describing every distinct character name that was converted (head noun, number,
verb, method, spaCy root, agreement) -- useful for auditing coverage on a new
taxonomic group without a human in the loop.
"""
from .transform import transform_text, transform_file

__all__ = ["transform_text", "transform_file"]
__version__ = "0.1.0"
