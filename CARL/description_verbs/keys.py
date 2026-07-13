"""Recognise transformable lines in an identification key.

A key couplet looks like::

    1a. If legs I and-or II tarsal spines = absent, then go to 2.
    2b. If anterior lateral spinnerets = absent, then the taxon is Antrodiaetus.

The character name sits between the ``If`` and the ``=``; the state follows the
``=``. The verb is chosen from the head noun of that name using the *same*
engine as descriptions -- only the delimiter (``=`` vs ``:``) and the
surrounding boilerplate differ. Everything else (banners, ``Key statistics
[SI]:`` lines, ``N steps: taxa`` lists, ``====``/``----`` rules) has no ``=`` and
passes straight through.
"""
from __future__ import annotations

import re

# A couplet must carry a structural signal so we never mistake a stray "=" in a
# description value (e.g. "many (>=10)") for a key clause: a numbered label
# ("1a.", "10b.", "3)") and/or a leading "If". At least one is required.
_LABEL = r"\d+[a-z]?[.)]\s+"
_IF = r"[Ii]f\s+"
_PREFIX = r"(?:" + _LABEL + r"(?:" + _IF + r")?|" + _IF + r")"

# prefix = label and/or "If " ; name = up to the first "=" ; rest = state (+ "then ...").
KEY_LINE_RE = re.compile(
    r"^(?P<prefix>\s*" + _PREFIX + r")(?P<name>.+?)\s*=\s*(?P<rest>.+)$"
)


def is_key_line(content: str) -> bool:
    """True for a couplet line carrying a ``character = state`` clause."""
    return KEY_LINE_RE.match(content) is not None


def split_key_line(content: str):
    """Return ``(prefix, name, rest)`` for a key line, or ``None``.

    *prefix* keeps its trailing space so the line rebuilds as
    ``f"{prefix}{name} {verb} {rest}"``.
    """
    m = KEY_LINE_RE.match(content)
    if m is None:
        return None
    name = m.group("name").strip()
    if not name:
        return None
    return m.group("prefix"), name, m.group("rest")
