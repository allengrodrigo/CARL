#!/usr/bin/env python3
"""Standalone alignment / character-matrix format converter.

Reads and writes the full supported set symmetrically:

    fasta, nexus, phylip, nexml, clustal, stockholm

Engine split (internal detail):
  * NEXUS / NeXML        -> DendroPy   (datatype-aware, incl. morphology/standard)
  * FASTA / PHYLIP /
    Clustal / Stockholm  -> Biopython AlignIO (FASTA also written directly)

A neutral (labels, sequences, data_type) bridge moves data between the two
libraries, so any input format can convert to any output format.

This is a self-contained command-line program with no CARL dependencies, so it
can be frozen to a standalone executable and wrapped by a plugin descriptor.

Usage:
    alignment_convert.py INPUT OUTPUT --to nexus [--from auto] [--data-type standard] [--relaxed]
"""

from __future__ import annotations

import argparse
import os
import re
import sys

DENDROPY_FORMATS  = {"nexus", "nexml"}
BIOPYTHON_FORMATS = {"phylip", "clustal", "stockholm"}   # fasta written directly
ALL_FORMATS       = ["fasta", "nexus", "phylip", "nexml", "clustal", "stockholm"]
DATA_TYPES        = ["standard", "dna", "rna", "protein"]

_EXT_MAP = {
    ".fasta": "fasta", ".fa": "fasta", ".fas": "fasta", ".fna": "fasta",
    ".nex": "nexus", ".nexus": "nexus",
    ".phy": "phylip", ".phylip": "phylip",
    ".xml": "nexml", ".nexml": "nexml",
    ".aln": "clustal", ".clustal": "clustal",
    ".sto": "stockholm", ".stk": "stockholm", ".stockholm": "stockholm",
}


class ConversionError(Exception):
    """Raised for any user-facing conversion failure."""


# ── format detection ────────────────────────────────────────────────────────────

def detect_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    fmt = _EXT_MAP.get(ext)
    if not fmt:
        raise ConversionError(
            f"Cannot auto-detect input format from extension '{ext or '(none)'}'. "
            f"Specify --from explicitly (one of: {', '.join(ALL_FORMATS)}).")
    return fmt


# ── reading: any format -> (labels, sequences, data_type) ───────────────────────

def read_alignment(path: str, fmt: str, data_type: str):
    if fmt == "nexus":
        return _read_nexus(path)
    if fmt == "nexml":
        return _read_dendropy(path, "nexml")
    return _read_biopython(path, fmt, data_type)


def _read_nexus(path: str):
    """DendroPy first (rich, typed); fall back to a permissive reader for files
    it rejects — undeclared symbols, polymorphism, or extra blocks (e.g. CARL)."""
    try:
        return _read_dendropy(path, "nexus")
    except Exception:
        return _read_nexus_permissive(path)


def _read_biopython(path: str, fmt: str, data_type: str):
    if fmt == "fasta":
        labels, seqs = _read_fasta(path)
        return labels, seqs, data_type
    try:
        from Bio import AlignIO
    except ImportError as exc:
        raise ConversionError(f"Biopython is required to read '{fmt}': {exc}")
    bio_fmt = "phylip-relaxed" if fmt == "phylip" else fmt
    try:
        alignment = AlignIO.read(path, bio_fmt)
    except Exception:
        if fmt == "phylip":                      # retry strict layout
            alignment = AlignIO.read(path, "phylip")
        else:
            raise
    labels = [rec.id for rec in alignment]
    seqs   = [str(rec.seq) for rec in alignment]
    return labels, seqs, data_type


def _read_fasta(path: str):
    labels, seqs, buff = [], [], []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if labels:
                    seqs.append("".join(buff))
                    buff = []
                labels.append(line[1:].strip())
            elif line:
                buff.append(line.strip())
    if labels:
        seqs.append("".join(buff))
    if not labels:
        raise ConversionError(f"No sequences found in FASTA file: {path}")
    return labels, seqs


def _read_dendropy(path: str, fmt: str):
    try:
        import dendropy
    except ImportError as exc:
        raise ConversionError(f"DendroPy is required to read '{fmt}': {exc}")
    dataset = dendropy.DataSet.get(path=path, schema=fmt)
    if not dataset.char_matrices:
        raise ConversionError(f"No character matrix found in {fmt} file: {path}")
    matrix = dataset.char_matrices[0]
    detected = _dendropy_data_type(dendropy, matrix)
    labels, seqs = [], []
    for taxon in matrix:
        labels.append(taxon.label)
        seqs.append(matrix[taxon].symbols_as_string())
    return labels, seqs, detected


