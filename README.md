# CARL — Classification (AI-Accessible) Research Laboratory

CARL is an integrated desktop environment for taxonomic research: build and
edit NEXUS character matrices, retrieve taxonomic and nomenclatural
information from biodiversity databases, generate descriptions, comparisons
and identification keys, and run external phylogenetics tools — with optional
LLM assistance throughout.

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
