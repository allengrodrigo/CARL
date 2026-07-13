"""Command-line entry point.

    python -m description_verbs INPUT.txt [-o OUTPUT] [--report REPORT.tsv]

By default writes ``INPUT_rec.txt`` beside the input and leaves the original
untouched.
"""
from __future__ import annotations

import argparse
import sys

from .nlp import ModelNotInstalled
from .transform import MODES, _default_out_path, detect_mode, transform_file


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="description_verbs",
        description="Replace the 'character <-> state' delimiter (':' in a "
                    "description, '=' in a key) with 'is'/'are' chosen from the "
                    "number of the head noun.",
    )
    p.add_argument("input", help="input text file (description or key)")
    p.add_argument("-o", "--output", default=None,
                   help="output path (default: <input>_rec<ext>)")
    p.add_argument("-m", "--mode", choices=MODES, default="auto",
                   help="input format: 'description' (':'), 'key' ('='), or "
                        "'auto' (detect; default)")
    p.add_argument("--report", default=None, metavar="PATH",
                   help="write a TSV audit of every character-name decision")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="suppress the summary line")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    out = args.output or _default_out_path(args.input)
    try:
        transform_file(args.input, out_path=out, report_path=args.report,
                       mode=args.mode)
    except ModelNotInstalled as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2
    if not args.quiet:
        mode = args.mode
        if mode == "auto":
            try:
                with open(args.input, encoding="utf-8") as fh:
                    mode = f"auto -> {detect_mode(fh.read())}"
            except OSError:
                pass
        print(f"wrote {out}  (mode: {mode})")
        if args.report:
            print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