def _dendropy_data_type(dendropy, matrix) -> str:
    if isinstance(matrix, dendropy.DnaCharacterMatrix):
        return "dna"
    if isinstance(matrix, dendropy.RnaCharacterMatrix):
        return "rna"
    if isinstance(matrix, dendropy.ProteinCharacterMatrix):
        return "protein"
    return "standard"


# ── permissive NEXUS reader (fallback) ──────────────────────────────────────────
#
# For NEXUS files DendroPy's strict, typed reader rejects: undeclared state
# symbols (e.g. an 'N' used as a second missing code), polymorphism like (1,2)
# or {1,2}, and unrecognised blocks (e.g. a CARL block). We read only the
# DATA/CHARACTERS matrix and normalise each cell to a single character:
#   * declared GAP            -> '-'
#   * declared MISSING        -> '?'
#   * polymorphism/uncertainty -> '?'
#   * undeclared symbol        -> '?'
#   * declared state / molecular symbol -> kept
#
# Heuristic limit: for standard data with no SYMBOLS= declaration, single digits
# are treated as states and any letter as missing. Matrices that code states as
# letters (>10 states) should declare SYMBOLS= to be read faithfully.

def _read_nexus_permissive(path: str):
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    block = _find_nexus_block(text, ("data", "characters"))
    if block is None:
        raise ConversionError("No DATA or CHARACTERS block found in NEXUS file.")

    missing, gap, symbols, datatype = _parse_nexus_format(block)
    matrix_region = _extract_nexus_matrix(block)
    if matrix_region is None:
        raise ConversionError("No MATRIX found in the NEXUS DATA block.")
    matrix_region = re.sub(r"\[[^\]]*\]", "", matrix_region)   # strip comments

    labels, cell_rows = _parse_nexus_matrix_rows(matrix_region)
    if not labels:
        raise ConversionError("No taxa parsed from the NEXUS MATRIX.")

    seqs = ["".join(_nexus_cell_to_char(c, symbols, missing, gap, datatype)
                    for c in cells)
            for cells in cell_rows]
    return labels, seqs, datatype


def _find_nexus_block(text, names):
    for name in names:
        m = re.search(r"begin\s+" + name + r"\b", text, re.IGNORECASE)
        if not m:
            continue
        start = m.start()
        end_m = re.search(r"\bend\s*;", text[start:], re.IGNORECASE)
        end = start + end_m.end() if end_m else len(text)
        return text[start:end]
    return None


def _parse_nexus_format(block):
    missing, gap, symbols, datatype = "?", "-", None, "standard"
    m = re.search(r"\bformat\b(.*?);", block, re.IGNORECASE | re.DOTALL)
    if m:
        fmt = m.group(1)
        md = re.search(r"datatype\s*=\s*(\w+)", fmt, re.IGNORECASE)
        if md:
            dt = md.group(1).lower()
            datatype = dt if dt in ("dna", "rna", "protein", "standard") else "standard"
        mm = re.search(r"missing\s*=\s*(\S)", fmt, re.IGNORECASE)
        if mm:
            missing = mm.group(1).strip("'\"")
        mg = re.search(r"gap\s*=\s*(\S)", fmt, re.IGNORECASE)
        if mg:
            gap = mg.group(1).strip("'\"")
        ms = re.search(r'symbols\s*=\s*"([^"]*)"', fmt, re.IGNORECASE)
        if ms:
            raw = ms.group(1).strip()
            symbols = set(raw.split()) if " " in raw else set(raw)
    return missing, gap, symbols, datatype


