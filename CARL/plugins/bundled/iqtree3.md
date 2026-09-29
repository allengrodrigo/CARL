# IQ-TREE 3

## What it does
Maximum-likelihood phylogenetic inference: model selection, tree search,
ultrafast/nonparametric bootstrap, single-branch tests, ancestral sequence
reconstruction, topology tests, consensus trees, Robinson-Foulds distances,
random tree generation, and likelihood mapping.

## Reference
- Minh et al. (2020) *IQ-TREE 2: New Models and Methods for Phylogenetic
  Inference*. Mol. Biol. Evol. 37:1530-1534.
- Homepage: https://iqtree.github.io
- License: GPL-2.0
- Minimum version: 2.0

## Installing the root program
Download a prebuilt binary for your OS from
https://iqtree.github.io/download, or install via conda
(`conda install -c bioconda iqtree`). Make sure the resulting executable is
on PATH.

## Descriptor notes
The plugin file/id predate IQ-TREE's own version-3 rename: the executable
name has changed across major releases (`iqtree` → `iqtree2` → `iqtree3`),
so `alt_executables` lists all three (and their `.exe` variants) — whichever
one is actually installed and on PATH is used. The descriptor's ~100 fields
mirror IQ-TREE's own CLI closely, organised into the same sections as its
manual.

## Known issues
None currently known.
