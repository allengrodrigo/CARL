"""
literature_cache.py — Cache backend for TaxonGPT literature retrieval pipeline.

All retrieval is programmatic (GBIF, CoL, ZooBank REST APIs).
No LLM calls are made anywhere in this module.

Cache file: <dataset_stem>_literature_cache.json (alongside the .nex file)

NEW-FORMAT entry structure (per taxon key):
{
  "retrieved":          "2026-05-08T10:30:00Z",   # ISO 8601 UTC
  "providers_queried":  ["GBIF", "CoL", "ZooBank"],
  "fields": {
    "scientificName":   {"value": "Hexurella pinea",           "source": "GBIF"},
    "scientificNameAuthorship": {"value": "Gertsch & Platnick, 1979", "source": "ZooBank"}
  },
  "conflicts": [
    {
      "term":               "taxonomicStatus",
      "values":             {"GBIF": "ACCEPTED", "CoL": "accepted"},
      "authoritative":      "GBIF",
      "authoritative_value": "ACCEPTED"
    }
  ],
  "provider_data": {
    "GBIF":    {"scientificName": "Hexurella pinea", ...},
    "CoL":     {"scientificName": "Hexurella pinea", ...},
    "ZooBank": {}
  },
  "error": ""
}

OLD-FORMAT entries (from the compound-mini era) have a "data" key containing
prose text.  is_new_format(entry) distinguishes the two schemas.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone

log = logging.getLogger(__name__)

from biodiversity_apis import (FETCH_FN, PROVIDERS, ADAPTER_META, REQUIRES_KEY,
                               fetch_identifiers, fetch_itis_by_tsn)

# ============================================================
# CONSTANTS
# ============================================================

CACHE_SUFFIX           = "_literature_cache.json"
DESC_CACHE_SUFFIX      = "_descriptions_cache.json"
IMAGES_CACHE_SUFFIX    = "_images_cache.json"
PUB_CACHE_SUFFIX       = "_publications_cache.json"
RESOURCES_CACHE_SUFFIX = "_resources_cache.json"

# Displayed when no provider returned a value for a requested field.
NO_INFO = "No Information Available"

# Polite delay (seconds) between successive full-taxon fetches.
# All three providers are queried per taxon within this window.
INTER_TAXON_DELAY = 1

# Full provider order — index 0 = highest priority.
# Wikipedia and Wikidata are disabled by default (unchecked in Settings > Databases).
DEFAULT_PROVIDER_ORDER = [
    "GBIF", "CoL", "ITIS", "WoRMS", "WSC", "BacDive", "POWO",
    "NCBI", "ZooBank", "CrossRef",
    "BHL", "Plazi", "Wikipedia", "Wikidata",
]
DEFAULT_ENABLED_PROVIDERS = [
    "GBIF", "CoL", "ITIS", "WoRMS",
    "NCBI", "ZooBank", "CrossRef",
    "BHL", "Plazi",
]


# ============================================================
# FORMAT DETECTION
# ============================================================

def is_new_format(entry: dict) -> bool:
    """True when the entry uses the Darwin Core JSON schema (not old prose format)."""
    return isinstance(entry, dict) and "fields" in entry and "data" not in entry


def entry_has_data(entry: dict | None) -> bool:
    """True when an entry (either format) contains usable cached data."""
    if not entry:
        return False
    if is_new_format(entry):
        return bool(entry.get("fields"))
    return bool(entry.get("data") or entry.get("no_data"))


# ============================================================
# CACHE PATH AND I/O
# ============================================================

def cache_path(nexus_filepath: str) -> str:
    """Return the JSON cache path corresponding to a NEXUS file."""
    base = os.path.splitext(nexus_filepath)[0]
    return base + CACHE_SUFFIX


def load_cache(nexus_filepath: str) -> dict:
    """Load and return the cache dict; empty dict on missing or unreadable file."""
    path = cache_path(nexus_filepath)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[literature_cache] Could not load cache at {path}: {e}")
        return {}


def save_cache_atomic(cache: dict, nexus_filepath: str) -> None:
    """Write cache atomically (temp file → os.replace) to prevent corruption."""
    path = cache_path(nexus_filepath)
    dir_ = os.path.dirname(os.path.abspath(path))
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=dir_, suffix=".tmp", delete=False
        ) as tmp:
            json.dump(cache, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, path)
    except OSError as e:
        print(f"[literature_cache] Could not save cache to {path}: {e}")
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ============================================================
# DESCRIPTIONS + IMAGES CACHE HELPERS
# ============================================================

def _aux_cache_path(nexus_filepath: str, suffix: str) -> str:
    base = os.path.splitext(nexus_filepath)[0]
    return base + suffix


def load_descriptions_cache(nexus_filepath: str) -> dict:
    path = _aux_cache_path(nexus_filepath, DESC_CACHE_SUFFIX)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_descriptions_cache(cache: dict, nexus_filepath: str) -> None:
    _save_aux_cache(cache, _aux_cache_path(nexus_filepath, DESC_CACHE_SUFFIX))


def load_images_cache(nexus_filepath: str) -> dict:
    path = _aux_cache_path(nexus_filepath, IMAGES_CACHE_SUFFIX)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_images_cache(cache: dict, nexus_filepath: str) -> None:
    _save_aux_cache(cache, _aux_cache_path(nexus_filepath, IMAGES_CACHE_SUFFIX))


def load_publications_cache(nexus_filepath: str) -> dict:
    path = _aux_cache_path(nexus_filepath, PUB_CACHE_SUFFIX)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_publications_cache(cache: dict, nexus_filepath: str) -> None:
    _save_aux_cache(cache, _aux_cache_path(nexus_filepath, PUB_CACHE_SUFFIX))


_RESOURCES_CACHE_VERSION = 2


def load_resources_cache(nexus_filepath: str) -> dict:
    """Load the resources cache (sandbox-style reports per taxon)."""
    path = _aux_cache_path(nexus_filepath, RESOURCES_CACHE_SUFFIX)
    if not os.path.exists(path):
        return {"_cache_version": _RESOURCES_CACHE_VERSION}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"_cache_version": _RESOURCES_CACHE_VERSION}
    if data.get("_cache_version", 0) < _RESOURCES_CACHE_VERSION:
        return {"_cache_version": _RESOURCES_CACHE_VERSION}
    return data


def save_resources_cache(cache: dict, nexus_filepath: str) -> None:
    """Save the resources cache atomically."""
    _save_aux_cache(cache, _aux_cache_path(nexus_filepath, RESOURCES_CACHE_SUFFIX))


def _save_aux_cache(cache: dict, path: str) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=dir_, suffix=".tmp", delete=False
        ) as tmp:
            json.dump(cache, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, path)
    except OSError as e:
        print(f"[cache] Could not save {path}: {e}")
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ============================================================
# MERGE AND CONFLICT DETECTION
# ============================================================

# Equivalent taxonomic status terms across providers (GBIF/CoL/ITIS vocabularies).
# Values are normalised to a canonical form before conflict comparison so that
# e.g. GBIF "ACCEPTED", CoL "accepted", ITIS "valid" are not reported as conflicts.
_STATUS_SYNONYMS: dict[str, str] = {
    "valid":        "accepted",
    "not accepted": "synonym",
    "invalid":      "synonym",
}


def _normalize(value: str, term: str = "") -> str:
    """Normalise a value for conflict comparison (case- and whitespace-insensitive).

    For taxonomicStatus, equivalent cross-provider vocabulary is collapsed to a
    single canonical token so GBIF "ACCEPTED" / CoL "accepted" / ITIS "valid"
    are not treated as conflicts.
    """
    v = value.strip().lower()
    if term == "taxonomicStatus":
        v = _STATUS_SYNONYMS.get(v, v)
    return v


def merge_results(results_by_provider: dict, provider_order: list) -> tuple:
    """Merge per-provider result dicts into a fields dict and a conflict list.

    Args:
        results_by_provider: {provider_name: {dwc_term: value_str}}
        provider_order:      provider names in descending priority (index 0 = highest)

    Returns:
        fields_dict — {term: {"value": str, "source": provider_name}}
        conflicts   — list of conflict dicts (see module docstring for structure)
    """
    all_terms: set[str] = set()
    for pr in results_by_provider.values():
        all_terms.update(pr.keys())

    fields_dict: dict[str, dict] = {}
    conflicts: list[dict] = []

    for term in sorted(all_terms):
        # Collect non-empty values per provider, in priority order
        term_values: dict[str, str] = {}
        for provider in provider_order:
            v = results_by_provider.get(provider, {}).get(term)
            if v is not None and str(v).strip():
                term_values[provider] = str(v).strip()

        if not term_values:
            continue

        # Highest-priority provider with a value is authoritative
        authoritative = next(
            (p for p in provider_order if p in term_values), None
        )
        if authoritative is None:
            continue

        fields_dict[term] = {
            "value":  term_values[authoritative],
            "source": authoritative,
        }

        # Conflict: two or more providers with different normalised values.
        # Provider-specific ID fields are exempt — each database uses its own namespace.
        _ID_TERMS = {"taxonID", "taxonConceptID", "parentNameUsageID",
                     "acceptedNameUsageID", "originalNameUsageID", "nameAccordingToID",
                     "namePublishedInID", "scientificNameID"}
        if len(term_values) >= 2 and term not in _ID_TERMS:
            norm = {p: _normalize(v, term) for p, v in term_values.items()}
            if len(set(norm.values())) > 1:
                conflicts.append({
                    "term":                term,
                    "values":              dict(term_values),
                    "authoritative":       authoritative,
                    "authoritative_value": term_values[authoritative],
                })

    return fields_dict, conflicts


def redetect_conflicts(entry: dict, new_provider_order: list) -> dict:
    """Re-run merge/conflict detection on stored provider_data with a new ranking.

    Useful when the user changes authority priority without re-fetching.
    Returns an updated copy of the entry; leaves old-format entries unchanged.
    """
    if not is_new_format(entry):
        return entry
    results_by_provider = entry.get("provider_data", {})
    active_order = [p for p in new_provider_order if p in results_by_provider]
    fields_dict, conflicts = merge_results(results_by_provider, active_order)
    updated = dict(entry)
    updated["fields"]    = fields_dict
    updated["conflicts"] = conflicts
    return updated


# ============================================================
# RETRIEVAL
# ============================================================

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_taxon_entry(
    taxon_name: str,
    enabled_providers: list,
    provider_order: list,
    fields: set,
    status_fn=None,
    rank: str = "",
    api_keys: dict = None,
) -> dict:
    """Fetch and merge data for one taxon from all enabled providers.

    Delegates to run_registry() for parallel execution and ID consolidation.
    Signature is backwards-compatible; rank and api_keys are optional extras.
    """
    return run_registry(
        taxon_name,
        rank,
        enabled_providers,
        provider_order,
        fields,
        api_keys=api_keys,
        status_fn=status_fn,
    )


def run_registry(
    taxon_name: str,
    rank: str,
    enabled_providers: list,
    provider_order: list,
    fields: set,
    api_keys: dict = None,
    status_fn=None,
) -> dict:
    """3-stage parallel retrieval pipeline replacing the sequential fetch_taxon_entry.

    Stage 1 — ID pool: call fetch_identifiers (GBIF backbone) to collect
      cross-database IDs (GBIF usageKey, ITIS TSN, NCBI TaxID, ZooBank LSID).

    Stage 2 — Pass 1 (parallel): fire all enabled providers simultaneously
      by taxon name using ThreadPoolExecutor.

    Stage 3 — Pass 2 (targeted): for providers that returned {} in Pass 1
      but whose pass2_id_type is present in the id_pool, re-query by ID.
      Currently implemented: ITIS by TSN.

    Returns the same dict schema as fetch_taxon_entry for drop-in compatibility,
    with the addition of an "id_pool" key for downstream inspection.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    api_keys = api_keys or {}
    errors: list[str] = []

    # ── Stage 1: build id_pool ────────────────────────────────────────
    if status_fn:
        status_fn(f"Resolving identifiers: {taxon_name}...")
    try:
        id_info = fetch_identifiers(taxon_name, rank or "")
    except Exception as exc:
        log.warning("[run_registry id_pool] %s → %s", taxon_name, exc)
        id_info = {}

    id_pool: dict[str, str] = {
        "gbif_usage_key": id_info.get("usageKey") or "",
        "itis_tsn":       id_info.get("tsn")      or "",
        "ncbi_taxid":     id_info.get("taxid")    or "",
        "zoobank_lsid":   id_info.get("lsid")     or "",
    }

    # ── Stage 2: Pass 1 — all providers in parallel by name ──────────
    providers_to_run: list[str] = []
    for p in enabled_providers:
        if p not in FETCH_FN:
            continue
        providers_to_run.append(p)

    results_by_provider: dict[str, dict] = {}

    if status_fn:
        status_fn(f"Querying {len(providers_to_run)} databases: {taxon_name}...")

    with ThreadPoolExecutor(max_workers=max(len(providers_to_run), 1)) as ex:
        future_map = {
            ex.submit(FETCH_FN[p], taxon_name, fields): p
            for p in providers_to_run
        }
        for future in as_completed(future_map):
            p = future_map[future]
            try:
                results_by_provider[p] = future.result(timeout=30) or {}
            except Exception as exc:
                errors.append(f"{p}: {exc}")
                results_by_provider[p] = {}

    # ── Stage 3: Pass 2 — retry failed providers using id_pool ───────
    for p in providers_to_run:
        if results_by_provider.get(p):
            continue                          # Pass 1 succeeded; nothing to do
        id_type = ADAPTER_META.get(p, {}).get("pass2_id_type", "")
        id_val  = id_pool.get(id_type, "")
        if not id_val:
            continue

        if status_fn:
            status_fn(f"Pass 2 ({p} by {id_type}): {taxon_name}...")
        try:
            if p == "ITIS":
                results_by_provider[p] = fetch_itis_by_tsn(id_val, fields)
            # Additional Pass 2 handlers to be added as needed:
            # elif p == "WoRMS":  results_by_provider[p] = fetch_worms_by_aphia(id_val, fields)
            # elif p == "GBIF":   results_by_provider[p] = fetch_gbif_by_key(id_val, fields)
        except Exception as exc:
            errors.append(f"{p} Pass2: {exc}")

    # ── Field merge ───────────────────────────────────────────────────
    active_order = [p for p in provider_order if p in providers_to_run]
    fields_dict, conflicts = merge_results(results_by_provider, active_order)

    for term in fields:
        if term not in fields_dict:
            fields_dict[term] = {"value": NO_INFO, "source": ""}

    return {
        "retrieved":         _now(),
        "providers_queried": list(providers_to_run),
        "fields":            fields_dict,
        "conflicts":         conflicts,
        "provider_data":     results_by_provider,
        "id_pool":           id_pool,
        "error":             "; ".join(errors),
    }
