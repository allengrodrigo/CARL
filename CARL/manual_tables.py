"""
manual_tables.py — regenerate CARL_user_manual.html's button/tab-reference
tables from tooltips_data.py.

tooltips_data.py is the source of truth; this module is the one-way generator
that keeps the manual in sync with it. Run `python manual_tables.py` after
editing tooltips_data.py (or call regenerate_manual() directly) to rewrite the
manual's tables in place. Nothing else in the manual is touched.
"""

from __future__ import annotations

import re

from tooltips_data import GROUPS, TABS

# (group_key, heading text, column headers) — column count implied by len(headers).
# A 3-header set with "Location" produces a 3-column table; otherwise 2-column.
TABLE_SPECS = [
    ("Nomenclature tab", "Nomenclature tab — button reference",
     ("Button", "Location", "Function")),
    ("Editor tab", "Editor tab — button reference", ("Button", "Function")),
    ("Information tab", "Information tab — button reference", ("Button", "Function")),
    ("Descriptions tab", "Descriptions tab — button reference",
     ("Button / Control", "Function")),
    ("Comparisons tab", "Comparisons tab — button reference",
     ("Button / Control", "Function")),
    ("Keys tab", "Keys tab — button reference", ("Button / Control", "Function")),
    ("Preferences tab", "Preferences tab — widget reference", ("Widget", "Function")),
    ("Plugins tab", "Plugins tab — button reference", ("Button", "Location", "Function")),
]


def _row_html(entry: dict, ncols: int) -> str:
    label = entry.get("manual_label") or entry.get("label") or ""
    cells = [f"<td><strong>{label}</strong></td>"]
    if ncols == 3:
        cells.append(f"<td>{entry.get('location', '')}</td>")
    cells.append(f"<td>{entry['html']}</td>")
    return "  <tr>" + "\n      ".join(cells) + "</tr>"


def render_group_table(group_key: str) -> str:
    _, _, headers = next(s for s in TABLE_SPECS if s[0] == group_key)
    ncols = len(headers)
    header_row = "  <tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"
    rows = [_row_html(e, ncols) for e in GROUPS[group_key]]
    return "<table>\n" + header_row + "\n\n" + "\n\n".join(rows) + "\n</table>"


def render_tab_table() -> str:
    header_row = "  <tr><th>Tab</th><th>Description</th></tr>"
    rows = [f"  <tr><td><strong>{label}</strong></td>\n      <td>{desc}</td></tr>"
            for label, desc in TABS.items()]
    return "<table>\n" + header_row + "\n" + "\n".join(rows) + "\n</table>"


def regenerate_manual(path: str) -> int:
    """Replace each generated table's HTML in place. Returns count replaced."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    count = 0
    for group_key, heading, _headers in TABLE_SPECS:
        pattern = re.compile(
            re.escape(f"<h3>{heading}</h3>") + r"\s*<table>.*?</table>",
            re.DOTALL)
        new_block = f"<h3>{heading}</h3>\n{render_group_table(group_key)}"
        text, n = pattern.subn(new_block, text, count=1)
        if n == 0:
            print(f"  !! heading not found, skipped: {heading}")
        count += n

    tab_pattern = re.compile(
        re.escape("<p>The tabs available across the panels:</p>") + r"\s*<table>.*?</table>",
        re.DOTALL)
    new_tab_block = "<p>The tabs available across the panels:</p>\n" + render_tab_table()
    text, n = tab_pattern.subn(new_tab_block, text, count=1)
    if n == 0:
        print("  !! tab reference table not found, skipped")
    count += n

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return count


if __name__ == "__main__":
    import os
    manual_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "CARL_user_manual.html")
    n = regenerate_manual(manual_path)
    print(f"Regenerated {n} tables in {manual_path}")
