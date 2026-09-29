# Alignment Format Converter

## What it does
Converts sequence alignments and character matrices between FASTA, NEXUS,
PHYLIP, NeXML, Clustal, and Stockholm. Any supported format can be read or
written, in any direction. Morphology/standard data is fully represented in
NEXUS/NeXML.

## Reference
CARL's own tool (`alignment_convert.py`) — no external citation for the tool
itself. Internally it uses DendroPy (NEXUS/NeXML) and Biopython's AlignIO
(PHYLIP/Clustal/Stockholm; FASTA is written directly), both open-source
libraries already bundled in CARL's Python environment.

## Installing the root program
Nothing to install separately — it ships with CARL. A frozen standalone
build (`alignment_convert.exe`) is also available as an `alt_executable` for
use outside CARL's own Python environment.

## Descriptor notes
"Relaxed PHYLIP" only appears, and only applies, when Output format is set
to `phylip`.

## Known issues
None currently known.
