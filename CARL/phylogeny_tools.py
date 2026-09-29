#!/usr/bin/env python3
"""Render IQ-TREE Newick results and emit reusable phylogeny evidence."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile

from Bio import Phylo


SUPPORT_RE = re.compile(r"^\s*([0-9.]+)(?:/([0-9.]+))?\s*$")

# Comment keys that carry node support, in priority order → canonical label.
# Newick has no support standard; different programs use different conventions.
_COMMENT_SUPPORT_KEYS = [
    ("posterior", "posterior"),   # BEAST, RevBayes
    ("prob",      "posterior"),   # MrBayes .con.tre clade probability
    ("support",   "support"),
    ("bootstrap", "bootstrap"),
    ("b",         "bootstrap"),   # NHX bootstrap key
]


def detect_tree_format(path) -> str:
    """Peek at a tree file's content to tell NEXUS from bare Newick, rather
    than assuming Newick. PAUP*'s SAVETREES/CONTREE output is always a full
    NEXUS block (#NEXUS, Begin trees;, one or more named tree statements,
    End;) -- never bare Newick -- so hardcoding "newick" broke on every
    PAUP*-produced tree file (confirmed directly: NewickError('Text after
    semicolon...'), because the parser was treating the NEXUS "Begin trees;"
    statement's own semicolon as a tree terminator)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        head = fh.read(64).lstrip()
    return "nexus" if head[:6].upper() == "#NEXUS" else "newick"


def _extract_first_newick_from_nexus(text: str) -> str:
    """Extract the first 'tree NAME = [&U] (...);' statement's Newick
    substring from a NEXUS TREES block, via balanced-paren scanning (not a
    naive regex, so nested clades don't break it).

    This exists because Bio.Phylo's own NEXUS tree-statement parser silently
    drops node confidence/support values -- confirmed directly against a
    real PAUP* CONTREE file (MajRule consensus, values like 100, 79.915,
    39.927 after each internal clade): every clade.confidence came back
    None when read with format="nexus", but correctly populated
    (0, 100, 100, 100, 79.915, ...) when the identical tree substring was
    parsed with format="newick" instead. Bio.Phylo handles the surrounding
    NEXUS structure fine; it's specifically the per-node support values
    inside the tree string it loses. Pulling out just the Newick substring
    and handing that to the Newick parser sidesteps the gap entirely.
    """
    m = re.search(r'\btree\s+\S+\s*=\s*(?:\[&[URur]\]\s*)?\(', text)
    if not m:
        raise ValueError("No tree statement found in NEXUS file.")
    start = m.end() - 1  # position of the tree's opening '('
    depth = 0
    i = start
    while i < len(text):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                break
        i += 1
    else:
        raise ValueError("Unbalanced parentheses in tree statement.")
    semi = text.find(';', i)
    if semi == -1:
        raise ValueError("No terminating ';' found for tree statement.")
    return text[start:semi + 1]


def _parse_nexus_translate(text: str) -> dict:
    """Parse a NEXUS 'Translate 1 Name1, 2 Name2, ... ;' block into
    {code: name}. Common in PAUP* output for large tree files (e.g. every
    tree in a 1,643-tree SAVETREES file) -- taxa are coded as bare numbers
    in every tree statement, saving the full names from being repeated in
    every one, with the mapping given once up front. Bio.Phylo's own NEXUS
    reader resolves this automatically; the direct-Newick-substring approach
    in read_first_tree() (needed to preserve confidence values -- see
    project_tree_viewer_nexus_support_revision.md) does not, so this is
    applied manually afterward. Returns {} if there's no Translate block
    (an ordinary file with real names directly in the tree string)."""
    m = re.search(r'\btranslate\b(.*?);', text, re.IGNORECASE | re.DOTALL)
    if not m:
        return {}
    mapping = {}
    for entry in m.group(1).split(','):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(None, 1)
        if len(parts) == 2:
            code, name = parts
            mapping[code] = name.strip().strip("'\"")
    return mapping


def read_first_tree(path):
    """Read a tree file that may be NEXUS or Newick, and may contain more
    than one tree -- e.g. a PAUP* CONTREE output has both a Strict and
    Semistrict consensus tree in one file, and a raw SAVETREES output from a
    real search routinely has hundreds or thousands (every equally-
    parsimonious tree retained). Always returns the first tree (see
    project_tree_viewer_nexus_support_revision.md for why a fuller
    "which tree to show" design was deliberately left open rather than
    attempted here).

    For NEXUS files, the tree string is extracted and parsed as Newick
    directly (see _extract_first_newick_from_nexus) rather than handed to
    Bio.Phylo's own NEXUS reader, to preserve node confidence/support
    values it would otherwise silently drop -- confirmed this loses a
    NEXUS file's own Translate-block tip-name resolution as a side effect
    (tips came back labelled "1", "2", ... instead of the real taxon
    names), so that's re-applied manually via _parse_nexus_translate()."""
    fmt = detect_tree_format(path)
    if fmt == "nexus":
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        newick_str = _extract_first_newick_from_nexus(text)
        tree = Phylo.read(io.StringIO(newick_str), "newick")
        translate = _parse_nexus_translate(text)
        if translate:
            for clade in tree.get_terminals():
                if clade.name in translate:
                    clade.name = translate[clade.name]
        return tree
    return next(Phylo.parse(str(path), fmt))


def _base_path(tree_path: Path) -> Path:
    return tree_path.with_suffix("") if tree_path.suffix == ".treefile" else tree_path


def _to_float(text: str):
    try:
        return float(text.strip().strip('"').strip("'"))
    except (ValueError, AttributeError):
        return None


def _split_pairs(body: str, sep: str) -> dict:
    """Split key=value pairs on `sep`, ignoring separators inside {...}/[...]/(...)."""
    pairs, token, depth = [], "", 0
    for ch in body:
        if ch in "{[(":
            depth += 1
            token += ch
        elif ch in "}])":
            depth = max(0, depth - 1)
            token += ch
        elif ch == sep and depth == 0:
            pairs.append(token)
            token = ""
        else:
            token += ch
    if token:
        pairs.append(token)
    out = {}
    for item in pairs:
        if "=" in item:
            key, val = item.split("=", 1)
            out[key.strip().lower()] = val.strip()
    return out


def _parse_comment_support(comment: str) -> dict:
    """Extract support from a FigTree/BEAST `[&..]` or NHX `[&&NHX:..]` comment."""
    body = comment.strip().lstrip("&")
    if body[:3].upper() == "NHX":
        pairs = _split_pairs(body[3:].lstrip(":"), sep=":")
    else:
        pairs = _split_pairs(body, sep=",")
    for key, label in _COMMENT_SUPPORT_KEYS:
        if key in pairs:
            value = _to_float(pairs[key])
            if value is not None:
                return {label: value}
    return {}


def parse_node_support(clade) -> dict:
    """Return an ordered {scheme: value} dict of a clade's support.

    Reads the three incompatible Newick support conventions, in priority order:
      1. FigTree/BEAST/NEXUS metadata comment  ``[&posterior=..,prob=..]``
         (BEAST, MrBayes, RevBayes) and NHX ``[&&NHX:B=..]``
      2. Internal-node label — a single number, or IQ-TREE's ``SH-aLRT/UFBoot`` pair
      3. Bio.Phylo ``clade.confidence`` fallback (numeric internal labels often
         land here instead of ``clade.name``)
    Returns {} when no support is present.
    """
    comment = (getattr(clade, "comment", None) or "").strip()
    if comment:
        vals = _parse_comment_support(comment)
        if vals:
            return vals

    label = (clade.name or "").strip()
    match = SUPPORT_RE.match(label)
    if match:
        first = float(match.group(1))
        if match.group(2) is not None:
            return {"SH-aLRT": first, "UFBoot": float(match.group(2))}
        return {"support": first}

    if clade.confidence is not None:
        return {"support": float(clade.confidence)}
    return {}


def _tip_names(clade) -> list[str]:
    return sorted(t.name or "" for t in clade.get_terminals())


def _tree_evidence(tree, source: Path, rooting: str) -> dict:
    nodes = []
    for clade in tree.find_clades(order="preorder"):
        if clade.is_terminal():
            continue
        support = parse_node_support(clade)
        nodes.append({
            "taxa": _tip_names(clade),
            "branch_length": clade.branch_length,
            **support,
        })
    return {
        "source_tree": str(source.resolve()),
        "rooting": rooting,
        "taxa": _tip_names(tree.root),
        "internal_nodes": nodes,
    }


def _layout(tree):
    terminals = tree.get_terminals()
    step = (2 * math.pi) / max(len(terminals), 1)
    terminal_index = {terminal: i for i, terminal in enumerate(terminals)}
    angles = {terminal: i * step for terminal, i in terminal_index.items()}

    for clade in tree.find_clades(order="postorder"):
        if clade.is_terminal():
            continue
        descendants = clade.get_terminals()
        angles[clade] = sum(terminal_index[t] for t in descendants) / len(descendants) * step

    heights = {}
    for clade in tree.find_clades(order="postorder"):
        heights[clade] = 0 if clade.is_terminal() else 1 + max(heights[c] for c in clade.clades)
    max_height = heights[tree.root] or 1
    radii = {
        clade: 0.78 * (max_height - height) / max_height
        for clade, height in heights.items()
    }
    return terminals, angles, radii


def _draw_arc(ax, radius: float, start: float, end: float, **kwargs):
    if end < start:
        start, end = end, start
    points = max(12, int((end - start) * 40))
    theta = [start + (end - start) * i / points for i in range(points + 1)]
    ax.plot([radius * math.cos(t) for t in theta],
            [radius * math.sin(t) for t in theta], **kwargs)


def render_circular_tree(tree, output_png: Path, output_svg: Path, title: str,
                         rooting_note: str) -> None:
    cache_dir = Path(tempfile.gettempdir()) / "carl-matplotlib"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    terminals, angles, radii = _layout(tree)
    size = min(16, max(9, 7 + len(terminals) * 0.22))
    fig, ax = plt.subplots(figsize=(size, size), facecolor="white")
    ax.set_aspect("equal")
    ax.axis("off")

    edge_color = "#3f4854"
    support_color = "#8b2f2f"
    for parent in tree.find_clades(order="preorder"):
        children = list(parent.clades)
        if not children:
            continue
        child_angles = [angles[child] for child in children]
        _draw_arc(ax, radii[parent], min(child_angles), max(child_angles),
                  color=edge_color, linewidth=1.15)
        for child in children:
            angle = angles[child]
            r0, r1 = radii[parent], radii[child]
            ax.plot([r0 * math.cos(angle), r1 * math.cos(angle)],
                    [r0 * math.sin(angle), r1 * math.sin(angle)],
                    color=edge_color, linewidth=1.15)
            support = parse_node_support(child)
            if support:
                text = "/".join(f"{v:g}" for v in support.values())
                rm = (r0 + r1) / 2
                ax.text(rm * math.cos(angle), rm * math.sin(angle), text,
                        fontsize=6.5, color=support_color, ha="center", va="center",
                        bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.4})

    label_radius = 0.815
    for terminal in terminals:
        angle = angles[terminal]
        degrees = math.degrees(angle)
        on_left = 90 < degrees < 270
        rotation = degrees + 180 if on_left else degrees
        ha = "right" if on_left else "left"
        ax.text(label_radius * math.cos(angle), label_radius * math.sin(angle),
                terminal.name or "", rotation=rotation, rotation_mode="anchor",
                ha=ha, va="center", fontsize=9, color="#111111")

    ax.set_xlim(-1.25, 1.25)
    ax.set_ylim(-1.30, 1.25)
    ax.text(0, 1.16, title, ha="center", va="center", fontsize=15, weight="bold")
    ax.text(0, -1.23, rooting_note, ha="center", va="center", fontsize=8.5,
            color="#555555", wrap=True)
    fig.savefig(output_png, dpi=240, bbox_inches="tight", pad_inches=0.15)
    fig.savefig(output_svg, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def generate_phylogeny_outputs(tree_file: str) -> dict:
    source = Path(tree_file).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Tree file not found: {source}")

    original = read_first_tree(source)
    original.rooted = False
    midpoint = copy.deepcopy(original)
    midpoint.root_at_midpoint()
    midpoint.rooted = True

    base = _base_path(source)
    outputs = {
        "unrooted_png": Path(str(base) + ".unrooted.circular.png"),
        "unrooted_svg": Path(str(base) + ".unrooted.circular.svg"),
        "midpoint_png": Path(str(base) + ".midpoint.circular.png"),
        "midpoint_svg": Path(str(base) + ".midpoint.circular.svg"),
        "midpoint_tree": Path(str(base) + ".midpoint.treefile"),
        "evidence_json": Path(str(base) + ".phylogeny_evidence.json"),
    }

    render_circular_tree(
        original,
        outputs["unrooted_png"],
        outputs["unrooted_svg"],
        "Unrooted phylogeny",
        "Circular display of the original IQ-TREE topology; no biological root is implied.",
    )
    render_circular_tree(
        midpoint,
        outputs["midpoint_png"],
        outputs["midpoint_svg"],
        "Midpoint-rooted phylogeny",
        "Midpoint rooting is a working visualization and does not establish evolutionary direction.",
    )
    Phylo.write(midpoint, str(outputs["midpoint_tree"]), "newick")

    evidence = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_tree": str(source),
        "cautions": [
            "The original IQ-TREE tree is treated as unrooted.",
            "Midpoint rooting is provisional and must not be interpreted as evidence of evolutionary direction.",
            "Topology comparisons require compatible taxon sampling and name reconciliation.",
        ],
        "unrooted": _tree_evidence(original, source, "unrooted"),
        "midpoint": _tree_evidence(midpoint, source, "midpoint"),
        "outputs": {key: str(value) for key, value in outputs.items()},
    }
    outputs["evidence_json"].write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {key: str(value) for key, value in outputs.items()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tree_file", help="IQ-TREE .treefile or Newick file")
    args = parser.parse_args(argv)
    outputs = generate_phylogeny_outputs(args.tree_file)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