def _extract_nexus_matrix(block):
    m = re.search(r"\bmatrix\b(.*?);", block, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else None


def _parse_nexus_matrix_rows(matrix_region):
    labels, rows, seen = [], [], {}
    for line in matrix_region.splitlines():
        line = line.strip()
        if not line:
            continue
        label, rest = _split_nexus_label(line)
        if label is None:
            continue
        tokens = _tokenize_nexus_cells(rest)
        if label in seen:                       # interleaved continuation
            rows[seen[label]].extend(tokens)
        else:
            seen[label] = len(labels)
            labels.append(label)
            rows.append(tokens)
    return labels, rows


def _split_nexus_label(line):
    if line[0] in "'\"":
        quote = line[0]
        end = line.find(quote, 1)
        if end == -1:
            return None, ""
        return line[1:end], line[end + 1:]
    parts = line.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _tokenize_nexus_cells(text):
    cells, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "({":
            close = ")" if ch == "(" else "}"
            j = text.find(close, i)
            if j == -1:
                cells.append(text[i:])
                break
            cells.append(text[i:j + 1])
            i = j + 1
        else:
            cells.append(ch)
            i += 1
    return cells


def _nexus_cell_to_char(cell, symbols, missing, gap, datatype):
    if cell[0] in "({":
        return "?"                              # polymorphism / uncertainty
    if cell == gap:
        return "-"
    if cell == missing:
        return "?"
    if datatype in ("dna", "rna", "protein"):
        return cell.upper()                     # keep molecular symbols verbatim
    if symbols is not None:
        return cell if cell in symbols else "?"
    return cell if cell.isdigit() else "?"      # standard heuristic: digits = states


# ── writing: (labels, sequences, data_type) -> any format ───────────────────────

def write_alignment(path, fmt, labels, seqs, data_type, relaxed=False):
    if fmt == "fasta":
        _write_fasta(path, labels, seqs)
    elif fmt in DENDROPY_FORMATS:
        _write_dendropy(path, fmt, labels, seqs, data_type)
    else:
        _write_biopython(path, fmt, labels, seqs, relaxed)


def _write_fasta(path, labels, seqs, width=60):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for label, seq in zip(labels, seqs):
            fh.write(f">{label}\n")
            for i in range(0, len(seq), width):
                fh.write(seq[i:i + width] + "\n")


def _write_biopython(path, fmt, labels, seqs, relaxed):
    try:
        from Bio import AlignIO
        from Bio.Align import MultipleSeqAlignment
        from Bio.Seq import Seq
        from Bio.SeqRecord import SeqRecord
    except ImportError as exc:
        raise ConversionError(f"Biopython is required to write '{fmt}': {exc}")
    records = [SeqRecord(Seq(seq), id=label, description="")
               for label, seq in zip(labels, seqs)]
    alignment = MultipleSeqAlignment(records)
    bio_fmt = ("phylip-relaxed" if relaxed else "phylip") if fmt == "phylip" else fmt
    AlignIO.write(alignment, path, bio_fmt)


def _write_dendropy(path, fmt, labels, seqs, data_type):
    try:
        import dendropy
    except ImportError as exc:
        raise ConversionError(f"DendroPy is required to write '{fmt}': {exc}")
    fasta = "".join(f">{label}\n{seq}\n" for label, seq in zip(labels, seqs))
    classes = {
        "dna":      dendropy.DnaCharacterMatrix,
        "rna":      dendropy.RnaCharacterMatrix,
        "protein":  dendropy.ProteinCharacterMatrix,
        "standard": dendropy.StandardCharacterMatrix,
    }
    cls = classes[data_type]
    if data_type == "standard":
        symbols = sorted({c for seq in seqs for c in seq if c not in "-?"})
        state_alphabet = dendropy.new_standard_state_alphabet(symbols)
        matrix = cls.get(data=fasta, schema="fasta",
                         default_state_alphabet=state_alphabet)
    else:
        matrix = cls.get(data=fasta, schema="fasta")
    matrix.write(path=path, schema=fmt)


# ── CLI ─────────────────────────────────────────────────────────────────────────

def convert(args) -> None:
    if not os.path.isfile(args.input):
        raise ConversionError(f"Input file not found: {args.input}")
    from_fmt = detect_format(args.input) if args.__dict__["from"] == "auto" \
        else args.__dict__["from"]
    labels, seqs, data_type = read_alignment(args.input, from_fmt, args.data_type)
    if not labels:
        raise ConversionError("Input contains no sequences.")
    lengths = {len(s) for s in seqs}
    if len(lengths) > 1:
        raise ConversionError(
            "Sequences are not all the same length — this is an alignment "
            f"converter (lengths seen: {sorted(lengths)}).")
    write_alignment(args.output, args.to, labels, seqs, data_type, args.relaxed)
    print(f"Converted {len(labels)} sequences: "
          f"{from_fmt} -> {args.to}  ({data_type})")
    print(f"Wrote: {args.output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert sequence alignments / character matrices between formats.")
    parser.add_argument("input", help="Input alignment file")
    parser.add_argument("output", help="Output alignment file")
    parser.add_argument("--from", dest="from", default="auto",
                        choices=["auto"] + ALL_FORMATS,
                        help="Input format (default: auto-detect by extension)")
    parser.add_argument("--to", required=True, choices=ALL_FORMATS,
                        help="Output format")
    parser.add_argument("--data-type", default="standard", choices=DATA_TYPES,
                        help="Data type for schema-less inputs and NEXUS/NeXML "
                             "output (default: standard). NEXUS/NeXML inputs are "
                             "auto-detected.")
    parser.add_argument("--relaxed", action="store_true",
                        help="Write relaxed PHYLIP (long taxon names); phylip output only.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        convert(args)
    except ConversionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:                     # unexpected — surface cleanly
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
