# CARL — Classification (AI-Accessible) Research Laboratory

CARL is an integrated desktop environment for taxonomic research: build and
edit NEXUS character matrices, retrieve taxonomic and nomenclatural
information from biodiversity databases, generate descriptions, comparisons
and identification keys, and run external phylogenetics tools — with optional
LLM assistance throughout.

## Disclaimer

CARL is free, open-source software released under the [MIT License](LICENSE)
and is provided **as is**, without warranty of any kind. The authors accept
no liability for any loss or damage arising from its use.

CARL's outputs — identification keys, generated descriptions (programmatic
or LLM-assisted), nomenclatural lookups, and retrieved passages from the
Codes — are research aids, not authoritative determinations. Results should
be verified against primary sources before publication or any formal
nomenclatural act. Large-language-model output can be inaccurate or
fabricated; where CARL's verifier reports remaining issues after its
correction loop, those are shown to you deliberately, alongside the
unmodified original, so you can judge them yourself.

## Installation

See **[Installation_Guide.html](Installation_Guide.html)** for full details.

Quick start:

- **macOS / Linux:** `./install.sh`
- **Windows:** double-click `install.bat`

Both scripts create a local virtual environment, install dependencies from
`requirements.txt`, and write a launcher (`run_carl.sh` / `run_carl.bat`) you
can use to start CARL afterwards.

## Configuration

Copy `CARL/config_dist.py` to `CARL/config.py` and fill in your own API
key(s) for any LLM provider(s) you plan to use. `config.py` is your local
configuration file and should never be committed or shared — it is already
excluded via `.gitignore`.

## Plugins

Plugin descriptors run programs. A descriptor tells CARL which executable to
launch, with what arguments, and where to write output — with your own user
permissions. Only load descriptors you wrote yourself or obtained from a
source you trust, and check the *Command:* preview before running. CARL does
not install or vet the external tools a descriptor points to; each has its
own license and is your responsibility to obtain and trust separately.

Descriptors are plain JSON, so you can (and should) open one in a text
editor before loading it. Look at `executable` / `alt_executables` (what
will run), the fields (what arguments it accepts), and `output.stdout_file`
if present (a literal path CARL will *overwrite* with the tool's output).
The bundled descriptors (IQ-TREE, TreeAnnotator, the alignment converter) —
see [CARL/plugin_spec.md](CARL/plugin_spec.md) for the format — only launch
the named tool if you have installed it yourself; they never download or
install anything on their own.

## Documentation

- **[CARL_user_manual.html](CARL_user_manual.html)** — full user manual,
  also available from CARL's own **About > Help** tab.
- **[CARL/plugin_spec.md](CARL/plugin_spec.md)** — descriptor format for
  adding external command-line tools as CARL plugins.
- **[CARL/taxon_declaration_and_dataIDs.md](CARL/taxon_declaration_and_dataIDs.md)**
  — the data model underlying CARL's NEXUS `CARL` block (taxon declarations,
  nomenclatural actions, and data-ID rules).

## How to cite CARL

> Rodrigo, A. G., Huang, H., Wang, Z., Seldon, D., and Li, T. (2026).
> Classification (AI-Accessible) Research Laboratory, CARL: An integrated
> environment for taxonomic research.

## License

CARL is released under the [MIT License](LICENSE).
