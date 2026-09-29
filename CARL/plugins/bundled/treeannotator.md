# TreeAnnotator

## What it does
Summarises a BEAST posterior tree sample (a `.trees` file) into a single
Maximum Clade Credibility (MCC) tree, annotated with node statistics (node
heights, HPD intervals, posterior probabilities).

## Reference
- Rambaut A. and Drummond A.J. *TreeAnnotator v1.10*, 2002-2017.
- Homepage: https://beast.community/treeannotator
- License: LGPL-2.1

## Installing the root program
TreeAnnotator ships as part of a BEAST installation, not standalone. Install
BEAST 1.x from https://beast.community (or BEAST2 from https://www.beast2.org);
either places `treeannotator`/`treeannotator.exe` alongside BEAST's other
command-line tools. Make sure that install's `bin` folder is on PATH.

## Descriptor notes
"Burn-in (states)" and "Burn-in (trees)" are mutually exclusive — set one,
not both. Both the input trees file and the output file are plain
positional file fields, not flags.

## Known issues
None currently known.
