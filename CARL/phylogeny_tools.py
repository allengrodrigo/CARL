#!/usr/bin/env python3
"""Render IQ-TREE Newick results and emit reusable phylogeny evidence."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
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

    original = Phylo.read(str(source), "newick")
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
