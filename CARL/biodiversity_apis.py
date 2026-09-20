"""
biodiversity_apis.py — Programmatic retrieval from GBIF, CoL, and ZooBank.

Public API:
  fetch_gbif(taxon_name, fields)    → {dwc_term: str_value}
  fetch_col(taxon_name, fields)     → {dwc_term: str_value}
  fetch_zoobank(taxon_name, fields) → {dwc_term: str_value}
  set_contact_email(email)          → updates the User-Agent header
  PROVIDERS                         → ordered list of provider name strings
  FETCH_FN                          → {provider_name: fetch_function}

Each fetch function:
  - Accepts taxon_name (str) and fields (set[str] of Darwin Core terms)
  - Returns a flat {dwc_term: str_value} dict for whatever was found
  - Never raises — all failures are logged; partial results are returned
  - Values are always non-empty strings

No LLM calls are made anywhere in this module.
"""

import re
import time
import logging
import requests
from darwin_core import BY_SECTION

log = logging.getLogger(__name__)

# ============================================================
# USER-AGENT
# ============================================================

_USER_AGENT = "TaxonGPT/2.0 (taxonomic research tool)"


def set_contact_email(email: str) -> None:
    """Embed a contact email in the User-Agent (good practice for API use)."""
    global _USER_AGENT
    _USER_AGENT = f"TaxonGPT/2.0 (taxonomic research tool; contact: {email})"


def _headers() -> dict:
    return {"User-Agent": _USER_AGENT, "Accept": "application/json"}




# ============================================================
# RETRY HELPER
# ============================================================

_URL_QUERY_RE = re.compile(r"(https?://[^\s'\"?]+)\?[^\s'\"]*")


def _redact_query(exc) -> str:
    """str(exc) with any URL query string stripped. requests' HTTPError text
    embeds the full request URL, so for APIs that take the key as a query
    parameter (WSC apiKey, BHL apikey) logging the raw exception would write
    the key to the log/console."""
    return _URL_QUERY_RE.sub(r"\1?<redacted>", str(exc))


def _get_with_retry(url: str, params: dict = None, headers: dict = None,
                    timeout: int = 25, retries: int = 1, retry_delay: float = 3.0):
    """GET with one retry on timeout or 5xx errors."""
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            if attempt < retries:
                log.info("Timeout on %s — retrying in %.0fs", url, retry_delay)
                time.sleep(retry_delay)
                continue
            raise
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code >= 500 and attempt < retries:
                log.info("Server error %s on %s — retrying", exc.response.status_code, url)
                time.sleep(retry_delay)
                continue
            raise


# ============================================================
# OCCURRENCE-RELATED FIELD SET
# Terms that require an occurrence-level API call (not just taxonomy)
# ============================================================

_OCC_TERMS: set[str] = (
    {f.term for f in BY_SECTION["Occurrence"]}
    | {f.term for f in BY_SECTION["Event"]}
    | {f.term for f in BY_SECTION["Location"]}
)


# ============================================================
# SHARED HELPERS
# ============================================================

def _add(result: dict, term: str, value, fields: set) -> None:
    """Add term → str(value) to result if term is requested and value is non-empty."""
    if term not in fields:
        return
    if value is None:
        return
    s = str(value).strip()
    if s:
        result[term] = s


def _year_from_text(text: str) -> str | None:
    """Extract a plausible publication year from a free-text string."""
    m = re.search(r'\b(1[5-9]\d{2}|20[0-2]\d)\b', text or "")
    return m.group(1) if m else None


# ============================================================
# GBIF
# ============================================================

_GBIF = "https://api.gbif.org/v1"

# GBIF species record keys → Darwin Core terms
# Note: GBIF uses "clazz" for class (avoids Python keyword conflict)
_GBIF_SP_MAP: dict[str, str] = {
    "canonicalName":       "scientificName",   # bare name without authorship
    "authorship":          "scientificNameAuthorship",
    "rank":                "taxonRank",
    "taxonomicStatus":     "taxonomicStatus",
    "kingdom":             "kingdom",
    "phylum":              "phylum",
    "clazz":               "class",
    "class":               "class",      # some responses use "class" directly
    "order":               "order",
    "family":              "family",
    "genus":               "genus",
    "subgenus":            "subgenus",
    "publishedIn":         "namePublishedIn",
    "remarks":             "taxonRemarks",
    "vernacularName":      "vernacularName",
}

# GBIF occurrence record keys → Darwin Core terms
_GBIF_OCC_MAP: dict[str, str] = {
    "occurrenceID":                   "occurrenceID",
    "catalogNumber":                  "catalogNumber",
    "otherCatalogNumbers":            "otherCatalogNumbers",
    "recordedBy":                     "recordedBy",
    "individualCount":                "individualCount",
    "sex":                            "sex",
    "lifeStage":                      "lifeStage",
    "reproductiveCondition":          "reproductiveCondition",
    "behavior":                       "behavior",
    "establishmentMeans":             "establishmentMeans",
    "degreeOfEstablishment":          "degreeOfEstablishment",
    "occurrenceStatus":               "occurrenceStatus",
    "preparations":                   "preparations",
    "disposition":                    "disposition",
    "associatedReferences":           "associatedReferences",
    "associatedSequences":            "associatedSequences",
    "associatedTaxa":                 "associatedTaxa",
    "occurrenceRemarks":              "occurrenceRemarks",
    # Event
    "eventID":                        "eventID",
    "fieldNumber":                    "fieldNumber",
    "eventDate":                      "eventDate",
    "year":                           "year",
    "month":                          "month",
    "day":                            "day",
    "verbatimEventDate":              "verbatimEventDate",
    "habitat":                        "habitat",
    "samplingProtocol":               "samplingProtocol",
    "samplingEffort":                 "samplingEffort",
    "fieldNotes":                     "fieldNotes",
    "eventRemarks":                   "eventRemarks",
    # Location
    "continent":                      "continent",
    "waterBody":                      "waterBody",
    "islandGroup":                    "islandGroup",
    "island":                         "island",
    "country":                        "country",
    "countryCode":                    "countryCode",
    "stateProvince":                  "stateProvince",
    "county":                         "county",
    "municipality":                   "municipality",
    "locality":                       "locality",
    "verbatimLocality":               "verbatimLocality",
    "minimumElevationInMeters":       "minimumElevationInMeters",
    "maximumElevationInMeters":       "maximumElevationInMeters",
    "minimumDepthInMeters":           "minimumDepthInMeters",
    "maximumDepthInMeters":           "maximumDepthInMeters",
    "decimalLatitude":                "decimalLatitude",
    "decimalLongitude":               "decimalLongitude",
    "coordinateUncertaintyInMeters":  "coordinateUncertaintyInMeters",
    "geodeticDatum":                  "geodeticDatum",
    "verbatimLatitude":               "verbatimLatitude",
    "verbatimLongitude":              "verbatimLongitude",
    "verbatimCoordinateSystem":       "verbatimCoordinateSystem",
    "verbatimSRS":                    "verbatimSRS",
    "footprintWKT":                   "footprintWKT",
    "georeferencedBy":                "georeferencedBy",
    "georeferencedDate":              "georeferencedDate",
    "georeferenceProtocol":           "georeferenceProtocol",
    "georeferenceSources":            "georeferenceSources",
    "georeferenceRemarks":            "georeferenceRemarks",
    # Identification
    "identifiedBy":                   "identifiedBy",
    "dateIdentified":                 "dateIdentified",
    "identificationReferences":       "identificationReferences",
    "identificationRemarks":          "identificationRemarks",
    "identificationQualifier":        "identificationQualifier",
    "typeStatus":                     "typeStatus",
    # Record-level
    "institutionCode":                "institutionCode",
    "collectionCode":                 "collectionCode",
    "datasetName":                    "datasetName",
    "basisOfRecord":                  "basisOfRecord",
    "bibliographicCitation":          "bibliographicCitation",
    "references":                     "references",
    "dynamicProperties":              "dynamicProperties",
    "informationWithheld":            "informationWithheld",
    "dataGeneralizations":            "dataGeneralizations",
}

# Ranks returned by GBIF classification in occurrence records
_GBIF_RANK_TERMS = {
    "kingdom", "phylum", "class", "order", "family", "genus",
}


def _gbif_get(path: str, params: dict = None):
    try:
        r = _get_with_retry(f"{_GBIF}{path}", params=params, headers=_headers())
        return r.json()
    except Exception as exc:
        log.warning("[GBIF] %s params=%s → %s", path, params, exc)
        return None


def _gbif_match_strict(name: str, rank: str = None) -> dict | None:
    """Call /species/match and return the result only for matchType == 'EXACT'.
    Rejects FUZZY and HIGHERRANK matches so that misspelled or corrected names
    never silently resolve to a different taxon.
    """
    params: dict = {"name": name}
    if rank:
        params["rank"] = rank.upper()
    result = _gbif_get("/species/match", params)
    if not result or result.get("matchType") != "EXACT":
        return None
    return result


def fetch_gbif(taxon_name: str, fields: set) -> dict:
    """Return {dwc_term: value} for the requested fields from GBIF."""
    result: dict[str, str] = {}

    # 1. Species match — exact only; reject FUZZY/HIGHERRANK silent corrections
    match = _gbif_match_strict(taxon_name)
    if not match:
        return {}
    usage_key = match.get("usageKey")
    if not usage_key:
        return {}

    # 2. Full species record (authoritative; overrides match where keys overlap)
    detail = _gbif_get(f"/species/{usage_key}") or {}
    sp = {**match, **detail}

    # Direct field mappings
    for gbif_key, dwc_term in _GBIF_SP_MAP.items():
        _add(result, dwc_term, sp.get(gbif_key), fields)

    # nomenclaturalStatus may be a list (Set<NomenclaturalStatus> in GBIF model)
    if "nomenclaturalStatus" in fields:
        ns = sp.get("nomenclaturalStatus")
        if isinstance(ns, list):
            _add(result, "nomenclaturalStatus", "; ".join(str(v) for v in ns), fields)
        else:
            _add(result, "nomenclaturalStatus", ns, fields)

    # specificEpithet — second token of canonicalName
    if "specificEpithet" in fields:
        parts = sp.get("canonicalName", "").split()
        if len(parts) >= 2:
            result["specificEpithet"] = parts[1]

    # infraspecificEpithet — third token of canonicalName
    if "infraspecificEpithet" in fields:
        parts = sp.get("canonicalName", "").split()
        if len(parts) >= 3:
            result["infraspecificEpithet"] = parts[2]

    # namePublishedInYear — extract from publishedIn string
    if "namePublishedInYear" in fields and "namePublishedInYear" not in result:
        _add(result, "namePublishedInYear",
             _year_from_text(sp.get("publishedIn", "")), fields)

    # taxonID
    _add(result, "taxonID", str(usage_key), fields)

    # acceptedNameUsageID / acceptedNameUsage
    acc_key = sp.get("acceptedKey")
    if acc_key:
        _add(result, "acceptedNameUsageID", str(acc_key), fields)
        if "acceptedNameUsage" in fields and acc_key != usage_key:
            acc = _gbif_get(f"/species/{acc_key}") or {}
            _add(result, "acceptedNameUsage", acc.get("canonicalName"), fields)
    elif "acceptedNameUsage" in fields:
        _add(result, "acceptedNameUsage", sp.get("canonicalName"), fields)

    # parentNameUsageID / parentNameUsage
    par_key = sp.get("parentKey")
    if par_key:
        _add(result, "parentNameUsageID", str(par_key), fields)
        if "parentNameUsage" in fields:
            par = _gbif_get(f"/species/{par_key}") or {}
            _add(result, "parentNameUsage", par.get("canonicalName"), fields)

    # originalNameUsage (basionym)
    bas_key = sp.get("basionymKey")
    if bas_key:
        _add(result, "originalNameUsageID", str(bas_key), fields)
        if "originalNameUsage" in fields:
            bas = _gbif_get(f"/species/{bas_key}") or {}
            _add(result, "originalNameUsage", bas.get("canonicalName"), fields)
    elif "originalNameUsage" in fields:
        # basionym name may be directly on the record
        _add(result, "originalNameUsage", sp.get("basionym"), fields)

    # 3. Occurrence-level fields
    if fields & _OCC_TERMS:
        occ_data = _gbif_get("/occurrence/search",
                              {"taxonKey": usage_key, "limit": 1})
        occ_list = (occ_data or {}).get("results", [])
        if occ_list:
            occ = occ_list[0]
            for gbif_key, dwc_term in _GBIF_OCC_MAP.items():
                _add(result, dwc_term, occ.get(gbif_key), fields)

    return result


# ============================================================
# CATALOGUE OF LIFE  (ChecklistBank, dataset key = 3)
# ============================================================

_COL = "https://api.checklistbank.org"
_COL_KEY = "3"   # Catalogue of Life dataset in ChecklistBank

# Rank strings returned by ChecklistBank → Darwin Core terms
_COL_RANK_MAP: dict[str, str] = {
    "KINGDOM":     "kingdom",
    "PHYLUM":      "phylum",
    "CLASS":       "class",
    "ORDER":       "order",
    "SUPERFAMILY": "superfamily",
    "FAMILY":      "family",
    "SUBFAMILY":   "subfamily",
    "TRIBE":       "tribe",
    "SUBTRIBE":    "subtribe",
    "GENUS":       "genus",
    "SUBGENUS":    "subgenus",
}


def _col_get(path: str, params: dict = None):
    try:
        # CoL/ChecklistBank can be slow; 30s timeout, one retry
        r = _get_with_retry(f"{_COL}{path}", params=params, headers=_headers(),
                             timeout=30, retries=1, retry_delay=5.0)
        return r.json()
    except Exception as exc:
        log.warning("[CoL] %s params=%s → %s", path, params, exc)
        return None


def fetch_col(taxon_name: str, fields: set) -> dict:
    """Return {dwc_term: value} for the requested fields from Catalogue of Life."""
    result: dict[str, str] = {}

    # 1. Name search
    search = _col_get(
        f"/dataset/{_COL_KEY}/nameusage/search",
        {"q": taxon_name, "limit": 10}
    )
    items = (search or {}).get("result", [])
    if not items:
        return {}

    # Prefer exact match; otherwise take first result
    usage = None
    for item in items:
        u = item.get("usage") or {}
        canon = (u.get("name") or {}).get("scientificName", "")
        if canon.lower() == taxon_name.lower():
            usage = u
            classification = item.get("classification", [])
            break
    if usage is None:
        usage = items[0].get("usage") or {}
        classification = items[0].get("classification", [])

    name_obj = usage.get("name") or {}
    usage_id = usage.get("id", "")
    status = (usage.get("status") or "").lower()

    # Core name fields
    _add(result, "scientificName",          name_obj.get("scientificName"),    fields)
    _add(result, "scientificNameAuthorship", name_obj.get("authorship"),        fields)
    _add(result, "taxonRank",               name_obj.get("rank"),              fields)
    _add(result, "specificEpithet",         name_obj.get("specificEpithet"),   fields)
    _add(result, "infraspecificEpithet",    name_obj.get("infraspecificEpithet"), fields)
    _add(result, "genus",                   name_obj.get("genus"),             fields)
    _add(result, "subgenus",               name_obj.get("infragenericEpithet"), fields)
    _add(result, "taxonomicStatus",         status,                            fields)
    _add(result, "taxonID",                 usage_id,                          fields)
    _add(result, "taxonRemarks",            usage.get("remarks"),              fields)

    # Identifier: link field (often a CoL or external URL)
    link = usage.get("link")
    if link:
        _add(result, "references", link, fields)

    # Classification hierarchy
    for node in classification:
        rank = (node.get("rank") or "").upper()
        dwc_term = _COL_RANK_MAP.get(rank)
        if dwc_term:
            _add(result, dwc_term, node.get("name"), fields)

    # acceptedNameUsage: if synonym, fetch the accepted record
    if status == "synonym":
        acc_id = usage.get("parentId")
        if acc_id:
            _add(result, "acceptedNameUsageID", acc_id, fields)
            if "acceptedNameUsage" in fields:
                acc_data = _col_get(f"/dataset/{_COL_KEY}/nameusage/{acc_id}") or {}
                acc_usage = acc_data.get("usage") or acc_data
                acc_name = (acc_usage.get("name") or {}).get("scientificName")
                _add(result, "acceptedNameUsage", acc_name, fields)
    else:
        _add(result, "acceptedNameUsage",
             name_obj.get("scientificName"), fields)

    # 2. Publication details (requires fetching the full nameusage record)
    pub_fields = {"namePublishedIn", "namePublishedInYear", "namePublishedInID"}
    if fields & pub_fields and usage_id:
        detail = _col_get(f"/dataset/{_COL_KEY}/nameusage/{usage_id}") or {}
        full_name = (detail.get("usage") or {}).get("name") or detail.get("name") or {}
        pub = full_name.get("publishedIn")
        if isinstance(pub, dict):
            citation = (pub.get("citation") or pub.get("title") or "").strip()
            _add(result, "namePublishedIn",    citation,          fields)
            _add(result, "namePublishedInID",  pub.get("id"),     fields)
            year = pub.get("year")
            _add(result, "namePublishedInYear",
                 str(year) if year else _year_from_text(citation), fields)
        elif isinstance(pub, str) and pub.strip():
            _add(result, "namePublishedIn", pub, fields)
            _add(result, "namePublishedInYear", _year_from_text(pub), fields)

    return result


# ============================================================
# ITIS  (Integrated Taxonomic Information System)
# US government database — public API, no authentication required.
# ============================================================

_ITIS = "https://www.itis.gov/ITISWebService/jsonservice"

# ITIS rank names → Darwin Core terms (lowercased match)
_ITIS_RANK_MAP: dict[str, str] = {
    "kingdom":    "kingdom",
    "phylum":     "phylum",
    "division":   "phylum",      # botanical equivalent
    "class":      "class",
    "order":      "order",
    "superfamily": "superfamily",
    "family":     "family",
    "subfamily":  "subfamily",
    "tribe":      "tribe",
    "subtribe":   "subtribe",
    "genus":      "genus",
    "subgenus":   "subgenus",
}


def _itis_get(endpoint: str, params: dict = None, silent_404: bool = False):
    try:
        r = _get_with_retry(f"{_ITIS}/{endpoint}", params=params,
                            headers=_headers(), timeout=25)
        data = r.json()
        return data if isinstance(data, dict) else None
    except requests.exceptions.HTTPError as exc:
        if silent_404 and exc.response is not None and exc.response.status_code == 404:
            return None  # ITIS returns 404 meaning "no records" — not an error
        log.warning("[ITIS] %s params=%s → %s", endpoint, params, exc)
        return None
    except Exception as exc:
        log.warning("[ITIS] %s params=%s → %s", endpoint, params, exc)
        return None


def _as_dict(val) -> dict:
    """Return val if it is a dict; otherwise return empty dict."""
    return val if isinstance(val, dict) else {}


def fetch_itis(taxon_name: str, fields: set) -> dict:
    """Return {dwc_term: value} for the requested fields from ITIS."""
    result: dict[str, str] = {}

    # 1. Search by scientific name → get TSN
    search = _itis_get("searchByScientificName", {"srchKey": taxon_name})
    raw_names = _as_dict(search).get("scientificNames") or []
    names = [n for n in (raw_names if isinstance(raw_names, list) else [])
             if isinstance(n, dict)]
    if not names:
        return {}

    # Prefer exact match on combinedName; fall back to first result
    name_lower = taxon_name.lower()
    match = next(
        (n for n in names if (n.get("combinedName") or "").lower() == name_lower),
        names[0]
    )
    tsn = str(match.get("tsn") or "").strip()
    if not tsn:
        return {}

    _add(result, "taxonID",              tsn,                        fields)
    _add(result, "scientificName",       match.get("combinedName"),  fields)
    _add(result, "specificEpithet",      match.get("unitName2"),     fields)
    _add(result, "infraspecificEpithet", match.get("unitName3"),     fields)
    # kingdom is a string directly on the search result
    _add(result, "kingdom",              match.get("kingdom"),       fields)

    # 2. Full record — rank, authorship, taxonomic status, kingdom, publications
    rec        = _as_dict(_itis_get("getFullRecordFromTSN", {"tsn": tsn}))
    rank_obj   = _as_dict(rec.get("taxRank"))
    author_obj = _as_dict(rec.get("taxonAuthor"))
    usage_obj  = _as_dict(rec.get("usage"))

    # ITIS rank strings sometimes have trailing whitespace
    _add(result, "taxonRank",
         (rank_obj.get("rankName") or "").strip(), fields)

    authorship = (author_obj.get("authorship") or "").strip()
    _add(result, "scientificNameAuthorship", authorship, fields)

    status = (usage_obj.get("taxonUsageRating") or "").strip()
    _add(result, "taxonomicStatus", status, fields)

    # Kingdom fallback from full record (has trailing whitespace too)
    if "kingdom" not in result:
        kingdom_obj = _as_dict(rec.get("kingdom"))
        _add(result, "kingdom",
             (kingdom_obj.get("kingdomName") or "").strip(), fields)

    # Publications — ITIS wraps the list in a SvcTaxonPublicationList dict;
    # the actual publication objects are under the "publications" key.
    pub_fields = {"namePublishedIn", "namePublishedInYear", "bibliographicCitation"}
    if fields & pub_fields:
        pub_wrapper = _as_dict(rec.get("publicationList"))
        pub_list    = pub_wrapper.get("publications") or []
        for pub in (pub_list if isinstance(pub_list, list) else []):
            if not isinstance(pub, dict):
                continue
            citation = (pub.get("fullReference") or "").strip()
            if citation:
                _add(result, "namePublishedIn",      citation, fields)
                _add(result, "bibliographicCitation", citation, fields)
                year = str(pub.get("pubYear") or "").strip()
                _add(result, "namePublishedInYear",
                     year or _year_from_text(citation), fields)
                break

    # Year fallback: extract from authorship "(Author, 1979)"
    if "namePublishedInYear" not in result and authorship:
        _add(result, "namePublishedInYear", _year_from_text(authorship), fields)

    # 3. Accepted name (if synonym / not accepted)
    if status.lower() in ("invalid", "not accepted", "synonym"):
        acc_data = _as_dict(_itis_get("getAcceptedNamesFromTSN", {"tsn": tsn}))
        acc_raw  = acc_data.get("acceptedNames") or []
        acc_list = [a for a in (acc_raw if isinstance(acc_raw, list) else [])
                    if isinstance(a, dict)]
        if acc_list:
            acc          = acc_list[0]
            acc_name_obj = _as_dict(acc.get("acceptedName"))
            _add(result, "acceptedNameUsage",
                 acc_name_obj.get("combinedName"), fields)
            _add(result, "acceptedNameUsageID",
                 str(acc.get("acceptedTsn") or ""), fields)

    return result


def fetch_itis_by_tsn(tsn: str, fields: set) -> dict:
    """ITIS Pass 2: fetch DwC fields directly by TSN (skips name search).

    Used by run_registry() when ITIS failed the name search but another
    provider (typically GBIF) supplied the TSN via the id_pool.
    """
    result: dict[str, str] = {}
    if not tsn:
        return {}

    _add(result, "taxonID", tsn, fields)

    rec        = _as_dict(_itis_get("getFullRecordFromTSN", {"tsn": tsn}))
    if not rec:
        return result

    rank_obj   = _as_dict(rec.get("taxRank"))
    author_obj = _as_dict(rec.get("taxonAuthor"))
    usage_obj  = _as_dict(rec.get("usage"))

    _add(result, "taxonRank",
         (rank_obj.get("rankName") or "").strip(), fields)

    authorship = (author_obj.get("authorship") or "").strip()
    _add(result, "scientificNameAuthorship", authorship, fields)

    status = (usage_obj.get("taxonUsageRating") or "").strip()
    _add(result, "taxonomicStatus", status, fields)

    kingdom_obj = _as_dict(rec.get("kingdom"))
    _add(result, "kingdom",
         (kingdom_obj.get("kingdomName") or "").strip(), fields)

    pub_fields = {"namePublishedIn", "namePublishedInYear", "bibliographicCitation"}
    if fields & pub_fields:
        pub_wrapper = _as_dict(rec.get("publicationList"))
        pub_list    = pub_wrapper.get("publications") or []
        for pub in (pub_list if isinstance(pub_list, list) else []):
            if not isinstance(pub, dict):
                continue
            citation = (pub.get("fullReference") or "").strip()
            if citation:
                _add(result, "namePublishedIn",       citation, fields)
                _add(result, "bibliographicCitation", citation, fields)
                year = str(pub.get("pubYear") or "").strip()
                _add(result, "namePublishedInYear",
                     year or _year_from_text(citation), fields)
                break

    if "namePublishedInYear" not in result and authorship:
        _add(result, "namePublishedInYear", _year_from_text(authorship), fields)

    if status.lower() in ("invalid", "not accepted", "synonym"):
        acc_data = _as_dict(_itis_get("getAcceptedNamesFromTSN", {"tsn": tsn}))
        acc_raw  = acc_data.get("acceptedNames") or []
        acc_list = [a for a in (acc_raw if isinstance(acc_raw, list) else [])
                    if isinstance(a, dict)]
        if acc_list:
            acc          = acc_list[0]
            acc_name_obj = _as_dict(acc.get("acceptedName"))
            _add(result, "acceptedNameUsage",
                 acc_name_obj.get("combinedName"), fields)
            _add(result, "acceptedNameUsageID",
                 str(acc.get("acceptedTsn") or ""), fields)

    return result


# ============================================================
# WORLD REGISTER OF MARINE SPECIES (WoRMS)
# ============================================================

_WORMS = "https://www.marinespecies.org/rest"


def _worms_get(path: str, params: dict = None):
    try:
        import urllib.parse
        url = f"{_WORMS}{path}"
        r = _get_with_retry(url, params=params, headers=_headers(), timeout=20)
        if not r.text.strip():
            return None
        return r.json()
    except Exception as exc:
        log.warning("[WoRMS] %s params=%s → %s", path, params, exc)
        return None


def _fetch_worms_sources(aphia_id: int) -> list:
    """Return the AphiaSourcesByAphiaID list for aphia_id, or [] on failure.

    Each element: {source_id, use, reference, page, doi, url}.
    The 'use' field identifies the role: 'original description',
    'subsequent combination', 'basis of record', etc.
    """
    if not aphia_id:
        return []
    data = _worms_get(f"/AphiaSourcesByAphiaID/{aphia_id}")
    if not isinstance(data, list):
        return []
    return data


def _worms_best_record(taxon_name: str) -> dict | None:
    """Return the best-matching WoRMS AphiaRecord for taxon_name, or None."""
    import urllib.parse
    encoded = urllib.parse.quote(taxon_name)
    records = _worms_get(
        f"/AphiaRecordsByName/{encoded}",
        {"like": "false", "marine_only": "false"},
    )
    if not records or not isinstance(records, list):
        return None

    name_lower = taxon_name.lower()

    # 1. accepted + exact name match
    for r in records:
        if (r.get("status") == "accepted"
                and (r.get("scientificname") or "").lower() == name_lower):
            return r

    # 2. any exact name match (may be synonym)
    rec = next(
        (r for r in records
         if (r.get("scientificname") or "").lower() == name_lower),
        None,
    )
    if rec is None:
        rec = records[0]

    # 3. If synonym, resolve to valid record
    if (rec.get("status") != "accepted"
            and rec.get("valid_AphiaID")
            and rec["valid_AphiaID"] != rec.get("AphiaID")):
        valid = _worms_get(f"/AphiaRecordByAphiaID/{rec['valid_AphiaID']}")
        if isinstance(valid, dict) and valid.get("AphiaID"):
            return valid

    return rec


def fetch_worms(taxon_name: str, fields: set) -> dict:
    """Return {dwc_term: value} for the requested fields from WoRMS."""
    result: dict[str, str] = {}

    rec = _worms_best_record(taxon_name)
    if not rec:
        return {}

    _add(result, "scientificName",          rec.get("scientificname"),   fields)
    _add(result, "scientificNameAuthorship", rec.get("authority"),        fields)
    _add(result, "taxonRank",               rec.get("rank"),             fields)
    _add(result, "taxonomicStatus",         rec.get("status"),           fields)
    _add(result, "kingdom",                 rec.get("kingdom"),          fields)
    _add(result, "phylum",                  rec.get("phylum"),           fields)
    _add(result, "class",                   rec.get("class"),            fields)
    _add(result, "order",                   rec.get("order"),            fields)
    _add(result, "family",                  rec.get("family"),           fields)
    _add(result, "genus",                   rec.get("genus"),            fields)

    aphia_id = rec.get("AphiaID")
    lsid = (rec.get("lsid")
            or (f"urn:lsid:marinespecies.org:taxname:{aphia_id}" if aphia_id else None))
    _add(result, "taxonID", lsid, fields)

    # namePublishedIn from AphiaSourcesByAphiaID — only "original description" source.
    # rec["citation"] is a WoRMS database access citation and must NOT be used here.
    needs_pub = bool(fields & {"namePublishedIn", "namePublishedInYear"})
    orig_ref  = ""
    orig_year = ""
    if needs_pub and aphia_id:
        for src in _fetch_worms_sources(aphia_id):
            use = (src.get("use") or "").lower()
            ref = (src.get("reference") or "").strip()
            if "original description" in use and ref:
                orig_ref  = ref
                orig_year = _year_from_text(ref) or _year_from_text(
                    rec.get("authority", ""))
                break
        if not orig_year:
            orig_year = _year_from_text(rec.get("authority", ""))

    _add(result, "namePublishedIn",     orig_ref,  fields)
    _add(result, "namePublishedInYear", orig_year, fields)

    return result


def fetch_worms_summary(taxon_name: str) -> dict:
    """Fetch WoRMS profile for use in the text report.

    Returns a dict with profile fields plus:
      orig_ref  — raw original-description citation string (or "")
      pub_dicts — list of pub dicts for resolve_publications (one per source)
    Returns empty dict when the taxon is not found in WoRMS.
    """
    rec = _worms_best_record(taxon_name)
    if not rec:
        return {}

    aphia_id = rec.get("AphiaID")
    lsid = (rec.get("lsid")
            or (f"urn:lsid:marinespecies.org:taxname:{aphia_id}" if aphia_id else ""))

    # Fetch bibliographic sources from WoRMS
    sources   = _fetch_worms_sources(aphia_id)
    orig_ref  = ""
    pub_dicts = []
    seen_refs: set = set()
    for src in sources:
        ref = (src.get("reference") or "").strip()
        if not ref or ref in seen_refs:
            continue
        seen_refs.add(ref)
        doi = (src.get("doi") or "").strip()
        pub_dicts.append({
            "doi":          doi,
            "title":        None,
            "csl":          None,
            "raw_citation": ref,
            "sources":      ["WoRMS"],
        })
        if "original description" in (src.get("use") or "").lower() and not orig_ref:
            orig_ref = ref

    return {
        "aphia_id":       aphia_id,
        "lsid":           lsid,
        "scientificname": rec.get("scientificname", ""),
        "authority":      rec.get("authority", ""),
        "rank":           rec.get("rank", ""),
        "status":         rec.get("status", ""),
        "kingdom":        rec.get("kingdom") or "",
        "phylum":         rec.get("phylum") or "",
        "class":          rec.get("class") or "",
        "order":          rec.get("order") or "",
        "family":         rec.get("family") or "",
        "genus":          rec.get("genus") or "",
        "orig_ref":       orig_ref,
        "pub_dicts":      pub_dicts,
    }


def fetch_worms_synonyms(aphia_id: int) -> list:
    """Return WoRMS synonyms for aphia_id via AphiaSynonymsByAphiaID.

    Each item: {"name": str (scientificname + authority), "status": str}.
    Returns [] when aphia_id is falsy or the API returns nothing.
    """
    if not aphia_id:
        return []
    data = _worms_get(f"/AphiaSynonymsByAphiaID/{aphia_id}")
    if not isinstance(data, list):
        return []
    result = []
    for r in data:
        sci = (r.get("scientificname") or "").strip()
        if not sci:
            continue
        auth = (r.get("authority") or "").strip()
        result.append({
            "name":   f"{sci} {auth}".strip() if auth else sci,
            "status": (r.get("status") or "synonym").lower(),
        })
    return result


def fetch_worms_children(aphia_id: int) -> list:
    """Return direct children of aphia_id via AphiaChildrenByAphiaID.

    Each item: {"name": str, "authorship": str, "rank": str}.
    Includes non-marine taxa (marine_only=false).
    """
    if not aphia_id:
        return []
    data = _worms_get(
        f"/AphiaChildrenByAphiaID/{aphia_id}",
        {"marine_only": "false"},
    )
    if not isinstance(data, list):
        return []
    result = []
    for r in data:
        sci = (r.get("scientificname") or "").strip()
        if not sci:
            continue
        auth = (r.get("authority") or "").strip()
        result.append({
            "name":       f"{sci} {auth}".strip() if auth else sci,
            "authorship": auth,
            "rank":       (r.get("rank") or "").lower(),
        })
    return result


# ============================================================
# WSC — World Spider Catalogue
# ============================================================

_WSC = "https://wsc.nmbe.ch/api"
_WSC_API_KEY: str = ""
_WSC_COL_SECTOR = 56185  # ChecklistBank dataset key for WSC source checklist


def set_wsc_api_key(key: str) -> None:
    global _WSC_API_KEY
    _WSC_API_KEY = key.strip()


def _wsc_get(path: str, params: dict = None):
    try:
        p = dict(params or {})
        if _WSC_API_KEY:
            p["apiKey"] = _WSC_API_KEY
        r = _get_with_retry(f"{_WSC}{path}", params=p, headers=_headers(), timeout=20)
        return r.json()
    except Exception as exc:
        log.warning("[WSC] %s params=%s → %s", path, params, _redact_query(exc))
        return None


def _wsc_resolve(taxon_name: str) -> tuple:
    """Return (lsid, name_obj, classification) for taxon_name via ChecklistBank's WSC sector.

    ChecklistBank hosts the WSC checklist as dataset 56185.  Each record's id
    field is the WSC LSID (e.g. 'urn:lsid:nmbe.ch:spidergen:00010'), which is
    then used to call the authenticated WSC API endpoint.

    Returns ("", {}, []) when the taxon is not found.
    """
    try:
        data = _col_get(f"/dataset/{_WSC_COL_SECTOR}/nameusage/search",
                        {"q": taxon_name, "limit": 5})
        results = (data or {}).get("result", [])
        if not results:
            return "", {}, []
        name_lower = taxon_name.lower()
        match = next(
            (r for r in results
             if name_lower in (r.get("usage", {}).get("label") or "").lower()),
            results[0],
        )
        lsid = match.get("id") or (match.get("usage") or {}).get("id") or ""
        if not lsid.startswith("urn:lsid:nmbe.ch:"):
            return "", {}, []
        name_obj        = (match.get("usage") or {}).get("name") or {}
        classification  = match.get("classification") or []
        return lsid, name_obj, classification
    except Exception as exc:
        log.warning("[WSC resolve] %s → %s", taxon_name, exc)
        return "", {}, []


def fetch_wsc_profile(taxon_name: str) -> dict:
    """Return a WSC profile dict for use in the information panel report.

    Name → LSID resolution uses ChecklistBank's WSC sector (no key needed).
    The full record is then fetched from the authenticated WSC API endpoint
    /api/lsid/{lsid}.  The response wraps the data under a "taxon" key.

    Returns {} when no API key is configured or the taxon is not found in WSC.
    Keys: name, author, rank, status, family, family_author, lsid,
          reference (plain text, HTML stripped), reference_doi.
    """
    if not _WSC_API_KEY:
        return {}
    lsid, col_name, col_classification = _wsc_resolve(taxon_name)
    if not lsid:
        return {}

    raw    = _wsc_get(f"/lsid/{lsid}") or {}
    record = raw.get("taxon") or raw  # unwrap {"taxon": {...}}
    if not record:
        return {}

    ref_obj = record.get("referenceObject") or {}
    fam_obj = record.get("familyObject") or {}

    citation_raw = ref_obj.get("reference") or ""
    reference = _html_to_text(citation_raw).strip() if citation_raw else ""

    family_from_col = next(
        (c.get("name") for c in col_classification
         if (c.get("rank") or "").upper() == "FAMILY"),
        None,
    )

    return {
        "name":          record.get("genus") or record.get("species") or taxon_name,
        "author":        record.get("author") or col_name.get("authorship") or "",
        "rank":          record.get("taxonRank") or col_name.get("rank") or "",
        "status":        record.get("status") or "",
        "family":        record.get("family") or family_from_col or "",
        "family_author": fam_obj.get("author") or "",
        "lsid":          record.get("lsid") or lsid,
        "reference":     reference,
        "reference_doi": ref_obj.get("doi") or "",
    }


def fetch_wsc(taxon_name: str, fields: set) -> dict:
    """Return {dwc_term: value} from the World Spider Catalogue.

    Delegates to fetch_wsc_profile() so the API is called only once.
    Fixed higher-classification values (Animalia/Arthropoda/Arachnida/Araneae/ICZN)
    are injected directly — all spiders share these.
    """
    if not _WSC_API_KEY:
        return {}

    p = fetch_wsc_profile(taxon_name)
    if not p:
        return {}

    result: dict[str, str] = {}
    _add(result, "scientificName",           p["name"],   fields)
    _add(result, "scientificNameAuthorship", p["author"], fields)
    _add(result, "taxonRank",                p["rank"],   fields)
    _add(result, "taxonomicStatus",          p["status"], fields)
    _add(result, "family",                   p["family"], fields)
    _add(result, "taxonID",                  p["lsid"],   fields)
    _add(result, "scientificNameID",         p["lsid"],   fields)

    rank_upper = (p["rank"] or "").upper()
    if rank_upper in ("GENUS", "SUBGENUS"):
        _add(result, "genus", p["name"], fields)
    elif rank_upper in ("SPECIES", "SUBSPECIES"):
        parts = p["name"].split()
        if len(parts) >= 2:
            _add(result, "genus",           parts[0], fields)
            _add(result, "specificEpithet", parts[1], fields)

    _add(result, "kingdom",           "Animalia",   fields)
    _add(result, "phylum",            "Arthropoda", fields)
    _add(result, "class",             "Arachnida",  fields)
    _add(result, "order",             "Araneae",    fields)
    _add(result, "nomenclaturalCode", "ICZN",       fields)

    if p["reference"]:
        _add(result, "namePublishedIn",     p["reference"],                       fields)
        _add(result, "namePublishedInYear", _year_from_text(p["reference"]),      fields)
    if p["reference_doi"]:
        _add(result, "namePublishedInID", f"https://doi.org/{p['reference_doi']}", fields)

    return result


# ============================================================
# BacDive — Bacterial Diversity Metadatabase (DSMZ)
# ============================================================

_BACDIVE = "https://api.bacdive.dsmz.de"
_BACDIVE_FETCH_CAP = 10  # max strain records to fetch per taxon query


def _bacdive_get(path: str, params: dict = None):
    try:
        r = _get_with_retry(f"{_BACDIVE}{path}", params=params,
                            headers=_headers(), timeout=20)
        if not r.text.strip():
            return None
        return r.json()
    except Exception as exc:
        log.warning("[BacDive] %s params=%s → %s", path, params, exc)
        return None


def _bd_section(record_data: dict, *keys: str):
    """Return first non-None section value from a BacDive record, trying multiple key names."""
    for k in keys:
        v = record_data.get(k)
        if v is not None:
            return v
    return None


def _parse_bacdive_strain(bacdive_id, record_data: dict) -> dict:
    """Extract displayable fields from one BacDive strain record (inner dict)."""
    out = {"bacdive_id": bacdive_id}

    # General
    general = _bd_section(record_data, "General") or {}
    if isinstance(general, list):
        general = general[0] if general else {}
    out["description"]  = (general.get("description") or "")[:300]
    out["ncbi_taxid"]   = general.get("NCBI tax id") or general.get("ncbi_tax_id", "")

    # Name and Taxonomic Classification
    tax_sec = _bd_section(record_data,
        "Name and taxonomic classification",
        "Name and Taxonomic Classification", "Taxonomy_name", "taxonomy") or []
    if isinstance(tax_sec, dict):
        tax_sec = [tax_sec]
    out["type_strain"]        = False
    out["strain_designation"] = ""
    out["taxonomy"]           = {}
    for entry in tax_sec:
        if not isinstance(entry, dict):
            continue
        ts = str(entry.get("type strain", entry.get("type_strain", ""))).lower()
        if ts in ("yes", "true", "1"):
            out["type_strain"] = True
        sd = entry.get("strain designation", entry.get("strain_designation", ""))
        if sd:
            out["strain_designation"] = str(sd)
        lpsn = entry.get("LPSN", entry.get("lpsn", {}))
        if isinstance(lpsn, dict) and lpsn:
            out["taxonomy"] = {k: lpsn.get(k, "") for k in
                               ("domain", "phylum", "class", "order", "family", "genus", "species")}

    # Morphology
    morph_sec = _bd_section(record_data, "Morphology", "morphology") or []
    if isinstance(morph_sec, dict):
        morph_sec = [morph_sec]
    out["gram_stain"] = out["cell_shape"] = out["motility"] = ""
    for entry in morph_sec:
        if not isinstance(entry, dict):
            continue
        for cm in (entry.get("cell morphology") or entry.get("cell_morphology") or []):
            if not isinstance(cm, dict):
                continue
            out["gram_stain"] = out["gram_stain"] or (cm.get("gram stain") or cm.get("gram_stain", ""))
            out["cell_shape"] = out["cell_shape"] or (cm.get("cell shape") or cm.get("cell_shape", ""))
            mot = cm.get("motility")
            if mot is not None and not out["motility"]:
                out["motility"] = str(mot)

    # Culture and Growth Conditions — temperature range
    culture_sec = _bd_section(record_data,
        "Culture and growth conditions",
        "Culture and Growth Conditions", "Culture_growth_condition") or []
    if isinstance(culture_sec, dict):
        culture_sec = [culture_sec]
    temps = []
    for entry in culture_sec:
        if not isinstance(entry, dict):
            continue
        for temp in (entry.get("culture temp") or entry.get("culture_temp") or []):
            if not isinstance(temp, dict):
                continue
            t = temp.get("temperature") or temp.get("temp")
            growth = str(temp.get("growth", "")).lower()
            if t and growth in ("yes", "+", "positive", "1", "true"):
                temps.append(str(t))
    out["temp_range"] = (", ".join(sorted(set(temps))) + "°C") if temps else ""

    # Physiology — oxygen tolerance
    physio_sec = _bd_section(record_data,
        "Physiology and metabolism",
        "Physiology and Metabolism", "Physiology_metabolism") or []
    if isinstance(physio_sec, dict):
        physio_sec = [physio_sec]
    out["oxygen_tolerance"] = ""
    for entry in physio_sec:
        if not isinstance(entry, dict):
            continue
        ot = entry.get("oxygen tolerance") or entry.get("oxygen_tolerance", "")
        if ot:
            out["oxygen_tolerance"] = str(ot)
            break

    # Safety Information
    safety_sec = _bd_section(record_data,
        "Safety information",
        "Safety Information", "Safety_information") or []
    if isinstance(safety_sec, dict):
        safety_sec = [safety_sec]
    out["biosafety_level"] = out["pathogenicity_human"] = ""
    for entry in safety_sec:
        if not isinstance(entry, dict):
            continue
        for risk in (entry.get("risk assessment") or entry.get("risk_assessment") or []):
            if not isinstance(risk, dict):
                continue
            bsl = risk.get("biosafety level") or risk.get("biosafety_level", "")
            if bsl:
                out["biosafety_level"] = str(bsl)
            ph = risk.get("pathogenicity human") or risk.get("pathogenicity_human", "")
            if ph:
                out["pathogenicity_human"] = str(ph)

    # Sequence Information
    seq_sec = _bd_section(record_data,
        "Sequence information",
        "Sequence Information", "Sequence_information") or []
    if isinstance(seq_sec, dict):
        seq_sec = [seq_sec]
    out["sequences_16s"] = []
    out["sequences_genome"] = []
    for entry in seq_sec:
        if not isinstance(entry, dict):
            continue
        for s in (entry.get("16S sequences") or entry.get("16s_sequences") or []):
            if isinstance(s, dict):
                acc = s.get("accession") or s.get("ENA/NCBI accession", "")
                if acc:
                    out["sequences_16s"].append({"accession": acc, "length": s.get("length", "")})
        for s in (entry.get("Genome sequences") or entry.get("genome_sequences") or []):
            if isinstance(s, dict) and s.get("accession"):
                out["sequences_genome"].append({"accession": s["accession"]})

    # External Links — culture collection numbers
    ext_sec = _bd_section(record_data, "External links", "External Links", "external_links") or {}
    if isinstance(ext_sec, list):
        ext_sec = ext_sec[0] if ext_sec else {}
    out["culture_collection_nos"] = (
        ext_sec.get("culture collection no.", "") or
        ext_sec.get("culture_collection_no", "")
    )

    # Literature — pub_dicts
    lit_sec = _bd_section(record_data, "Reference", "reference", "Literature", "literature") or []
    if isinstance(lit_sec, dict):
        lit_sec = list(lit_sec.values())
    out["pub_dicts"] = []
    for ref in lit_sec:
        if not isinstance(ref, dict):
            continue
        doi     = ref.get("doi", "")
        title   = ref.get("title", "")
        authors = ref.get("authors", "")
        year    = str(ref.get("pubmed year", ref.get("year", "")))
        journal = ref.get("journal", "")
        raw = ""
        if authors and title:
            raw = f"{authors} ({year}). {title}."
            if journal:
                raw += f" {journal}."
        elif doi:
            raw = doi
        if doi or raw:
            out["pub_dicts"].append({
                "doi": doi, "title": title, "csl": None,
                "raw_citation": raw, "sources": ["BacDive"],
            })

    return out


def _bacdive_fetch_strains(taxon_name: str) -> list:
    """Fetch parsed strain records for taxon_name; stops early on first type strain found."""
    parts = taxon_name.strip().split(None, 1)
    genus   = parts[0]
    species = parts[1] if len(parts) > 1 else None
    path = f"/v2/taxon/{genus}/{species}" if species else f"/v2/taxon/{genus}"

    search = _bacdive_get(path)
    if not search or not isinstance(search, dict):
        return []
    ids = search.get("results") or []
    if not ids:
        return []

    strains = []
    for bd_id in ids[:_BACDIVE_FETCH_CAP]:
        raw = _bacdive_get(f"/fetch/{bd_id}")
        if not raw or not isinstance(raw, dict):
            continue
        results = raw.get("results") or {}
        record_data = (results.get(str(bd_id)) or results.get(bd_id)
                       if isinstance(results, dict) else None)
        if not isinstance(record_data, dict):
            continue
        parsed = _parse_bacdive_strain(bd_id, record_data)
        strains.append(parsed)
        if parsed.get("type_strain"):
            break
    return strains


def fetch_bacdive(taxon_name: str, fields: set) -> dict:
    """Return {dwc_term: value} from BacDive (prokaryotes; genus/species only)."""
    result: dict[str, str] = {}
    strains = _bacdive_fetch_strains(taxon_name)
    if not strains:
        return {}
    record = next((s for s in strains if s.get("type_strain")), strains[0])
    tax = record.get("taxonomy") or {}
    sci_name = (tax.get("genus", "") + " " + tax.get("species", "")).strip()
    _add(result, "scientificName",    sci_name or taxon_name,         fields)
    _add(result, "taxonRank",         "genus" if " " not in taxon_name else "species", fields)
    _add(result, "nomenclaturalCode", "ICNP",                         fields)
    _add(result, "kingdom",           "Bacteria",                     fields)
    _add(result, "phylum",            tax.get("phylum", ""),          fields)
    _add(result, "class",             tax.get("class", ""),           fields)
    _add(result, "order",             tax.get("order", ""),           fields)
    _add(result, "family",            tax.get("family", ""),          fields)
    _add(result, "genus",             tax.get("genus", ""),           fields)
    if record.get("type_strain"):
        _add(result, "taxonRemarks",
             f"Type strain: {record['strain_designation'] or str(record['bacdive_id'])}", fields)
    return result


def fetch_bacdive_profile(taxon_name: str) -> dict:
    """Return structured BacDive profile dict for _info_worker display.

    Keys: type_strains (list), total_found (int), pub_dicts (aggregated list).
    Returns {} when BacDive has no data (e.g. ranks above genus).
    """
    strains = _bacdive_fetch_strains(taxon_name)
    if not strains:
        return {}
    type_strains = [s for s in strains if s.get("type_strain")] or strains[:1]

    seen: set = set()
    all_pubs = []
    for s in type_strains:
        for p in s.get("pub_dicts", []):
            key = p.get("doi") or p.get("raw_citation", "")[:60]
            if key and key not in seen:
                seen.add(key)
                all_pubs.append(p)

    return {
        "type_strains": type_strains,
        "total_found":  len(strains),
        "pub_dicts":    all_pubs,
    }


# ============================================================
# IPNI — International Plant Names Index (Royal Botanic Gardens, Kew)
# ============================================================
# Replaces POWO, whose API now sits behind a Cloudflare bot challenge that no
# non-browser client can pass. IPNI is Kew's names index (POWO's own IDs are
# IPNI LSIDs) and its API is open. It holds nomenclature only: name,
# authorship, rank, family/genus, the protologue citation, basionym and
# nomenclatural synonyms, and the names below a taxon. It has no accepted /
# synonym status and no classification above family, so those still come from
# GBIF / CoL.

_IPNI = "https://www.ipni.org/api/1"
_IPNI_PAGE_SIZE = 500
_IPNI_MAX_PAGES = 100

_IPNI_RANK = {
    "fam.": "FAMILY", "subfam.": "SUBFAMILY", "trib.": "TRIBE",
    "subtrib.": "SUBTRIBE", "gen.": "GENUS", "subgen.": "SUBGENUS",
    "sect.": "SECTION", "subsect.": "SUBSECTION", "ser.": "SERIES",
    "subser.": "SUBSERIES", "spec.": "SPECIES", "subsp.": "SUBSPECIES",
    "var.": "VARIETY", "subvar.": "SUBVARIETY", "f.": "FORM",
    "subf.": "SUBFORM",
}

# IPNI detail-record fields that name another name related to this one, with
# the label shown in the Synonyms group. All are nomenclatural relations, not
# taxonomic synonymy.
_IPNI_RELATIONS = (
    ("basionym",             "basionym"),
    ("replacedSynonym",      "replaced synonym"),
    ("nomenclaturalSynonym", "nomenclatural synonym"),
)


def _ipni_rank(rank: str) -> str:
    """IPNI rank abbreviation → the upper-case rank word GBIF uses."""
    r = (rank or "").strip()
    return _IPNI_RANK.get(r.lower(), r.rstrip(".").upper())


def _ipni_get(path: str, params: dict = None):
    try:
        r = _get_with_retry(f"{_IPNI}{path}", params=params,
                            headers=_headers(), timeout=30)
        return r.json()
    except Exception as exc:
        log.warning("[IPNI] %s params=%s → %s", path, params, _redact_query(exc))
        return None


def _ipni_pages(query: str, filt: str = None, max_pages: int = _IPNI_MAX_PAGES):
    """Yield the (non-suppressed, named) hits of an IPNI search one page at a time."""
    for page in range(1, max_pages + 1):
        params = {"q": query, "perPage": _IPNI_PAGE_SIZE, "page": page}
        if filt:
            params["f"] = filt
        data = _ipni_get("/search", params)
        if not isinstance(data, dict):
            return
        results = data.get("results") or []
        yield [r for r in results
               if isinstance(r, dict) and r.get("name") and not r.get("suppressed")]
        # IPNI refuses to page past its maxReturnedRecords (10,000) window.
        if (not results or page >= (data.get("totalPages") or 0)
                or page * _IPNI_PAGE_SIZE >= (data.get("maxReturnedRecords") or 10000)):
            return


def _ipni_search_all(query: str, filt: str = None) -> list:
    out = []
    for hits in _ipni_pages(query, filt):
        out.extend(hits)
    return out


def _ipni_lookup(taxon_name: str) -> dict | None:
    """The IPNI record for an exact name: search hit overlaid with the full
    detail record (citation, basionym, parent, ...). None if not found."""
    name = taxon_name.strip()
    name_l = name.lower()
    if not name_l:
        return None
    # An unfiltered search for a family or genus also matches every name filed
    # under it (82,000+ hits for "Poaceae"), so narrow by the rank category
    # the name's shape implies before falling back to one unfiltered page.
    n_words = len(name.split())
    if n_words == 1:
        attempts = (("f_familial", 1), ("f_generic", 3), (None, 1))
    elif n_words == 2:
        attempts = (("f_specific", 3), (None, 1))
    else:
        attempts = (("f_infraspecific", 3), (None, 1))
    hits = []
    for filt, max_pages in attempts:
        for page_hits in _ipni_pages(name, filt, max_pages):
            hits = [r for r in page_hits if r["name"].lower() == name_l]
            if hits:
                break
        if hits:
            break
    if not hits:
        return None
    # Prefer the primary copy of a name, then one that Kew's checklist covers.
    hits.sort(key=lambda r: (r.get("topCopy") is False, not r.get("inPowo")))
    rec = hits[0]
    detail = _ipni_get(f"/n/{rec['id']}") if rec.get("id") else None
    return {**rec, **detail} if isinstance(detail, dict) else rec


def _ipni_lsid(rec: dict) -> str:
    if rec.get("fqId"):
        return str(rec["fqId"])
    if rec.get("id"):
        return f"urn:lsid:ipni.org:names:{rec['id']}"
    return ""


def _ipni_reference(rec: dict) -> str:
    return re.sub(r"\s+", " ", rec.get("reference") or "").strip()


def _ipni_citation(rec: dict) -> str:
    """Protologue citation, e.g. 'Calyptochloa C.E.Hubb., Hooker's Icon. Pl.
    33: t. 3210. 1933'. Empty when IPNI has no reference for the name."""
    ref = _ipni_reference(rec)
    if not ref:
        return ""
    head = f"{rec.get('name', '')} {(rec.get('authors') or '').strip()}".strip()
    return f"{head}, {ref}"


def _ipni_relations(rec: dict) -> list:
    """Basionym / replaced / nomenclatural synonyms as Synonyms-group entries."""
    out, seen = [], set()
    for key, label in _IPNI_RELATIONS:
        for e in (rec.get(key) or []):
            if not isinstance(e, dict) or not e.get("name"):
                continue
            auth = (e.get("authors") or "").strip()
            ident = (e["name"].lower(), auth.lower())
            if ident in seen:
                continue
            seen.add(ident)
            out.append({"name": e["name"], "authorship": auth,
                        "rank": _ipni_rank(e.get("rank")), "status": label})
    return out


def _ipni_children(rec: dict) -> list:
    """Every name IPNI lists directly below this one, all pages, no cap:
    species of a genus, infraspecific names of a species, genera of a family."""
    rank = (rec.get("rank") or "").lower()
    name = rec["name"]
    if rank == "gen.":
        hits = _ipni_search_all(f"genus:{name}", "f_specific")
        keep = lambda r: r["name"].startswith(name + " ")
    elif rank == "spec.":
        hits = _ipni_search_all(name, "f_infraspecific")
        keep = lambda r: r["name"].startswith(name + " ")
    elif rank == "fam.":
        hits = _ipni_search_all(f"family:{name}", "f_generic")
        keep = lambda r: ((r.get("rank") or "").lower() == "gen."
                          and (r.get("family") or "").lower() == name.lower())
    else:
        return []
    out, seen = [], set()
    for r in hits:
        if not keep(r) or r.get("topCopy") is False:
            continue
        auth = (r.get("authors") or "").strip()
        ident = (r["name"].lower(), auth.lower())
        if ident in seen:
            continue
        seen.add(ident)
        out.append({"name": r["name"], "authorship": auth,
                    "rank": _ipni_rank(r.get("rank"))})
    return out


def _ipni_parent(rec: dict) -> str:
    for p in (rec.get("parent") or []):
        if isinstance(p, dict) and p.get("name"):
            return f"{p['name']} {(p.get('authors') or '').strip()}".strip()
    if (rec.get("rank") or "").lower() == "gen.":
        return rec.get("family") or ""
    return ""


def fetch_ipni(taxon_name: str, fields: set) -> dict:
    """Return {dwc_term: value} from IPNI (plant names)."""
    rec = _ipni_lookup(taxon_name)
    if not rec:
        return {}
    result: dict[str, str] = {}
    lsid = _ipni_lsid(rec)

    _add(result, "scientificName",          rec.get("name"),                    fields)
    _add(result, "scientificNameAuthorship", rec.get("authors"),                fields)
    _add(result, "taxonRank",               _ipni_rank(rec.get("rank")).lower(), fields)
    _add(result, "family",                  rec.get("family"),                  fields)
    _add(result, "genus",                   rec.get("genus"),                   fields)
    _add(result, "namePublishedIn",         _ipni_reference(rec),               fields)
    _add(result, "namePublishedInYear",     rec.get("publicationYear"),         fields)
    _add(result, "taxonID",                 lsid,                               fields)
    _add(result, "scientificNameID",        lsid,                               fields)
    _add(result, "nomenclaturalCode",       "ICN",                              fields)

    basionym = next((e for e in _ipni_relations(rec) if e["status"] == "basionym"), None)
    if basionym:
        _add(result, "originalNameUsage",
             f"{basionym['name']} {basionym['authorship']}".strip(), fields)
    return result


def fetch_ipni_profile(taxon_name: str) -> dict:
    """Return structured IPNI profile dict for _info_worker display.

    Keys: ipni_lsid, wfo_id, authorship, rank, family, genus, parent,
          reference, citation, namePublishedInYear, year, bhl_url,
          taxonRemarks, synonyms (list), children (list)
    """
    rec = _ipni_lookup(taxon_name)
    if not rec:
        return {}
    year = rec.get("publicationYear")
    linked = rec.get("linkedPublication") if isinstance(rec.get("linkedPublication"), dict) else {}
    return {
        "ipni_lsid":           _ipni_lsid(rec),
        "wfo_id":              rec.get("wfoId") or "",
        "authorship":          (rec.get("authors") or "").strip(),
        "rank":                _ipni_rank(rec.get("rank")),
        "family":              rec.get("family") or "",
        "genus":               rec.get("genus") or "",
        "parent":              _ipni_parent(rec),
        "reference":           _ipni_reference(rec),
        "citation":            _ipni_citation(rec),
        "namePublishedInYear": str(year) if year else "",
        "year":                int(year) if isinstance(year, int) else None,
        "bhl_url":             rec.get("bhlLink") or linked.get("bhlPageLink") or "",
        "taxonRemarks":        (rec.get("originalRemarks") or "").strip(),
        "synonyms":            _ipni_relations(rec),
        "children":            _ipni_children(rec),
    }


# ============================================================
# PROVIDER REGISTRY
# ============================================================

PROVIDERS: list[str] = ["GBIF", "CoL", "ITIS", "WoRMS", "WSC", "BacDive", "IPNI"]

FETCH_FN: dict[str, callable] = {
    "GBIF":  fetch_gbif,
    "CoL":   fetch_col,
    "ITIS":  fetch_itis,
    "WoRMS": fetch_worms,
    "WSC":     fetch_wsc,
    "BacDive": fetch_bacdive,
    "IPNI":    fetch_ipni,
}

# Providers that require an API key: maps provider name → settings key name.
# run_registry() skips a provider when its key is absent.
REQUIRES_KEY: dict[str, str] = {
    "WSC": "wsc_api_key",
}

# Per-provider adapter metadata for the 3-stage registry pipeline (run_registry).
# pass2_id_type: canonical id-type name this provider needs for Pass 2.
# All canonical names follow GBIF's identifier vocabulary.
ADAPTER_META: dict[str, dict] = {
    "GBIF":  {"pass2_id_type": "gbif_usage_key"},
    "CoL":   {"pass2_id_type": "col_id"},
    "ITIS":  {"pass2_id_type": "itis_tsn"},
    "WoRMS": {"pass2_id_type": "worms_aphia_id"},
    "ZooBank": {"pass2_id_type": "zoobank_lsid"},
    "WSC":     {"pass2_id_type": "wsc_taxon_id"},
    "BacDive": {"pass2_id_type": "bacdive_id"},
    "IPNI":    {"pass2_id_type": "ipni_lsid"},
}


# ============================================================
# DESCRIPTION RETRIEVAL  (Wikipedia → GBIF treatments)
# ============================================================

_WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_WIKI_SEARCH  = "https://en.wikipedia.org/w/api.php"


def fetch_description(taxon_name: str) -> dict:
    """
    Fetch description text for taxon_name from all available sources.
    Always queries every source; results are collected into a list so the
    caller can display them all.
    Returns {"descriptions": [{"source": str, "text": str, "url": str}, ...]}
    The list may be empty if nothing was found; never raises.
    """
    descriptions = []

    result = _fetch_description_wikipedia(taxon_name)
    if result and "text" in result:
        descriptions.append(result)

    result = _fetch_description_gbif(taxon_name)
    if result and "text" in result:
        descriptions.append(result)

    return {"descriptions": descriptions}


def _fetch_description_wikipedia(taxon_name: str) -> dict:
    """Fetch description summary from Wikipedia REST API."""
    try:
        title = taxon_name.replace(" ", "_")
        url = _WIKI_SUMMARY.format(title=title)
        r = _get_with_retry(url, headers=_headers(), timeout=10)
        data = r.json()
        text = data.get("extract", "").strip()
        if not text:
            return {}
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
        return {"source": "Wikipedia", "text": text, "url": page_url}
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return {}  # No Wikipedia article — try next source
        log.warning("[Wikipedia description] %s → %s", taxon_name, exc)
    except Exception as exc:
        log.warning("[Wikipedia description] %s → %s", taxon_name, exc)
    return {}


def fetch_wikipedia_report(taxon_name: str, max_sections: int = 0) -> dict:
    """Fetch a structured Wikipedia report for a taxon.

    Uses /page/summary for the lead extract + thumbnail, then the
    MediaWiki Action API (action=parse&prop=text) for full page HTML,
    which is split at <h2> boundaries into named sections.
    HTML is converted to formatted plain text via _html_to_text().

    Returns {
      "found":      bool,
      "title":      str,
      "url":        str,
      "thumbnail":  str | None,
      "extract":    str,
      "sections":   [{"heading": str, "text": str}, ...],
    }
    max_sections=0 means return all sections.  Never raises.
    """
    _SKIP_SECTIONS = frozenset((
        "references", "footnotes", "notes", "external links",
        "further reading", "see also", "bibliography",
    ))

    result = {"found": False, "title": taxon_name, "url": "",
              "thumbnail": None, "extract": "", "sections": []}

    def _wiki_get(url, params=None):
        """GET a Wikipedia endpoint; return parsed JSON or None on any error."""
        try:
            r = _get_with_retry(url, params=params, headers=_headers(), timeout=15)
            return r.json()
        except Exception:
            return None

    title = taxon_name.replace(" ", "_")

    # 1. Summary: extract + thumbnail (REST API v1 — still active)
    summary = _wiki_get(_WIKI_SUMMARY.format(title=title))
    if not summary or not summary.get("extract"):
        # Fall back to MediaWiki search to resolve the correct title
        search_data = _wiki_get(_WIKI_SEARCH, {
            "action": "query", "list": "search",
            "srsearch": taxon_name, "srlimit": 1, "format": "json",
        })
        hits = (search_data or {}).get("query", {}).get("search", [])
        if not hits:
            return result
        title   = hits[0]["title"].replace(" ", "_")
        summary = _wiki_get(_WIKI_SUMMARY.format(title=title))

    if not summary or not summary.get("extract"):
        return result

    extract = summary.get("extract", "").strip()
    result["found"]     = True
    result["title"]     = summary.get("title", taxon_name)
    result["url"]       = (summary.get("content_urls", {})
                           .get("desktop", {}).get("page", ""))
    result["thumbnail"] = (summary.get("thumbnail") or {}).get("source")
    result["extract"]   = _html_to_text(extract) if "<" in extract else extract

    # 2. Full page HTML via MediaWiki Action API (replaces decommissioned
    #    mobile-sections endpoint).  action=parse returns the complete rendered
    #    HTML; we split it at <h2> tags to recover individual sections.
    page_data = _wiki_get(_WIKI_SEARCH, {
        "action":      "parse",
        "page":        title.replace("_", " "),
        "prop":        "text",
        "format":      "json",
        "redirects":   "true",
        "disableeditsection": "true",
    })
    html_body = ((page_data or {}).get("parse") or {}).get("text", {}).get("*", "")

    if html_body:
        from html.parser import HTMLParser as _HP

        class _SectionSplitter(_HP):
            """Split page HTML into (heading, html_chunk) pairs at <h2> boundaries."""
            def __init__(self):
                super().__init__()
                self.sections: list[tuple[str, str]] = []
                self._cur_heading  = ""
                self._cur_buf:  list[str] = []
                self._in_h2        = False
                self._h2_buf:   list[str] = []
                self._depth        = 0   # tracks open tags inside a section

            def handle_starttag(self, tag, attrs):
                t = tag.lower()
                if t == "h2":
                    self._flush()
                    self._in_h2  = True
                    self._h2_buf = []
                    return
                if not self._in_h2:
                    attr_str = "".join(
                        f' {k}="{v}"' for k, v in attrs if v is not None
                    )
                    self._cur_buf.append(f"<{tag}{attr_str}>")

            def handle_endtag(self, tag):
                t = tag.lower()
                if t == "h2":
                    self._in_h2 = False
                    self._cur_heading = re.sub(r"\[.*?\]", "",
                                               "".join(self._h2_buf)).strip()
                    return
                if not self._in_h2:
                    self._cur_buf.append(f"</{tag}>")

            def handle_data(self, data):
                if self._in_h2:
                    self._h2_buf.append(data)
                else:
                    self._cur_buf.append(data)

            def _flush(self):
                if self._cur_heading and self._cur_buf:
                    self.sections.append(
                        (self._cur_heading, "".join(self._cur_buf))
                    )
                self._cur_buf     = []
                self._cur_heading = ""

            def finish(self):
                self._flush()

        splitter = _SectionSplitter()
        splitter.feed(html_body)
        splitter.finish()

        for heading, html_chunk in splitter.sections:
            if heading.lower() in _SKIP_SECTIONS:
                continue
            text = _html_to_text(html_chunk).strip()
            if text:
                result["sections"].append({"heading": heading, "text": text})
            if max_sections and len(result["sections"]) >= max_sections:
                break

    return result


def _fetch_description_gbif(taxon_name: str) -> dict:
    """Fetch a taxonomic treatment from GBIF's species descriptions endpoint.

    GBIF aggregates treatment text from literature (including Plazi) under
    /species/{key}/descriptions.  Results are HTML; we strip tags and pick
    the longest English entry that looks like a prose description rather than
    a nomenclatural header or identification key.
    """
    try:
        match = _gbif_match_strict(taxon_name)
        if not match:
            return {}
        usage_key = match.get("usageKey")
        if not usage_key:
            return {}

        data = _gbif_get(f"/species/{usage_key}/descriptions") or {}
        results = data.get("results", [])

        # Keep English entries only; fall back to language-unspecified ones
        english = [r for r in results if r.get("language", "eng") in ("eng", "en", "")]
        candidates = english or results

        best_text = ""
        best_source = ""
        for entry in candidates:
            raw = entry.get("description", "").strip()
            if not raw:
                continue
            # Strip HTML tags and normalise whitespace
            plain = re.sub(r"<[^>]+>", " ", raw)
            plain = re.sub(r"\s+", " ", plain).strip()
            # Skip entries that are just a nomenclatural header (< 80 chars)
            # or start with a key couplet ("1." or "1\.")
            if len(plain) < 80 or re.match(r"^\s*1[\.\s]", plain):
                continue
            if len(plain) > len(best_text):
                best_text   = plain
                best_source = entry.get("source", "")

        if not best_text:
            return {}

        return {
            "source": f"GBIF treatments ({best_source})" if best_source else "GBIF treatments",
            "text":   best_text,
            "url":    f"https://www.gbif.org/species/{usage_key}",
        }
    except Exception as exc:
        log.warning("[GBIF description] %s → %s", taxon_name, exc)
    return {}


# ============================================================
# PUBLICATION RETRIEVAL
# GBIF literature/search by taxonKey + CrossRef broad query
# Mirrors get_gbif_publications() and get_crossref_records() in sandbox
# ============================================================

_CROSSREF_WORKS = "https://api.crossref.org/works"

# GBIF literature search returns at most 200 results per page (API hard limit).
_GBIF_LIT_PAGE_SIZE = 200


def fetch_publications(taxon_name: str, usage_key: str = None,
                       gbif_limit: int = 10, crossref_limit: int = 20) -> dict:
    """
    Fetch publication references for taxon_name from GBIF literature index and CrossRef.
    usage_key: cached GBIF backbone key (skips name resolution when provided).
    Returns {"publications": [{"title", "authors", "year", "url", "source"}, ...]}
    Never raises.
    """
    key = usage_key
    if not key:
        try:
            match = _gbif_match_strict(taxon_name)
            if match:
                key = str(match.get("usageKey") or "") or None
        except Exception:
            pass

    publications = []
    if key:
        publications.extend(_fetch_publications_gbif_by_key(key, max_results=gbif_limit))
    publications.extend(_fetch_publications_crossref(taxon_name, max_results=crossref_limit))
    return {"publications": publications}


def _fetch_publications_gbif_by_key(usage_key: str, max_results: int = 10) -> list:
    """Fetch from GBIF literature index with offset-based pagination.

    'gbifTaxonKey'       — papers where this taxon is the focus.
    'gbifHigherTaxonKey' — papers where any child taxon is the focus (catches
                           species-level papers when searching at genus level).
    Plain 'taxonKey' is an occurrence/species parameter — not valid here.

    GBIF literature search returns at most _GBIF_LIT_PAGE_SIZE (200) results per
    request.  When max_results > 200 we loop with increasing offsets until we
    reach max_results or exhaust the index.
    """
    def _fmt_gbif(a):
        last  = a.get("lastName", "")
        first = a.get("firstName", "")
        return f"{last}, {first[0]}." if last and first else last or first

    try:
        seen_titles: set = set()
        pubs: list = []

        for param in ("gbifTaxonKey", "gbifHigherTaxonKey"):
            if len(pubs) >= max_results:
                break
            offset = 0
            while len(pubs) < max_results:
                page_size = min(_GBIF_LIT_PAGE_SIZE, max_results - len(pubs))
                data = _gbif_get("/literature/search",
                                 {param: usage_key, "limit": page_size, "offset": offset})
                results = (data or {}).get("results", [])
                if not results:
                    break
                for p in results:
                    title = (p.get("title") or "Untitled").strip()
                    if title in seen_titles:
                        continue
                    seen_titles.add(title)
                    year        = str(p.get("year", "")) if p.get("year") else ""
                    doi         = (p.get("identifiers") or {}).get("doi", "")
                    url         = (f"https://doi.org/{doi}" if doi
                                   else f"https://www.gbif.org/literature/search?"
                                        f"gbifTaxonKey={usage_key}")
                    authors_raw = p.get("authors") or []
                    authors     = ("; ".join(_fmt_gbif(a) for a in authors_raw[:3])
                                   + (" et al." if len(authors_raw) > 3 else "")
                                   if authors_raw else "")
                    pubs.append({
                        "title":   title,
                        "authors": authors,
                        "year":    year,
                        "url":     url,
                        "source":  "GBIF literature",
                    })
                    if len(pubs) >= max_results:
                        break
                end_of_records = (data or {}).get("endOfRecords", True)
                if end_of_records or len(results) < page_size:
                    break
                offset += page_size

        return pubs[:max_results]
    except Exception as exc:
        log.warning("[GBIF literature by key] %s → %s", usage_key, exc)
        return []


def _fetch_publications_crossref(taxon_name: str, max_results: int = 20) -> list:
    """Fetch from CrossRef using broad query. Mirrors get_crossref_records() in sandbox."""
    try:
        r = _get_with_retry(
            _CROSSREF_WORKS,
            params={"query": f'"{taxon_name}"', "rows": max_results},
            headers=_headers(), timeout=15,
        )
        items = r.json().get("message", {}).get("items", [])
        pubs = []
        for item in items:
            title = (item.get("title") or [""])[0].strip()
            if not title:
                continue
            doi     = item.get("DOI", "")
            journal = (item.get("container-title") or [""])[0].strip()
            year_parts = (item.get("published", {}).get("date-parts") or [[""]])[0]
            year = str(year_parts[0]) if year_parts and year_parts[0] else ""
            authors_raw = item.get("author") or []
            if authors_raw:
                def _fmt(a):
                    fam   = a.get("family", "")
                    given = a.get("given", "")
                    if fam and given:
                        return f"{fam}, {given[0]}."
                    return fam or given
                authors = "; ".join(_fmt(a) for a in authors_raw[:3])
                if len(authors_raw) > 3:
                    authors += " et al."
            else:
                authors = ""
            url = f"https://doi.org/{doi}" if doi else item.get("URL", "")
            pubs.append({
                "title":   title,
                "authors": authors,
                "year":    year,
                "url":     url,
                "source":  f"CrossRef ({journal})" if journal else "CrossRef",
            })
        return pubs
    except Exception as exc:
        log.warning("[CrossRef publications] %s → %s", taxon_name, exc)
    return []


def fetch_gbif_publications(usage_key: str, max_results: int = 10) -> list:
    """Public API: paginated GBIF literature retrieval by backbone usageKey."""
    return _fetch_publications_gbif_by_key(usage_key, max_results=max_results)


def fetch_inat_image_urls(taxon_name: str, max_results: int = 10) -> list:
    """Return iNaturalist taxon photo URLs as [str, ...] for report display."""
    images = _fetch_images_inaturalist(taxon_name, max_results)
    return [img["url"] for img in images if img.get("url")]


def fetch_crossref_publications(taxon_name: str, max_results: int = 20) -> list:
    """Public API: CrossRef publication retrieval with configurable result limit."""
    return _fetch_publications_crossref(taxon_name, max_results=max_results)


# ============================================================
# IMAGE RETRIEVAL  (GBIF occurrence by taxonKey, with iNaturalist fallback)
# ============================================================

_INAT_TAXA = "https://api.inaturalist.org/v1/taxa"


def fetch_images(taxon_name: str, max_results: int = 10,
                 usage_key: str = None) -> list:
    """
    Fetch image records for taxon_name.
    Primary: GBIF occurrence/search by taxonKey (mirrors sandbox get_gbif_images).
    Fallback: iNaturalist taxa API.
    Returns [{"title": str, "url": str, "thumb_url": str,
              "source": str, "attribution": str, "link": str}, ...]
    Never raises; returns [] on complete failure.
    """
    key = usage_key
    if not key:
        try:
            match = _gbif_match_strict(taxon_name)
            if match:
                key = str(match.get("usageKey") or "") or None
        except Exception:
            pass

    if key:
        images = _fetch_images_gbif_by_key(key, max_results)
        if images:
            return images

    return _fetch_images_inaturalist(taxon_name, max_results)


def _fetch_images_gbif_by_key(usage_key: str, max_results: int) -> list:
    """Fetch occurrence images from GBIF by taxonKey. Mirrors get_gbif_images() in sandbox."""
    try:
        images = []
        offset = 0
        while len(images) < max_results:
            data = _gbif_get("/occurrence/search",
                             {"taxonKey": usage_key, "mediaType": "StillImage",
                              "limit": 100, "offset": offset})
            if not data:
                break
            results = data.get("results", [])
            if not results:
                break
            for rec in results:
                for m in rec.get("media", []):
                    if m.get("type") != "StillImage":
                        continue
                    url = m.get("identifier", "")
                    if not url:
                        continue
                    images.append({
                        "title":       rec.get("species") or rec.get("canonicalName", ""),
                        "url":         url,
                        "thumb_url":   url,
                        "source":      "GBIF",
                        "attribution": m.get("rightsHolder") or m.get("license", ""),
                        "link":        f"https://www.gbif.org/occurrence/{rec.get('key', '')}",
                    })
                    if len(images) >= max_results:
                        break
                if len(images) >= max_results:
                    break
            if data.get("endOfRecords") or len(results) < 100:
                break
            offset += 100
        seen: set = set()
        deduped = []
        for img in images:
            if img["url"] not in seen:
                seen.add(img["url"])
                deduped.append(img)
        return deduped[:max_results]
    except Exception as exc:
        log.warning("[GBIF images by key] %s → %s", usage_key, exc)
        return []


def _fetch_images_inaturalist(taxon_name: str, max_results: int) -> list:
    """Fetch taxon photos from iNaturalist taxa API (fallback)."""
    try:
        r = _get_with_retry(
            _INAT_TAXA,
            params={"q": taxon_name, "per_page": 1, "rank": "genus,species,family,order"},
            headers=_headers(), timeout=10,
        )
        if not r:
            return []
        results = r.json().get("results", [])
        if not results:
            return []
        taxon = results[0]
        taxon_id = taxon.get("id")
        display_name = taxon.get("preferred_common_name") or taxon.get("name", taxon_name)

        images = []
        dp = taxon.get("default_photo")
        if dp:
            images.append({
                "title":       display_name,
                "url":         dp.get("medium_url", dp.get("url", "")),
                "thumb_url":   dp.get("square_url", dp.get("url", "")),
                "source":      "iNaturalist",
                "attribution": dp.get("attribution", ""),
                "link":        f"https://www.inaturalist.org/taxa/{taxon_id}" if taxon_id else "",
            })
        for tp in taxon.get("taxon_photos", [])[:max_results - 1]:
            photo = tp.get("photo", {})
            url = photo.get("medium_url") or photo.get("url", "")
            if url and url not in {i["url"] for i in images}:
                images.append({
                    "title":       display_name,
                    "url":         url,
                    "thumb_url":   photo.get("square_url", url),
                    "source":      "iNaturalist",
                    "attribution": photo.get("attribution", ""),
                    "link":        f"https://www.inaturalist.org/taxa/{taxon_id}" if taxon_id else "",
                })
        return images[:max_results]
    except Exception as exc:
        log.warning("[iNaturalist images] %s → %s", taxon_name, exc)
        return []


# ============================================================
# IDENTIFIER RESOLUTION  (Pass-1 aggregator)
# Mirrors resolve_gbif_backbone() in query_databases_sandbox.py
# ============================================================

def fetch_identifiers(taxon_name: str, rank: str = None) -> dict:
    """
    Resolve external identifiers for taxon_name.
    Pass 1: GBIF backbone → usageKey, LSID, TSN, TaxID.
    Fallback: if GBIF doesn't carry the TSN, query ITIS directly by name.
    Returns {
      "usageKey":       str | None,
      "scientificName": str,
      "lsid":           str | None,
      "tsn":            str | None,
      "taxid":          str | None,
    }
    Never raises.
    """
    result = {
        "usageKey":       None,
        "scientificName": taxon_name,
        "lsid":           None,
        "tsn":            None,
        "taxid":          None,
    }
    try:
        match = _gbif_match_strict(taxon_name, rank)
        if not match:
            return result

        usage_key = match.get("usageKey")
        if not usage_key:
            return result

        result["usageKey"]       = str(usage_key)
        result["scientificName"] = match.get("scientificName") or taxon_name

        id_data = _gbif_get(f"/species/{usage_key}/identifier") or {}
        for item in id_data.get("results", []):
            id_type = item.get("type", "")
            val     = item.get("identifier", "")
            if (id_type == "ITIS_TSN" or "itis.gov" in val) and not result["tsn"]:
                result["tsn"]   = val.split("/")[-1].split(":")[-1]
            elif (id_type == "NCBI_TAXONOMY" or "ncbi" in val.lower()) and not result["taxid"]:
                result["taxid"] = val.split("/")[-1].split(":")[-1]
            elif "lsid" in val.lower() and not result["lsid"]:
                result["lsid"]  = val
    except Exception as exc:
        log.warning("[fetch_identifiers] %s → %s", taxon_name, exc)

    # ITIS TSN fallback: GBIF's identifier endpoint doesn't carry TSN for many
    # taxa. Mirror the sandbox by querying ITIS directly when it's still missing.
    if not result["tsn"]:
        try:
            search = _itis_get("searchByScientificName", {"srchKey": taxon_name})
            raw    = _as_dict(search).get("scientificNames") or []
            names  = [n for n in (raw if isinstance(raw, list) else [])
                      if isinstance(n, dict)]
            name_lower = taxon_name.lower()
            match_rec  = next(
                (n for n in names
                 if (n.get("combinedName") or "").lower() == name_lower),
                names[0] if names else None,
            )
            if match_rec:
                tsn = str(match_rec.get("tsn") or "").strip()
                if tsn:
                    result["tsn"] = tsn
        except Exception as exc:
            log.warning("[fetch_identifiers ITIS fallback] %s → %s", taxon_name, exc)

    return result


# ============================================================
# NCBI MOLECULAR RECORDS
# Mirrors get_ncbi_records() in query_databases_sandbox.py
# ============================================================

_NCBI_ESEARCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_NCBI_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_NCBI_ACC_LIMIT = 10


def _ncbi_get(url: str, params: dict) -> dict:
    try:
        r = _get_with_retry(url, params=params, headers=_headers(), timeout=15)
        return r.json()
    except Exception as exc:
        log.warning("[NCBI] %s params=%s → %s", url, params, exc)
        return {}


def fetch_ncbi(taxon_name: str, taxid: str = None) -> dict:
    """
    Fetch NCBI molecular summary for taxon_name.
    Returns {
      "taxid":            str | None,
      "nucleotide_count": str,
      "accessions":       [str, ...],   # sample of up to _NCBI_ACC_LIMIT
    }
    Never raises.
    """
    if not taxid:
        res   = _ncbi_get(_NCBI_ESEARCH,
                          {"db": "taxonomy", "term": taxon_name, "retmode": "json"})
        ids   = res.get("esearchresult", {}).get("idlist", [])
        taxid = ids[0] if ids else None
    if not taxid:
        return {"taxid": None, "nucleotide_count": "0", "accessions": []}

    seq_res  = _ncbi_get(_NCBI_ESEARCH,
                         {"db": "nucleotide",
                          "term": f"txid{taxid}[Organism]",
                          "retmode": "json",
                          "retmax": _NCBI_ACC_LIMIT})
    eresult  = seq_res.get("esearchresult", {})
    count    = eresult.get("count", "0")
    uid_list = eresult.get("idlist", [])

    accessions = []
    if uid_list:
        summary = _ncbi_get(_NCBI_ESUMMARY,
                            {"db": "nucleotide",
                             "id": ",".join(uid_list),
                             "retmode": "json"})
        res_map = summary.get("result", {})
        for uid in uid_list:
            doc = res_map.get(uid, {})
            acc = doc.get("accessionversion") or doc.get("caption")
            if acc:
                accessions.append(acc)

    return {"taxid": taxid, "nucleotide_count": count, "accessions": accessions}


# ============================================================
# ZOOBANK NOMENCLATURAL ACTS
# Mirrors get_zoobank_records() in query_databases_sandbox.py
# ============================================================

_ZOOBANK = "https://zoobank.org"


def _zoobank_get(path: str, params: dict = None):
    """GET a ZooBank endpoint; returns parsed JSON (list or dict) or None."""
    try:
        r = _get_with_retry(f"{_ZOOBANK}{path}", params=params,
                            headers=_headers(), timeout=15)
        return r.json()
    except Exception as exc:
        log.warning("[ZooBank] %s → %s", path, exc)
        return None


def _zoobank_first(data) -> dict:
    """Return the first element if data is a non-empty list, or data if dict."""
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else {}
    return data if isinstance(data, dict) else {}


def fetch_synonyms(taxon_name: str, usage_key: str = None) -> dict:
    """
    Fetch synonymy from GBIF backbone and Catalogue of Life.
    Returns {
      "gbif": [{"scientificName": str, "taxonomicStatus": str,
                "originalNameUsage": str}, ...],
      "col":  {"status": str, "accepted": str,
               "synonyms": [{"name": str, "status": str}, ...]},
    }
    Never raises.
    """
    result: dict = {"gbif": [], "col": {"status": "", "accepted": "", "synonyms": []}}

    # ── GBIF backbone synonyms ────────────────────────────────────────
    if not usage_key:
        match = _gbif_match_strict(taxon_name)
        if match:
            usage_key = match.get("usageKey")
    if usage_key:
        data = _gbif_get(f"/species/{usage_key}/synonyms", {"limit": 100})
        for s in (data or {}).get("results", []):
            result["gbif"].append({
                "scientificName":    s.get("scientificName", ""),
                "taxonomicStatus":   s.get("taxonomicStatus", ""),
                "originalNameUsage": s.get("basionym", ""),
            })

    # ── Catalogue of Life synonyms ────────────────────────────────────
    search = _col_get(f"/dataset/{_COL_KEY}/nameusage/search",
                      {"q": taxon_name, "limit": 10})
    items = (search or {}).get("result", [])
    if items:
        name_lower = taxon_name.lower()
        match_item = next(
            (r for r in items
             if name_lower in (r.get("usage", {}).get("label") or "").lower()),
            items[0]
        )
        usage    = match_item.get("usage", {})
        usage_id = usage.get("id", "")
        status   = (usage.get("status") or "unknown").lower()
        label    = usage.get("label") or taxon_name

        result["col"]["status"]   = status
        result["col"]["accepted"] = label

        if status in ("synonym", "ambiguous synonym", "misapplied"):
            accepted_info = usage.get("accepted", {})
            result["col"]["accepted"] = (
                accepted_info.get("label") or
                (accepted_info.get("name") or {}).get("scientificName") or ""
            )
        elif usage_id:
            syn_data = _col_get(f"/dataset/{_COL_KEY}/taxon/{usage_id}/synonyms")
            if isinstance(syn_data, list):
                syn_list = syn_data
            else:
                d = syn_data or {}
                syn_list = (d.get("heterotypic") or d.get("result") or
                            d.get("synonyms") or [])
                syn_list = syn_list + (d.get("homotypic") or [])
            for s in (syn_list or [])[:30]:
                if not isinstance(s, dict):
                    continue
                s_usage  = s.get("usage", s)
                s_label  = (s_usage.get("label") or
                            (s_usage.get("name") or {}).get("scientificName") or "")
                s_status = s_usage.get("status") or "synonym"
                if s_label:
                    result["col"]["synonyms"].append(
                        {"name": s_label, "status": s_status})

    return result


def fetch_zoobank(taxon_name: str, max_acts: int = 10) -> dict:
    """
    Fetch ZooBank nomenclatural acts for taxon_name.
    Returns {
      "lsid": str | None,   # LSID of the first matching act
      "acts": [
        {
          "namestring": str,
          "rank":       str,
          "author":     str,   # ZooBank label field = "Author, Year"
          "lsid":       str,
          "citation":   str,   # full reference citation if retrievable
        }, ...
      ]
    }
    Never raises.
    """
    data = _zoobank_get("/NomenclaturalActs.json", {"search_term": taxon_name})
    if not isinstance(data, list) or not data:
        return {"lsid": None, "acts": []}

    top_lsid = None
    acts     = []
    for act in data[:max_acts]:
        act_lsid   = act.get("lsid", "")
        namestring = act.get("namestring") or act.get("label", taxon_name)
        year       = act.get("year", "")
        citation   = act.get("citationdetails", "")
        rank       = ""
        author     = ""

        # Enrich via per-act detail endpoint
        guid = act_lsid.split(":")[-1] if ":" in act_lsid else ""
        if guid:
            detail  = _zoobank_first(
                _zoobank_get(f"/NomenclaturalActs.json/{guid}"))
            year    = detail.get("year") or year
            rank    = detail.get("rankgroup", "")
            author  = detail.get("label", "")
            ref_uuid = detail.get("referenceuuid") or detail.get("PublicationUUID") or ""
            if ref_uuid and not citation:
                ref      = _zoobank_first(_zoobank_get(f"/References.json/{ref_uuid}"))
                citation = ref.get("citation") or ref.get("label") or ""

        if act_lsid and not top_lsid:
            top_lsid = act_lsid

        acts.append({
            "namestring": namestring,
            "rank":       rank,
            "author":     author,
            "lsid":       act_lsid,
            "citation":   citation,
        })

    return {"lsid": top_lsid, "acts": acts}


# ============================================================
# INFO-REPORT HELPERS
# One public function per external source, each returning the
# exact shape that _info_worker in ui_app.py expects.
# These replace all query_databases_sandbox.py calls in CARL.
# ============================================================

_GBIF_BACKBONE = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"
_PLAZI_API     = "https://api.plazi.org/v1"
_PLAZI_XML     = "https://tb.plazi.org/GgServer/xml"
_BHL_API       = "https://www.biodiversitylibrary.org/api3"


def resolve_gbif_backbone(name: str, rank: str) -> dict | None:
    """Resolve taxon to GBIF backbone + external IDs.
    Returns {"usageKey", "scientificName", "rank", "tsn", "taxid", "lsid"} or None.
    Mirrors resolve_gbif_backbone() in query_databases_sandbox.py.
    """
    try:
        match = _gbif_match_strict(name, rank)
        if match and match.get("usageKey"):
            usage_key = match["usageKey"]
            sci_name  = match.get("scientificName") or name
            gbif_rank = match.get("rank", rank)
        else:
            search = _gbif_get("/species/search",
                               {"q": name, "rank": rank.upper(),
                                "datasetKey": _GBIF_BACKBONE, "limit": 5})
            results = [r for r in (search or {}).get("results", [])
                       if r.get("canonicalName", "").lower() == name.lower()
                       and r.get("rank") == rank.upper()]
            if not results:
                return None
            usage_key = results[0].get("key")
            sci_name  = results[0].get("scientificName") or name
            gbif_rank = results[0].get("rank", rank)
        if not usage_key:
            return None

        tsn = taxid = lsid = None
        id_data = _gbif_get(f"/species/{usage_key}/identifier") or {}
        for item in id_data.get("results", []):
            id_type = item.get("type", "")
            val     = item.get("identifier", "")
            if (id_type == "ITIS_TSN" or "itis.gov" in val) and not tsn:
                tsn   = val.split("/")[-1].split(":")[-1]
            elif (id_type == "NCBI_TAXONOMY" or "ncbi" in val.lower()) and not taxid:
                taxid = val.split("/")[-1].split(":")[-1]
            elif "lsid" in val.lower() and not lsid:
                lsid  = val
        return {"usageKey": usage_key, "scientificName": sci_name,
                "rank": gbif_rank, "tsn": tsn, "taxid": taxid, "lsid": lsid}
    except Exception as exc:
        log.warning("[resolve_gbif_backbone] %s → %s", name, exc)
        return None


def fetch_gbif_synonyms(usage_key: str) -> list:
    """Return GBIF backbone synonyms as [{"scientificName", "taxonomicStatus", "originalNameUsage"}, ...]."""
    try:
        data = _gbif_get(f"/species/{usage_key}/synonyms", {"limit": 100})
        return [
            {"scientificName":    s.get("scientificName", ""),
             "taxonomicStatus":   s.get("taxonomicStatus", ""),
             "originalNameUsage": s.get("basionym", "")}
            for s in (data or {}).get("results", [])
        ]
    except Exception as exc:
        log.warning("[fetch_gbif_synonyms] %s → %s", usage_key, exc)
        return []


def _html_to_text(html_str: str) -> str:
    """Convert HTML to readable plain text, preserving structure.

    Block elements become paragraph breaks; lists become • bullets;
    bold/strong text is uppercased; anchors show URL in parentheses.
    """
    from html.parser import HTMLParser
    import html as _html

    class _Converter(HTMLParser):
        BLOCK  = {"p", "div", "section", "article", "blockquote",
                  "h1", "h2", "h3", "h4", "h5", "h6", "tr"}
        INLINE_BREAK = {"br"}
        BOLD   = {"b", "strong"}
        ITALIC = {"i", "em"}
        LIST   = {"ul", "ol"}
        ITEM   = {"li"}

        def __init__(self):
            super().__init__()
            self.parts: list[str] = []
            self._in_bold    = 0
            self._in_italic  = 0
            self._in_item    = False
            self._in_sup     = 0   # suppress citation superscripts
            self._pending_nl = 0   # pending newlines to collapse
            self._href       = ""

        def _flush_nl(self, n: int):
            self._pending_nl = max(self._pending_nl, n)

        def _emit(self, text: str):
            if not text:
                return
            if self._pending_nl:
                self.parts.append("\n" * self._pending_nl)
                self._pending_nl = 0
            self.parts.append(text)

        def handle_starttag(self, tag, attrs):
            tag = tag.lower()
            if tag in self.BLOCK:
                self._flush_nl(2)
            elif tag in self.INLINE_BREAK:
                self._flush_nl(1)
            elif tag in self.BOLD:
                self._in_bold += 1
            elif tag in self.ITALIC:
                self._in_italic += 1
                self._emit("_")
            elif tag in self.LIST:
                self._flush_nl(1)
            elif tag in self.ITEM:
                self._flush_nl(1)
                self._emit("• ")
                self._in_item = True
            elif tag == "a":
                self._href = dict(attrs).get("href", "")
            elif tag == "sup":
                self._in_sup += 1

        def handle_endtag(self, tag):
            tag = tag.lower()
            if tag in self.BLOCK or tag in self.LIST:
                self._flush_nl(2)
            elif tag in self.ITEM:
                self._in_item = False
            elif tag in self.BOLD:
                self._in_bold = max(0, self._in_bold - 1)
            elif tag in self.ITALIC:
                self._emit("_")
                self._in_italic = max(0, self._in_italic - 1)
            elif tag == "a" and self._href:
                # Only show URL for external links; skip /wiki/... and #... anchors
                if self._href.startswith("http"):
                    self._emit(f" ({self._href})")
                self._href = ""
            elif tag == "sup":
                self._in_sup = max(0, self._in_sup - 1)

        def handle_data(self, data):
            if self._in_sup:
                return  # suppress citation numbers ([1], [2] etc.)
            text = data  # entities already decoded by HTMLParser
            if self._in_bold:
                text = text.upper()
            self._emit(text)

        def result(self) -> str:
            raw = "".join(self.parts).strip()
            # Collapse runs of 3+ newlines to double-newline
            import re as _re
            return _re.sub(r"\n{3,}", "\n\n", raw)

    try:
        unescaped = _html.unescape(html_str)
        conv = _Converter()
        conv.feed(unescaped)
        return conv.result()
    except Exception:
        # Fallback: strip all tags with regex
        return re.sub(r"<[^>]+>", " ", html_str).strip()


def fetch_gbif_descriptions(usage_key: str) -> list:
    """Return GBIF species description texts as formatted plain-text strings."""
    try:
        data = _gbif_get(f"/species/{usage_key}/descriptions") or {}
        results = []
        for d in data.get("results", []):
            raw = d.get("description", "")
            if not raw:
                continue
            text = _html_to_text(raw) if "<" in raw else raw.strip()
            if text:
                results.append(text)
        return results
    except Exception as exc:
        log.warning("[fetch_gbif_descriptions] %s → %s", usage_key, exc)
        return []


def fetch_gbif_image_urls(usage_key: str, max_results: int = 10) -> list:
    """Return GBIF occurrence image URLs as [str, ...] for report display."""
    try:
        urls   = []
        offset = 0
        while len(urls) < max_results:
            data    = _gbif_get("/occurrence/search",
                                {"taxonKey": usage_key, "mediaType": "StillImage",
                                 "limit": 100, "offset": offset})
            results = (data or {}).get("results", [])
            if not results:
                break
            for rec in results:
                for m in rec.get("media", []):
                    if m.get("type") == "StillImage" and m.get("identifier"):
                        urls.append(m["identifier"])
                        if len(urls) >= max_results:
                            break
                if len(urls) >= max_results:
                    break
            if (data or {}).get("endOfRecords") or len(results) < 100:
                break
            offset += 100
        seen: set = set()
        return [u for u in urls if not (u in seen or seen.add(u))][:max_results]
    except Exception as exc:
        log.warning("[fetch_gbif_image_urls] %s → %s", usage_key, exc)
        return []


def fetch_gbif_specimens(usage_key: str, max_results: int = 20) -> list:
    """Return GBIF preserved-specimen records, type specimens first.
    Each entry: {"typeStatus", "institutionCode", "catalogNumber",
                 "collectionCode", "recordedBy", "locality", "country",
                 "eventDate", "occurrenceID", "preparations"}.
    """
    try:
        specimens = []
        offset    = 0
        while len(specimens) < max_results:
            data    = _gbif_get("/occurrence/search",
                                {"taxonKey": usage_key,
                                 "basisOfRecord": "PRESERVED_SPECIMEN",
                                 "limit": 100, "offset": offset})
            results = (data or {}).get("results", [])
            if not results:
                break
            for rec in results:
                if len(specimens) >= max_results:
                    break
                specimens.append({
                    "typeStatus":      rec.get("typeStatus", ""),
                    "institutionCode": rec.get("institutionCode", ""),
                    "catalogNumber":   rec.get("catalogNumber", ""),
                    "collectionCode":  rec.get("collectionCode", ""),
                    "recordedBy":      rec.get("recordedBy", ""),
                    "locality":        rec.get("locality", ""),
                    "country":         rec.get("country", ""),
                    "eventDate":       rec.get("eventDate", ""),
                    "occurrenceID":    rec.get("occurrenceID", ""),
                    "preparations":    rec.get("preparations", ""),
                })
            if (data or {}).get("endOfRecords") or len(results) < 100:
                break
            offset += 100
        _type_order = {"HOLOTYPE": 0, "LECTOTYPE": 1, "NEOTYPE": 2,
                       "SYNTYPE": 3, "PARATYPE": 4, "PARALECTOTYPE": 5}
        specimens.sort(key=lambda s: (_type_order.get((s["typeStatus"] or "").upper(), 99),
                                      (s["typeStatus"] or "").upper()))
        return specimens
    except Exception as exc:
        log.warning("[fetch_gbif_specimens] %s → %s", usage_key, exc)
        return []


def fetch_col_summary(name: str, syn_limit: int = 30) -> tuple:
    """Fetch CoL status and synonyms.
    Returns (accepted_name | None, synonyms_list, summary_str).
    Mirrors get_col_records() in query_databases_sandbox.py.
    """
    try:
        search  = _col_get(f"/dataset/{_COL_KEY}/nameusage/search",
                            {"q": name, "limit": 10})
        results = (search or {}).get("result", [])
        if not results:
            return None, [], "Not found in Catalogue of Life."

        name_lower = name.lower()
        match_rec  = next(
            (r for r in results
             if name_lower in (r.get("usage", {}).get("label") or "").lower()),
            results[0]
        )
        usage    = match_rec.get("usage", {})
        usage_id = usage.get("id", "")
        status   = usage.get("status", "unknown")
        label    = usage.get("label") or name

        if status.lower() in ("synonym", "ambiguous synonym", "misapplied"):
            accepted_info = usage.get("accepted", {})
            accepted_name = (accepted_info.get("label") or
                             (accepted_info.get("name") or {}).get("scientificName") or "")
            summary = f"Status: {status}\n  '{label}' is a synonym of: {accepted_name}"
            return accepted_name or None, [], summary

        synonyms = []
        if usage_id:
            syn_data = _col_get(f"/dataset/{_COL_KEY}/taxon/{usage_id}/synonyms")
            if isinstance(syn_data, list):
                syn_list = syn_data
            else:
                d = syn_data or {}
                syn_list = (d.get("heterotypic") or d.get("result") or
                            d.get("synonyms") or [])
                syn_list = syn_list + (d.get("homotypic") or [])
            for s in (syn_list or [])[:syn_limit]:
                if not isinstance(s, dict):
                    continue
                s_usage  = s.get("usage", s)
                s_label  = (s_usage.get("label") or
                            (s_usage.get("name") or {}).get("scientificName") or "")
                s_status = s_usage.get("status", "synonym")
                if s_label:
                    synonyms.append({"name": s_label, "status": s_status})

        summary = f"Status: {status}\nAccepted: {label}"
        if synonyms:
            summary += f"\nSynonyms ({len(synonyms)}):"
            for s in synonyms:
                summary += f"\n  {s['name']}  [{s['status']}]"
        else:
            summary += "\nSynonyms: None on record in CoL"
        return label, synonyms, summary
    except Exception as exc:
        log.warning("[fetch_col_summary] %s → %s", name, exc)
        return None, [], f"CoL lookup failed: {exc}"


def fetch_ncbi_summary(taxid: str | None, name: str,
                        acc_limit: int = 10) -> str:
    """Return a text summary of NCBI nucleotide records.
    Mirrors get_ncbi_records() in query_databases_sandbox.py.
    """
    try:
        if not taxid:
            res   = _ncbi_get(_NCBI_ESEARCH,
                               {"db": "taxonomy", "term": name, "retmode": "json"})
            ids   = res.get("esearchresult", {}).get("idlist", [])
            taxid = ids[0] if ids else None
        if not taxid:
            return "0 matches found (No mapped TaxID available)"

        seq_res  = _ncbi_get(_NCBI_ESEARCH,
                              {"db": "nucleotide",
                               "term": f"txid{taxid}[Organism]",
                               "retmode": "json", "retmax": acc_limit})
        eresult  = seq_res.get("esearchresult", {})
        count    = eresult.get("count", "0")
        uid_list = eresult.get("idlist", [])

        accessions = []
        if uid_list:
            summary = _ncbi_get(_NCBI_ESUMMARY,
                                 {"db": "nucleotide",
                                  "id": ",".join(uid_list), "retmode": "json"})
            res_map = summary.get("result", {})
            for uid in uid_list:
                doc = res_map.get(uid, {})
                acc = doc.get("accessionversion") or doc.get("caption")
                if acc:
                    accessions.append(acc)

        lines = [f"{count} nucleotide entries in GenBank [TaxID: {taxid}]"]
        if accessions:
            lines.append(f"Sample accessions: {', '.join(accessions)}")
        return "\n".join(lines)
    except Exception as exc:
        log.warning("[fetch_ncbi_summary] %s → %s", name, exc)
        return f"NCBI lookup failed: {exc}"


def fetch_itis_summary(tsn: str | None, name: str) -> tuple:
    """Return (resolved_tsn | None, summary_str).
    Mirrors get_itis_records() in query_databases_sandbox.py.
    """
    try:
        if not tsn:
            res     = _itis_get("searchByScientificName", {"srchKey": name})
            matches = _as_dict(res).get("scientificNames") or []
            for m in (matches if isinstance(matches, list) else []):
                if isinstance(m, dict) and m.get("tsn"):
                    tsn = str(m["tsn"])
                    break
        if not tsn:
            return None, "No corresponding matching record found in ITIS."

        syns     = _itis_get("getSynonymsFromTSN", {"tsn": tsn}, silent_404=True)
        syn_list = [s.get("sciName") for s in
                    (_as_dict(syns).get("synonyms") or [])
                    if isinstance(s, dict) and s.get("sciName")]
        summary  = (f"TSN: {tsn} | Synonyms: "
                    f"{', '.join(syn_list) if syn_list else 'None recorded'}")
        return tsn, summary
    except Exception as exc:
        log.warning("[fetch_itis_summary] %s → %s", name, exc)
        return None, f"ITIS lookup failed: {exc}"


def fetch_itis_synonyms(tsn: str) -> list:
    """Return ITIS synonyms for tsn via getSynonymsFromTSN.

    Each item: {"name": str, "authorship": str}.
    The ITIS "sciName" field contains the full scientific name string;
    "author" provides the separate authorship when available.
    """
    if not tsn:
        return []
    try:
        syns = _itis_get("getSynonymsFromTSN", {"tsn": tsn}, silent_404=True)
        result = []
        for s in (_as_dict(syns).get("synonyms") or []):
            if not isinstance(s, dict):
                continue
            sci = (s.get("sciName") or "").strip()
            if not sci:
                continue
            auth = (s.get("author") or "").strip()
            result.append({"name": sci, "authorship": auth})
        return result
    except Exception as exc:
        log.warning("[fetch_itis_synonyms] tsn=%s → %s", tsn, exc)
        return []


def fetch_zoobank_summary(name: str, max_acts: int = 10) -> tuple:
    """Return (lsid | None, summary_str).
    Mirrors get_zoobank_records() in query_databases_sandbox.py.
    """
    try:
        result = fetch_zoobank(name, max_acts=max_acts)
        if not result["acts"]:
            return None, "No nomenclatural acts found in ZooBank."
        lines = []
        for act in result["acts"]:
            line = act["namestring"]
            if act["rank"]:
                line += f" [{act['rank']}]"
            if act["author"]:
                line += f" — {act['author']}"
            line += f"\n  LSID: {act['lsid']}"
            if act["citation"]:
                line += f"\n  Ref:  {act['citation']}"
            lines.append(line)
        return result["lsid"], "\n".join(lines)
    except Exception as exc:
        log.warning("[fetch_zoobank_summary] %s → %s", name, exc)
        return None, f"ZooBank lookup failed: {exc}"


def fetch_bhl_records(name: str, api_key: str,
                       max_titles: int = 5, max_pages: int = 10) -> tuple:
    """Fetch BHL GetNameMetadata records.
    Returns (publications_list, pages_list) where:
      publications: [{"title", "year", "url"}, ...]
      pages:        [{"title", "page_url", "year"}, ...]
    Mirrors get_bhl_records() in query_databases_sandbox.py.
    """
    try:
        r = _get_with_retry(_BHL_API, params={
            "op": "GetNameMetadata", "name": name,
            "format": "json", "apikey": api_key,
        }, headers=_headers(), timeout=15)
        data    = r.json()
        results = data.get("Result", [])
        if not results or not isinstance(results, list):
            return [], []

        result     = results[0] if isinstance(results[0], dict) else {}
        titles_raw = result.get("Titles", []) or []
        publications: list = []
        pages:        list = []

        for title_rec in titles_raw:
            if len(publications) >= max_titles:
                break
            publications.append({
                "title": title_rec.get("FullTitle", "").strip(),
                "year":  str(title_rec.get("StartYear", "") or ""),
                "url":   title_rec.get("TitleUrl", ""),
            })
            for item in (title_rec.get("Items") or []):
                for page in (item.get("Pages") or []):
                    if len(pages) >= max_pages:
                        break
                    pages.append({
                        "title":    title_rec.get("FullTitle", "").strip(),
                        "page_url": page.get("PageUrl", ""),
                        "year":     str(page.get("Year", "") or ""),
                    })
                if len(pages) >= max_pages:
                    break
            if len(pages) >= max_pages:
                break
        return publications, pages
    except Exception as exc:
        log.warning("[fetch_bhl_records] %s → %s", name, _redact_query(exc))
        return [], []


def plazi_genus_species(taxon_name: str, rank: str):
    """Return (genus, species_or_None) for genus/species ranks, None for higher.
    Mirrors _plazi_genus_species() in query_databases_sandbox.py.
    """
    rank_upper = rank.upper()
    if rank_upper == "SPECIES":
        parts = taxon_name.split(None, 1)
        return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], None)
    if rank_upper == "GENUS":
        return (taxon_name, None)
    return None


def _safe_get_xml(url: str, params: dict = None) -> str:
    """GET and return raw response text (for XML endpoints). Never raises."""
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 200:
            return r.text
        log.warning("[xml GET] HTTP %s from %s", r.status_code, url)
    except Exception as exc:
        log.warning("[xml GET] %s → %s", url, exc)
    return ""


_XML_MAX_BYTES = 5 * 1024 * 1024  # 5 MB response-size limit before XML parsing

def _parse_plazi_xml(xml_text: str) -> tuple:
    """Parse Plazi treatment XML; return (description_texts, image_urls)."""
    import defusedxml.ElementTree as ET
    descriptions: list = []
    image_urls:   list = []
    if not xml_text:
        return descriptions, image_urls
    if len(xml_text.encode()) > _XML_MAX_BYTES:
        log.warning("[Plazi XML parse] response exceeds %d bytes, skipping", _XML_MAX_BYTES)
        return descriptions, image_urls
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError) as exc:
        log.warning("[Plazi XML parse] %s", exc)
        return descriptions, image_urls
    for elem in root.iter("subSubSection"):
        if elem.get("type") == "description":
            text = " ".join(" ".join(elem.itertext()).split()).strip()
            if len(text) > 40:
                descriptions.append(text)
    seen: set = set()
    for elem in root.iter("figureCitation"):
        uri = elem.get("httpUri", "").strip()
        if uri and uri not in seen:
            seen.add(uri)
            image_urls.append(uri)
    return descriptions, image_urls


def _plazi_get(endpoint: str, params: dict) -> list:
    """GET a Plazi API endpoint; return the response list (or [])."""
    try:
        r = _get_with_retry(f"{_PLAZI_API}{endpoint}", params=params,
                            headers=_headers(), timeout=20)
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as exc:
        log.warning("[Plazi] %s params=%s → %s", endpoint, params, exc)
        return []


def fetch_plazi_treatments(genus: str, species: str | None = None,
                            uuid_limit: int = 5) -> tuple:
    """Fetch Plazi treatment descriptions and figure images.
    Returns (descriptions, image_urls) where:
      descriptions: [{"taxon", "uuid", "text"}, ...]
      image_urls:   [str, ...]
    Mirrors get_plazi_treatments() in query_databases_sandbox.py.
    """
    params  = {"genus": genus, "format": "Json", "limit": uuid_limit}
    if species:
        params["species"] = species
    records = _plazi_get("/Taxon/TreatmentsForTaxon", params)

    all_descs:  list = []
    all_images: list = []
    seen_imgs:  set  = set()

    for rec in records:
        uuid     = rec.get("DocUuid", "").strip()
        tax_name = rec.get("TaxName", "").strip()
        if not uuid:
            continue
        xml_text = _safe_get_xml(f"{_PLAZI_XML}/{uuid}")
        descs, imgs = _parse_plazi_xml(xml_text)
        for text in descs:
            all_descs.append({"taxon": tax_name, "uuid": uuid, "text": text})
        for url in imgs:
            if url not in seen_imgs:
                seen_imgs.add(url)
                all_images.append(url)
    return all_descs, all_images


def fetch_plazi_specimens(genus: str, species: str | None = None,
                           spec_limit: int = 10) -> list:
    """Fetch Plazi specimen collection records.
    Returns [{"taxon", "country", "code", "institution"}, ...]
    Mirrors get_plazi_specimens() in query_databases_sandbox.py.
    """
    params  = {"genus": genus, "format": "Json", "limit": spec_limit}
    if species:
        params["species"] = species
    records = _plazi_get("/Taxon/SpecimensInCollections", params)
    return [{"taxon":       rec.get("TaxName", ""),
             "country":     rec.get("CollsCountry", ""),
             "code":        rec.get("CollsCode", ""),
             "institution": rec.get("CollsName", "")}
            for rec in records]


def _fetch_plazi_summary_html(uuid: str) -> dict:
    """Scrape tb.plazi.org/GgServer/summary/{uuid} for bibliographic metadata."""
    import re as _re
    url  = f"https://tb.plazi.org/GgServer/summary/{uuid}"
    html = _safe_get_xml(url)
    if not html:
        return {"summary_url": url, "title": "", "authors": "",
                "year": "", "journal": "", "doi": ""}
    result = {"summary_url": url, "title": "", "authors": "",
              "year": "", "journal": "", "doi": ""}
    doi_m = _re.search(r'href="(https://doi\.org/[^"]+)"', html)
    if doi_m:
        result["doi"] = doi_m.group(1)
    h1_m = _re.search(r'<h1[^>]*>(.*?)</h1>', html, _re.DOTALL)
    if h1_m:
        citation = _re.sub(r'<[^>]+>', '', h1_m.group(1)).strip()
        citation = _re.sub(r'\s+', ' ', citation)
        yr_m = _re.search(r',\s*(\d{4}),\s*', citation)
        if yr_m:
            result["year"]    = yr_m.group(1)
            result["authors"] = citation[:yr_m.start()].strip()
            result["title"]   = citation[yr_m.end():].strip()
        else:
            result["title"] = citation
    jrnl_m = _re.search(
        r'>\s*([A-Z][^<]{4,120}(?:pp\.|pages?)[^<]{2,60})\s*<', html)
    if jrnl_m:
        result["journal"] = _re.sub(r'\s+', ' ', jrnl_m.group(1)).strip()
    return result


def fetch_plazi_keys(genus: str, species: str | None = None,
                     key_limit: int = 5) -> list:
    """Fetch Plazi treatments containing identification keys.
    Returns [{"taxon", "uuid", "summary_url", "title", "authors",
              "year", "journal", "doi"}, ...]
    Mirrors get_plazi_keys() in query_databases_sandbox.py.
    """
    params  = {"genus": genus, "format": "Json", "limit": key_limit}
    if species:
        params["species"] = species
    records = _plazi_get("/Taxon/TreatmentsWithKeys", params)
    results = []
    for rec in records:
        uuid = rec.get("DocArticleUuid", "").strip()
        if not uuid:
            continue
        entry = {"taxon":       rec.get("TaxName", ""),
                 "uuid":        uuid,
                 "summary_url": f"https://tb.plazi.org/GgServer/summary/{uuid}",
                 "title": "", "authors": "", "year": "", "journal": "", "doi": ""}
        meta = _fetch_plazi_summary_html(uuid)
        if meta:
            entry.update({k: meta[k] for k in
                          ("title", "authors", "year", "journal", "doi", "summary_url")})
        results.append(entry)
    return results


# ============================================================
# ENCODING / TEXT NORMALIZATION HELPERS
# (ported from query_databases_sandbox.py)
# ============================================================

def _fix_encoding(text: str) -> str:
    """Fix GBIF double-encoded UTF-8 (e.g. 'BeitrÃ¤ge' → 'Beiträge')."""
    if not isinstance(text, str):
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _normalize_doi(doi_raw) -> str:
    """Return lowercase DOI without URL prefix, or '' if falsy."""
    if not doi_raw:
        return ""
    doi = re.sub(r'^https?://doi\.org/', '', str(doi_raw).strip().lower())
    doi = re.sub(r'^doi:\s*', '', doi).strip()
    return doi


def _normalize_title_key(title) -> str:
    """Lowercase alphanum-stripped 60-char prefix for title deduplication."""
    if not title:
        return ""
    t = re.sub(r'[^a-z0-9 ]', '', title.lower())
    return ' '.join(t.split())[:60]


_DOI_RE = re.compile(r'\b(10\.\d{4,9}/\S+)', re.IGNORECASE)


def _canonical_key(name: str) -> str:
    """Genus+epithet key for synonym deduplication (strips authorship)."""
    if not name:
        return ""
    parts = name.strip().split()
    result = []
    for i, p in enumerate(parts):
        clean = p.strip("(),.")
        if i == 0:
            result.append(clean.lower())
        elif clean and clean[0].islower():
            result.append(clean.lower())
            break
        else:
            break
    return " ".join(result)


def _name_authorship(name: str) -> str:
    """Extract authorship from scientific name (skips genus + epithet)."""
    if not name:
        return ""
    parts = name.strip().split()
    skip = 1
    if len(parts) > 1:
        w = parts[1].strip("(),.")
        if w and w[0].islower():
            skip = 2
    return " ".join(parts[skip:]).strip()


def _auth_year(auth: str) -> str:
    """Extract 4-digit publication year from authorship string."""
    m = re.search(r'\b(\d{4})\b', auth or "")
    return m.group(1) if m else ""


def _auth_key(auth: str) -> str:
    """Normalize authorship to lowercase alphanum for equality comparison."""
    return re.sub(r'[^a-z0-9]', '', (auth or "").lower())


def _tabulate(headers: list, rows: list, indent: str = "  ",
              max_widths: list = None) -> str:
    """Format rows as a pipe-delimited fixed-width text table.
    Columns where every data row is empty are silently dropped.
    max_widths: optional list of int|None per column; cells exceeding their
    limit are truncated with a trailing ellipsis character.
    """
    n = len(headers)
    if max_widths:
        def _clip(cell, mw):
            return cell[:mw - 1] + "…" if mw and len(cell) > mw else cell
        rows = [[_clip(cell, max_widths[i]) for i, cell in enumerate(row)]
                for row in rows]
    keep = [i for i in range(n) if any(row[i] for row in rows)]
    if not keep:
        return ""
    h = [headers[i] for i in keep]
    r = [[row[i] for i in keep] for row in rows]
    widths = [len(hdr) for hdr in h]
    for row in r:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    def _line(cells):
        return indent + "| " + " | ".join(
            c.ljust(w) for c, w in zip(cells, widths)) + " |"
    sep = indent + "|-" + "-|-".join("-" * w for w in widths) + "-|"
    return "\n".join([_line(h), sep] + [_line(row) for row in r])


def _format_apa(csl: dict) -> str:
    """Format a CSL-JSON dict in approximate APA 7 style (plain text)."""
    def _author_str(author_list):
        def _one(a):
            fam = a.get("family", "")
            giv = a.get("given", "")
            if fam and giv:
                initials = " ".join(p[0] + "." for p in giv.split() if p)
                return f"{fam}, {initials}"
            return fam or a.get("literal", "")
        n = len(author_list)
        if n == 0:
            return ""
        if n == 1:
            return _one(author_list[0])
        if n <= 20:
            parts = [_one(a) for a in author_list]
            return ", ".join(parts[:-1]) + f", & {parts[-1]}"
        parts = [_one(a) for a in author_list[:19]]
        return ", ".join(parts) + f", ... {_one(author_list[-1])}"

    authors  = _author_str(csl.get("author", []))
    dp       = (csl.get("issued", {}).get("date-parts") or [[]])[0]
    year     = str(dp[0]) if dp else "n.d."
    title    = re.sub(r'<[^>]+>', '', csl.get("title", ""))
    ref_type = csl.get("type", "article-journal")
    doi      = csl.get("DOI", "") or csl.get("doi", "")
    doi_str  = f" https://doi.org/{doi}" if doi else ""

    if ref_type in ("article-journal", "article", "paper-conference"):
        journal  = csl.get("container-title", "")
        vol      = csl.get("volume", "")
        issue    = csl.get("issue", "")
        page     = csl.get("page", "")
        vol_part = vol + (f"({issue})" if issue else "") if vol else ""
        mid      = ", ".join(filter(None, [journal, vol_part, page]))
        return f"{authors} ({year}). {title}. {mid}.{doi_str}".strip()
    if ref_type == "book":
        pub      = csl.get("publisher", "")
        place    = csl.get("publisher-place", "")
        pub_part = f"{place}: {pub}" if place and pub else pub or place
        return f"{authors} ({year}). {title}. {pub_part}.{doi_str}".strip()
    if ref_type == "chapter":
        editors  = _author_str(csl.get("editor", []))
        ed_part  = f"In {editors} (Ed.), " if editors else "In "
        book     = csl.get("container-title", "")
        page     = csl.get("page", "")
        pp_part  = f" (pp. {page})" if page else ""
        pub      = csl.get("publisher", "")
        return (f"{authors} ({year}). {title}. "
                f"{ed_part}{book}{pp_part}. {pub}.{doi_str}").strip()
    return f"{authors} ({year}). {title}.{doi_str}".strip()


# ============================================================
# GBIF BACKBONE — RICH VERSION (adds publishedIn, hierarchy, etc.)
# ============================================================

_RANK_CHAIN = [
    ("KINGDOM", "kingdom"), ("PHYLUM", "phylum"), ("CLASS", "class"),
    ("ORDER", "order"), ("FAMILY", "family"), ("GENUS", "genus"),
    ("SPECIES", "specificEpithet"), ("SUBSPECIES", "infraspecificEpithet"),
]
_RANK_PLURAL = {
    "KINGDOM": "kingdoms", "PHYLUM": "phyla",    "CLASS": "classes",
    "ORDER": "orders",     "FAMILY": "families", "GENUS": "genera",
    "TRIBE": "tribes",     "SUBFAMILY": "subfamilies",
    "SUPERFAMILY": "superfamilies",
    "SPECIES": "species",  "SUBSPECIES": "subspecies", "VARIETY": "varieties",
}


def resolve_gbif_backbone_rich(name: str, rank: str) -> dict | None:
    """Full GBIF backbone resolution with authorship, hierarchy, publishedIn, etc.
    Returns dict with all fields needed for §1 report, or None on failure.
    Extends the lightweight resolve_gbif_backbone() with extra detail fields.
    """
    try:
        match = _gbif_match_strict(name, rank)
        if match and match.get("usageKey"):
            usage_key = match["usageKey"]
            sci_name  = match.get("scientificName") or name
        else:
            search = _gbif_get("/species/search",
                               {"q": name, "rank": rank.upper(),
                                "datasetKey": _GBIF_BACKBONE, "limit": 5})
            results = [r for r in (search or {}).get("results", [])
                       if r.get("canonicalName", "").lower() == name.lower()
                       and r.get("rank") == rank.upper()]
            if not results:
                return None
            usage_key = results[0].get("key")
            sci_name  = results[0].get("scientificName") or name
        if not usage_key:
            return None

        detail       = _gbif_get(f"/species/{usage_key}") or {}
        published_in = _fix_encoding(detail.get("publishedIn") or "")
        num_desc     = detail.get("numDescendants")
        parent       = detail.get("parent") or ""
        authorship   = detail.get("authorship") or ""
        gbif_rank    = (detail.get("rank") or rank).upper()

        # Build colon-delimited hierarchy string
        hier_parts: list = []
        for r_name, r_field in _RANK_CHAIN:
            val = (detail.get(r_field) or "").strip()
            if val:
                hier_parts.append(val)
            if r_name == gbif_rank:
                break
        if gbif_rank and gbif_rank not in {r for r, _ in _RANK_CHAIN}:
            hier_parts.append(detail.get("canonicalName") or sci_name.split()[0])
        hierarchy = ":".join(hier_parts)

        # External IDs from GBIF identifier endpoint
        tsn = taxid = lsid = None
        id_data = _gbif_get(f"/species/{usage_key}/identifier") or {}
        for item in id_data.get("results", []):
            id_type = item.get("type", "")
            val     = item.get("identifier", "")
            if (id_type == "ITIS_TSN" or "itis.gov" in val) and not tsn:
                tsn   = val.split("/")[-1].split(":")[-1]
            elif (id_type == "NCBI_TAXONOMY" or "ncbi" in val.lower()) and not taxid:
                taxid = val.split("/")[-1].split(":")[-1]
            elif "lsid" in val.lower() and not lsid:
                lsid  = val

        _ns = detail.get("nomenclaturalStatus")
        _nom_status = ("; ".join(str(v) for v in _ns)
                       if isinstance(_ns, list) else (str(_ns) if _ns else ""))
        _tax_status = (detail.get("taxonomicStatus") or "").lower()
        _accepted_name = detail.get("accepted") or ""

        return {
            "usageKey":           usage_key,
            "scientificName":     sci_name,
            "rank":               gbif_rank,
            "authorship":         authorship,
            "publishedIn":        published_in,
            "numDescendants":     num_desc,
            "parent":             parent,
            "hierarchy":          hierarchy,
            "tsn":                tsn,
            "taxid":              taxid,
            "lsid":               lsid,
            # Individual rank fields from detail
            "kingdom":            detail.get("kingdom") or "",
            "phylum":             detail.get("phylum") or "",
            "class_name":         detail.get("class") or "",
            "order":              detail.get("order") or "",
            "family":             detail.get("family") or "",
            "genus":              detail.get("genus") or "",
            "taxonomicStatus":    _tax_status,
            "nomenclaturalStatus": _nom_status,
            "acceptedName":       _accepted_name,
        }
    except Exception as exc:
        log.warning("[resolve_gbif_backbone_rich] %s → %s", name, exc)
        return None


def fetch_gbif_children(usage_key: str, rank: str = "") -> list:
    """Retrieve direct child taxa from GBIF backbone (up to 300).
    Skips DOUBTFUL, MISAPPLIED, OTU clusters, nameless entries.
    Returns [] for SPECIES and below.
    Returns [{"name", "rank", "authorship", "key"}, ...] sorted by name.
    """
    if rank.upper() in ("SPECIES", "SUBSPECIES", "VARIETY", "FORM"):
        return []
    try:
        children: list = []
        offset = 0
        while len(children) < 300:
            data    = _gbif_get(f"/species/{usage_key}/children",
                                {"limit": 100, "offset": offset})
            results = (data or {}).get("results", [])
            if not results:
                break
            for r in results:
                if len(children) >= 300:
                    break
                if r.get("taxonomicStatus") in ("DOUBTFUL", "MISAPPLIED"):
                    continue
                if r.get("nameType") == "OTU" or not r.get("canonicalName"):
                    continue
                children.append({
                    "name":       r.get("canonicalName") or r.get("scientificName") or "",
                    "rank":       (r.get("rank") or "").upper(),
                    "authorship": r.get("authorship") or "",
                    "key":        r.get("key", ""),
                })
            if (data or {}).get("endOfRecords") or len(results) < 100:
                break
            offset += 100
        children.sort(key=lambda c: c["name"])
        return children
    except Exception as exc:
        log.warning("[fetch_gbif_children] %s → %s", usage_key, exc)
        return []


def fetch_gbif_species_profiles(usage_key: str) -> dict:
    """Retrieve habitat flags and extinction status from GBIF speciesProfiles.
    Returns {"habitats": [str, ...], "extinct": bool|None, "sources": [str, ...]}.
    """
    try:
        data    = _gbif_get(f"/species/{usage_key}/speciesProfiles") or {}
        records = data.get("results", [])
        marine      = any(r.get("marine")      for r in records)
        freshwater  = any(r.get("freshwater")  for r in records)
        terrestrial = any(r.get("terrestrial") for r in records)
        extinct_vals = [r["extinct"] for r in records if r.get("extinct") is not None]
        extinct      = any(extinct_vals) if extinct_vals else None
        habitats = [h for h, v in [("marine", marine),
                                    ("freshwater", freshwater),
                                    ("terrestrial", terrestrial)] if v]
        sources  = list(dict.fromkeys(r.get("source", "") for r in records
                                      if r.get("source")))
        return {"habitats": habitats, "extinct": extinct, "sources": sources}
    except Exception as exc:
        log.warning("[fetch_gbif_species_profiles] %s → %s", usage_key, exc)
        return {"habitats": [], "extinct": None, "sources": []}


def fetch_gbif_references(usage_key: str) -> list:
    """Retrieve typed literature references from GBIF /species/{key}/references.
    Returns [{"citation", "type", "source", "doi"}, ...] sorted by type.
    DOIs are extracted from citation text when not provided directly.
    """
    _TYPE_ORDER = {
        "original description": 0, "taxonomy source": 1,
        "identification resource": 2, "basis of record": 3,
    }
    try:
        data    = _gbif_get(f"/species/{usage_key}/references", {"limit": 100}) or {}
        results = []
        seen: set = set()
        for r in data.get("results", []):
            citation = _fix_encoding(r.get("citation", "")).strip()
            if not citation or citation in seen:
                continue
            seen.add(citation)
            doi_m = _DOI_RE.search(citation)
            doi   = _normalize_doi(doi_m.group(1).rstrip(".,;)") if doi_m else "")
            results.append({
                "citation": citation,
                "type":     r.get("type", ""),
                "source":   r.get("source", ""),
                "doi":      doi,
            })
        results.sort(key=lambda r: (_TYPE_ORDER.get(r["type"], 99), r["type"]))
        return results
    except Exception as exc:
        log.warning("[fetch_gbif_references] %s → %s", usage_key, exc)
        return []


def fetch_gbif_pub_dicts(usage_key: str, limit: int = 100) -> list:
    """Query GBIF literature index and return publication dicts for resolve_publications.
    Uses gbifTaxonKey + gbifHigherTaxonKey; deduplicates by title.
    Returns [{"doi", "title", "csl", "raw_citation", "sources"}, ...].
    """
    try:
        seen_titles: set = set()
        pubs: list = []
        for param in ("gbifTaxonKey", "gbifHigherTaxonKey"):
            if len(pubs) >= limit:
                break
            data = _gbif_get("/literature/search",
                             {param: usage_key, "limit": min(limit, 100)}) or {}
            for p in data.get("results", []):
                title = (p.get("title") or "Untitled").strip()
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                doi  = _normalize_doi(
                    p.get("doi") or (p.get("identifiers") or {}).get("doi", ""))
                year = p.get("year")
                csl  = None
                authors_raw = p.get("authors") or []
                if title and (authors_raw or year):
                    csl = {"id": doi or title[:20], "type": "article-journal",
                           "title": title}
                    if doi:
                        csl["DOI"] = doi
                    if year:
                        csl["issued"] = {"date-parts": [[year]]}
                    author_list = []
                    for a in authors_raw:
                        if isinstance(a, str):
                            author_list.append({"literal": a})
                        elif isinstance(a, dict):
                            entry = {}
                            if a.get("lastName"):
                                entry["family"] = a["lastName"]
                            if a.get("firstName"):
                                entry["given"] = a["firstName"]
                            if entry:
                                author_list.append(entry)
                    if author_list:
                        csl["author"] = author_list
                pubs.append({
                    "doi": doi, "title": title, "csl": csl,
                    "raw_citation": None, "sources": ["GBIF Literature"],
                })
                if len(pubs) >= limit:
                    break
        return pubs[:limit]
    except Exception as exc:
        log.warning("[fetch_gbif_pub_dicts] %s → %s", usage_key, exc)
        return []


# ============================================================
# ZOOBANK — ENHANCED (pub_dicts + OriginalReferenceUUID fix)
# ============================================================

def _zoobank_ref_to_csl(ref_data: dict) -> dict:
    """Build a CSL-JSON dict from a ZooBank References.json record."""
    _type_map = {
        "Journal Article": "article-journal", "Article": "article-journal",
        "Book": "book", "Book Chapter": "chapter", "Chapter": "chapter",
    }
    csl = {
        "id":   ref_data.get("referenceuuid", "zb"),
        "type": _type_map.get(ref_data.get("referencetype", ""), "article-journal"),
    }
    raw_authors = ref_data.get("authors") or []
    flat = []
    for item in raw_authors:
        if isinstance(item, list):
            flat.extend(item)
        elif isinstance(item, dict):
            flat.append(item)
    if flat:
        csl["author"] = [{"family": a.get("familyname", ""),
                          "given":  a.get("givenname", "")}
                         for a in flat if a.get("familyname")]
    elif ref_data.get("authorlist"):
        csl["author"] = [{"literal": ref_data["authorlist"]}]
    yr = str(ref_data.get("year") or "")
    if yr.isdigit():
        csl["issued"] = {"date-parts": [[int(yr)]]}
    raw_title = ref_data.get("title") or ref_data.get("label") or ""
    csl["title"] = re.sub(r'<[^>]+>', '', _fix_encoding(raw_title)).strip()
    if csl["type"] == "book":
        if ref_data.get("publisher"):
            csl["publisher"] = _fix_encoding(ref_data["publisher"])
        if ref_data.get("placepublished"):
            csl["publisher-place"] = _fix_encoding(ref_data["placepublished"])
    if ref_data.get("volume"):
        csl["volume"] = str(ref_data["volume"])
    if ref_data.get("number"):
        csl["issue"] = str(ref_data["number"])
    start = str(ref_data.get("startpage") or "")
    end   = str(ref_data.get("endpage") or "")
    if start and end:
        csl["page"] = f"{start}–{end}"
    elif start:
        csl["page"] = start
    return csl


def get_zoobank_full(name: str, max_acts: int = 10) -> tuple:
    """Fetch ZooBank nomenclatural acts with pub_dicts for resolve_publications.
    Uses OriginalReferenceUUID (correct field — not referenceuuid/PublicationUUID).
    Returns (lsid | None, summary_str, pub_dicts).
    """
    try:
        data = _zoobank_get("/NomenclaturalActs.json", {"search_term": name})
    except Exception as exc:
        log.warning("[get_zoobank_full] %s → %s", name, exc)
        return None, "ZooBank lookup failed.", []

    if not isinstance(data, list) or not data:
        return None, "No nomenclatural acts found in ZooBank.", []

    lsid          = None
    lines         = []
    seen_ref_ids: set  = set()
    pub_dicts:    list = []

    for act in data[:max_acts]:
        act_lsid   = act.get("lsid", "")
        namestring = act.get("namestring") or act.get("label", name)
        citation   = act.get("citationdetails", "")
        rank       = ""
        author     = ""
        guid = act_lsid.split(":")[-1] if ":" in act_lsid else ""
        if guid:
            detail   = _zoobank_first(_zoobank_get(f"/NomenclaturalActs.json/{guid}"))
            rank     = detail.get("rankgroup", "")
            author   = detail.get("label", "")
            ref_uuid = detail.get("OriginalReferenceUUID") or ""
            if ref_uuid:
                ref_data = _zoobank_first(_zoobank_get(f"/References.json/{ref_uuid}"))
                raw_cit  = _fix_encoding(
                    ref_data.get("label") or ref_data.get("value") or "")
                if raw_cit and not citation:
                    citation = raw_cit
                if ref_uuid not in seen_ref_ids:
                    seen_ref_ids.add(ref_uuid)
                    csl_item = _zoobank_ref_to_csl(ref_data) if ref_data else None
                    pub_dicts.append({
                        "doi":          "",
                        "title":        (csl_item or {}).get("title", ""),
                        "csl":          csl_item,
                        "raw_citation": raw_cit if not csl_item else None,
                        "sources":      ["ZooBank"],
                    })

        if act_lsid and not lsid:
            lsid = act_lsid

        line = namestring
        if rank:   line += f" [{rank}]"
        if author: line += f" — {author}"
        line += f"\n  LSID: {act_lsid}"
        if citation: line += f"\n  Ref:  {citation}"
        lines.append(line)

    summary = "\n".join(lines) if lines else "No records found."
    return lsid, summary, pub_dicts


# ============================================================
# CROSSREF RESOLUTION PIPELINE
# ============================================================

def _crossref_work_to_csl(work: dict) -> dict:
    """Convert a CrossRef work record to a CSL-JSON dict."""
    _type_map = {
        "journal-article": "article-journal",    "book": "book",
        "book-chapter": "chapter",               "monograph": "book",
        "proceedings-article": "paper-conference", "report": "report",
    }
    csl = {
        "id":   work.get("DOI", "cr"),
        "type": _type_map.get(work.get("type", ""), "article-journal"),
    }
    authors = []
    for a in work.get("author", []):
        entry = {}
        if a.get("family"): entry["family"] = a["family"]
        if a.get("given"):  entry["given"]  = a["given"]
        if a.get("name") and not entry: entry["literal"] = a["name"]
        if entry: authors.append(entry)
    if authors: csl["author"] = authors
    titles = work.get("title", [])
    if titles: csl["title"] = titles[0]
    containers = work.get("container-title", [])
    if containers: csl["container-title"] = containers[0]
    date_parts = (work.get("issued", {}).get("date-parts") or [[]])[0]
    if date_parts: csl["issued"] = {"date-parts": [date_parts[:1]]}
    for field in ("volume", "issue", "page", "publisher"):
        if work.get(field): csl[field] = work[field]
    if work.get("DOI"): csl["DOI"] = work["DOI"]
    return csl


def _crossref_fetch_csl(doi: str) -> dict | None:
    """Fetch a CrossRef work by DOI; return CSL-JSON dict or None."""
    import urllib.parse
    clean = _normalize_doi(doi)
    if not clean:
        return None
    try:
        r = _get_with_retry(
            f"{_CROSSREF_WORKS}/{urllib.parse.quote(clean, safe='/()')}",
            headers=_headers(), timeout=15,
        )
        work = r.json().get("message", {})
        return _crossref_work_to_csl(work) if work.get("title") else None
    except Exception as exc:
        log.warning("[_crossref_fetch_csl] %s → %s", doi, exc)
        return None


def _crossref_title_search_doi(title: str) -> str | None:
    """Search CrossRef by title; return normalized DOI if confident, else None."""
    if not title or len(title.strip()) < 15:
        return None
    try:
        r = _get_with_retry(_CROSSREF_WORKS,
                            params={"query.title": title, "rows": 1},
                            headers=_headers(), timeout=15)
        items = r.json().get("message", {}).get("items", [])
        if not items:
            return None
        found_titles = items[0].get("title", [])
        if not found_titles:
            return None
        q_key = _normalize_title_key(title)
        f_key = _normalize_title_key(found_titles[0])
        if not q_key or not f_key:
            return None
        match_chars = sum(a == b for a, b in zip(q_key, f_key))
        threshold   = min(30, int(min(len(q_key), len(f_key)) * 0.65))
        if match_chars < threshold:
            return None
        return _normalize_doi(items[0].get("DOI", "")) or None
    except Exception as exc:
        log.warning("[_crossref_title_search_doi] %s → %s", title[:40], exc)
        return None


def _crossref_bibliographic_search(citation_str: str) -> tuple:
    """Search CrossRef using a full citation string (score threshold 70).
    Returns (doi_normalized, csl_dict) or (None, None) if not found/score too low.
    """
    if not citation_str or len(citation_str.strip()) < 25:
        return None, None
    try:
        r = _get_with_retry(
            _CROSSREF_WORKS,
            params={"query.bibliographic": citation_str.strip(), "rows": 1},
            headers=_headers(), timeout=15,
        )
        items = r.json().get("message", {}).get("items", [])
        if not items:
            return None, None
        item  = items[0]
        score = item.get("score", 0)
        if score < 70:
            return None, None
        doi = _normalize_doi(item.get("DOI", ""))
        if not doi:
            return None, None
        csl = _crossref_work_to_csl(item)
        return doi, csl if (csl and csl.get("title")) else (doi, None)
    except Exception as exc:
        log.warning("[_crossref_bibliographic_search] → %s", exc)
        return None, None


def get_crossref_pub_dicts(name: str, max_results: int = 20) -> list:
    """Query CrossRef for publications mentioning taxon name; return pub_dicts list."""
    try:
        r = _get_with_retry(_CROSSREF_WORKS,
                            params={"query": f'"{name}"', "rows": max_results},
                            headers=_headers(), timeout=15)
        pubs = []
        for item in r.json().get("message", {}).get("items", []):
            doi   = _normalize_doi(item.get("DOI", ""))
            title = (item.get("title") or [""])[0]
            if not doi and not title:
                continue
            pubs.append({
                "doi": doi, "title": title,
                "csl": None, "raw_citation": None,
                "sources": ["CrossRef"],
            })
        return pubs
    except Exception as exc:
        log.warning("[get_crossref_pub_dicts] %s → %s", name, exc)
        return []


# ============================================================
# CATALOGUE OF LIFE — ENHANCED (pub_dicts + environments)
# ============================================================

def get_col_full(name: str, syn_limit: int = 30) -> tuple:
    """Fetch CoL status, synonyms, and publication dicts for resolve_publications.
    Returns (accepted_name | None, synonyms_list, summary_str, pub_dicts).
    Mirrors get_col_records() in query_databases_sandbox.py.
    """
    try:
        search  = _col_get(f"/dataset/{_COL_KEY}/nameusage/search",
                           {"q": name, "limit": 10})
        results = (search or {}).get("result", [])
        if not results:
            return None, [], "Not found in Catalogue of Life.", []

        name_lower = name.lower()
        match_rec  = next(
            (r for r in results
             if name_lower in (r.get("usage", {}).get("label") or "").lower()),
            results[0]
        )
        usage        = match_rec.get("usage", {})
        usage_id     = usage.get("id", "")
        status       = usage.get("status", "unknown")
        label        = usage.get("label") or name
        environments = usage.get("environments", [])
        ref_ids      = list(usage.get("referenceIds") or [])

        if status.lower() in ("synonym", "ambiguous synonym", "misapplied"):
            accepted_info = usage.get("accepted", {})
            accepted_name = (accepted_info.get("label") or
                             (accepted_info.get("name") or {}).get("scientificName") or "")
            summary = (f"Status: {status}\n"
                       f"  '{label}' is a synonym of: {accepted_name}")
            return accepted_name or None, [], summary, []

        accepted_name = label

        synonyms = []
        if usage_id:
            syn_data = _col_get(f"/dataset/{_COL_KEY}/taxon/{usage_id}/synonyms")
            if isinstance(syn_data, list):
                raw_list = syn_data
            else:
                d = syn_data or {}
                raw_list = (d.get("heterotypic") or d.get("result") or
                            d.get("synonyms") or [])
                raw_list = raw_list + (d.get("homotypic") or [])
            for s in (raw_list or [])[:syn_limit]:
                if not isinstance(s, dict):
                    continue
                s_label  = (s.get("label") or
                            (s.get("name") or {}).get("scientificName") or "")
                s_status = s.get("status", "synonym")
                if s_label:
                    synonyms.append({"name": s_label, "status": s_status})
                pub_id = (s.get("name") or {}).get("publishedInId")
                if pub_id and pub_id not in ref_ids:
                    ref_ids.append(pub_id)

        col_pubs = []
        for ref_id in ref_ids:
            ref_data = _col_get(f"/dataset/{_COL_KEY}/reference/{ref_id}") or {}
            citation = _fix_encoding(ref_data.get("citation", ""))
            csl_data = ref_data.get("csl")
            doi      = _normalize_doi((csl_data or {}).get("DOI") or
                                      (csl_data or {}).get("doi") or "")
            title    = ((csl_data or {}).get("title") or
                        (csl_data or {}).get("title-short") or "")
            if citation or title:
                col_pubs.append({
                    "doi": doi, "title": title, "csl": csl_data,
                    "raw_citation": citation if not csl_data else None,
                    "sources": ["CoL"],
                })

        summary = f"Status: {status}\nAccepted: {accepted_name}"
        if environments:
            summary += f"\nEnvironments: {', '.join(environments)}"
        return accepted_name, synonyms, summary, col_pubs
    except Exception as exc:
        log.warning("[get_col_full] %s → %s", name, exc)
        return None, [], f"CoL lookup failed: {exc}", []


def fetch_col_children(name: str) -> list:
    """Return direct children of name from ChecklistBank (CoL dataset).

    Does its own name lookup to obtain usage_id, then calls
    /dataset/{COL_KEY}/taxon/{usage_id}/children.
    Each item: {"name": str, "authorship": str, "rank": str}.
    """
    try:
        search  = _col_get(f"/dataset/{_COL_KEY}/nameusage/search",
                           {"q": name, "limit": 10})
        results = (search or {}).get("result", [])
        if not results:
            return []
        name_lower = name.lower()
        match_rec  = next(
            (r for r in results
             if name_lower in (r.get("usage", {}).get("label") or "").lower()),
            results[0],
        )
        usage_id = (match_rec.get("usage") or {}).get("id", "")
        if not usage_id:
            return []

        data = _col_get(f"/dataset/{_COL_KEY}/taxon/{usage_id}/children")
        if data is None:
            return []
        if isinstance(data, list):
            raw = data
        else:
            raw = data.get("result") or data.get("children") or []

        out = []
        for item in raw:
            usage_item = item.get("usage", item)
            name_obj   = (usage_item.get("name") or {})
            sci  = (name_obj.get("scientificName") or
                    usage_item.get("label") or "").strip()
            auth = (name_obj.get("authorship") or "").strip()
            rank = (name_obj.get("rank") or
                    usage_item.get("rank") or "").lower()
            if sci:
                out.append({
                    "name":       f"{sci} {auth}".strip() if auth else sci,
                    "authorship": auth,
                    "rank":       rank,
                })
        return out
    except Exception as exc:
        log.warning("[fetch_col_children] %s → %s", name, exc)
        return []


# ============================================================
# NCBI — TUPLE-RETURNING VERSION (backfill-aware)
# ============================================================

def get_ncbi_records(taxid: str | None, name: str, acc_limit: int = 50) -> tuple:
    """Returns (resolved_taxid | None, summary_str).
    Mirrors get_ncbi_records() in query_databases_sandbox.py.
    """
    try:
        if not taxid:
            res   = _ncbi_get(_NCBI_ESEARCH,
                              {"db": "taxonomy", "term": name, "retmode": "json"})
            ids   = res.get("esearchresult", {}).get("idlist", [])
            taxid = ids[0] if ids else None
        if not taxid:
            return None, "0 matches found (No mapped TaxID available)"

        seq_res  = _ncbi_get(_NCBI_ESEARCH,
                             {"db": "nucleotide",
                              "term": f"txid{taxid}[Organism]",
                              "retmode": "json", "retmax": acc_limit})
        eresult  = seq_res.get("esearchresult", {})
        count    = eresult.get("count", "0")
        uid_list = eresult.get("idlist", [])

        accessions = []
        if uid_list:
            summary = _ncbi_get(_NCBI_ESUMMARY,
                                {"db": "nucleotide",
                                 "id": ",".join(uid_list), "retmode": "json"})
            res_map = summary.get("result", {})
            for uid in uid_list:
                doc = res_map.get(uid, {})
                acc = doc.get("accessionversion") or doc.get("caption")
                if acc:
                    accessions.append(acc)

        lines = [f"{count} nucleotide entries in GenBank [TaxID: {taxid}]"]
        if accessions:
            lines.append(f"Sample accessions: {', '.join(accessions)}")
        return taxid, "\n".join(lines)
    except Exception as exc:
        log.warning("[get_ncbi_records] %s → %s", name, exc)
        return None, f"NCBI lookup failed: {exc}"


# ============================================================
# WIKIDATA HELPERS (for BHL enrichment chain)
# ============================================================

_WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData"
_WIKIDATA_UA     = {"User-Agent": "TaxonGPT/1.0 (allen.rodrigo@gmail.com)"}
_wd_label_cache: dict = {}


def _wikidata_label(qid: str) -> str:
    """Return English label for a Wikidata entity QID; cached per session."""
    if not qid:
        return ""
    if qid in _wd_label_cache:
        return _wd_label_cache[qid]
    try:
        r = _get_with_retry(f"{_WIKIDATA_ENTITY}/{qid}.json",
                            headers={**_headers(), **_WIKIDATA_UA}, timeout=15)
        entity = r.json().get("entities", {}).get(qid, {})
        label  = entity.get("labels", {}).get("en", {}).get("value") or qid
    except Exception:
        label = qid
    _wd_label_cache[qid] = label
    return label


def _wikidata_title_meta(qid: str) -> dict:
    """Return BHL publication metadata from Wikidata (place, dates, corporate author).
    Uses P291 (place), P571/P576/P582/P2669 (dates), P2093 (author string).
    """
    try:
        r = _get_with_retry(f"{_WIKIDATA_ENTITY}/{qid}.json",
                            headers={**_headers(), **_WIKIDATA_UA}, timeout=15)
        entity = r.json().get("entities", {}).get(qid, {})
        if not entity:
            return {}
        en_label = entity.get("labels", {}).get("en", {}).get("value") or ""
        _wd_label_cache[qid] = en_label
        claims = entity.get("claims", {})

        def _time_year(prop):
            for stmt in claims.get(prop, []):
                snak = stmt.get("mainsnak", {})
                if snak.get("snaktype") != "value":
                    continue
                time_str = (snak.get("datavalue", {}).get("value") or {}).get("time", "")
                m = re.search(r'\+?(\d{4})', time_str)
                if m:
                    return m.group(1)
            return ""

        def _entity_qid(prop):
            for stmt in claims.get(prop, []):
                snak = stmt.get("mainsnak", {})
                if snak.get("snaktype") != "value":
                    continue
                return (snak.get("datavalue", {}).get("value") or {}).get("id", "")
            return ""

        def _string_val(prop):
            for stmt in claims.get(prop, []):
                snak = stmt.get("mainsnak", {})
                if snak.get("snaktype") != "value":
                    continue
                val = snak.get("datavalue", {}).get("value")
                if isinstance(val, str):
                    return val
            return ""

        place_qid  = _entity_qid("P291")
        place      = _wikidata_label(place_qid) if place_qid else ""
        start_year = _time_year("P571") or _time_year("P580")
        end_year   = (_time_year("P576") or _time_year("P582")
                      or _time_year("P2669"))
        author_str = _fix_encoding(_string_val("P2093"))

        return {"title": en_label, "place": place,
                "start_year": start_year, "end_year": end_year,
                "author_str": author_str}
    except Exception as exc:
        log.warning("[_wikidata_title_meta] %s → %s", qid, exc)
        return {}


# ============================================================
# PLAZI — GGSERVER HTML SEARCH (replaces broken api.plazi.org)
# api.plazi.org/v1 accepts TCP but hangs — never use it.
# ============================================================

_PLAZI_GGSERVER   = "https://tb.plazi.org/GgServer"
_PLAZI_TREAT_RE   = re.compile(
    r'/GgServer/html/([0-9A-Fa-f]{32})[^"]*"\s+title="Open treatment">'
    r'([^<]+)</a>', re.IGNORECASE)
_PLAZI_ARTICLE_RE = re.compile(
    r'/GgServer/summary/([0-9A-Fa-f]{32})[^"]*"\s+[^>]*title="Go to article'
    r' overview">([^<]+)</a>', re.IGNORECASE)


def _plazi_ggserver_search(taxon_name: str, limit: int = 20) -> list:
    """Search Plazi TreatmentBank via GgServer HTML endpoint.
    Returns [{"treatment_uuid", "taxon_name", "article_uuid", "citation"}, ...].
    """
    import html as _html_mod
    try:
        html_text = _safe_get_xml(
            f"{_PLAZI_GGSERVER}/search",
            params={
                "taxonomicName.taxonomicName":  taxon_name,
                "taxonomicName.isNomenclature": "true",
                "taxonomicName.exactMatch":     "true",
            },
        )
        if not html_text:
            return []
        treats   = [(m.group(1).upper(), _html_mod.unescape(m.group(2).strip()))
                    for m in _PLAZI_TREAT_RE.finditer(html_text)]
        articles = [(m.group(1).upper(),
                     _fix_encoding(_html_mod.unescape(
                         re.sub(r'\s+', ' ', m.group(2)).strip())))
                    for m in _PLAZI_ARTICLE_RE.finditer(html_text)]
        results = []
        for i, (t_uuid, taxon) in enumerate(treats):
            a_uuid, citation = articles[i] if i < len(articles) else ("", "")
            results.append({
                "treatment_uuid": t_uuid,
                "taxon_name":     taxon,
                "article_uuid":   a_uuid,
                "citation":       citation,
            })
        return results[:limit]
    except Exception as exc:
        log.warning("[_plazi_ggserver_search] %s → %s", taxon_name, exc)
        return []


def _parse_plazi_xml_full(xml_text: str) -> tuple:
    """Parse Plazi treatment XML; return (descriptions, image_urls, specimens).
    Extends _parse_plazi_xml() by also extracting materialsCitation specimens.
    """
    import defusedxml.ElementTree as ET
    descriptions: list = []
    image_urls:   list = []
    specimens:    list = []
    if not xml_text:
        return descriptions, image_urls, specimens
    if len(xml_text.encode()) > _XML_MAX_BYTES:
        log.warning("[Plazi XML parse full] response exceeds %d bytes, skipping", _XML_MAX_BYTES)
        return descriptions, image_urls, specimens
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError) as exc:
        log.warning("[Plazi XML parse full] %s", exc)
        return descriptions, image_urls, specimens
    for elem in root.iter("subSubSection"):
        if elem.get("type") == "description":
            text = " ".join(" ".join(elem.itertext()).split()).strip()
            if len(text) > 40:
                descriptions.append(text)
    seen: set = set()
    for elem in root.iter("figureCitation"):
        uri = elem.get("httpUri", "").strip()
        if uri and uri not in seen:
            seen.add(uri)
            image_urls.append(uri)
    for elem in root.iter("materialsCitation"):
        specimens.append({
            "typeStatus":      elem.get("typeStatus", ""),
            "institutionCode": elem.get("institutionCode", ""),
            "catalogNumber":   elem.get("catalogNumber", ""),
            "country":         elem.get("country", ""),
            "locality":        (elem.get("location") or
                                elem.get("stateProvince") or ""),
        })
    return descriptions, image_urls, specimens


def get_plazi_all(taxon_name: str, uuid_limit: int = 20,
                  spec_limit: int = 50) -> tuple:
    """Fetch Plazi treatments via GgServer; return descriptions, images, specimens.
    Returns (descriptions, image_urls, specimens) where:
      descriptions : [{"taxon", "uuid", "text"}, ...]
      image_urls   : [str, ...] (deduplicated)
      specimens    : [{"typeStatus", "institutionCode", "catalogNumber",
                       "country", "locality", "taxon"}, ...]
    """
    records = _plazi_ggserver_search(taxon_name, limit=uuid_limit)
    if not records:
        return [], [], []
    all_descs: list = []
    all_imgs:  list = []
    all_specs: list = []
    seen_imgs: set  = set()
    for rec in records:
        uuid     = rec["treatment_uuid"]
        tax_name = rec["taxon_name"]
        xml_text = _safe_get_xml(f"{_PLAZI_XML}/{uuid}")
        descs, imgs, specs = _parse_plazi_xml_full(xml_text)
        for text in descs:
            all_descs.append({"taxon": tax_name, "uuid": uuid, "text": text})
        for url in imgs:
            if url not in seen_imgs:
                seen_imgs.add(url)
                all_imgs.append(url)
        for sp in specs:
            sp["taxon"] = tax_name
            all_specs.append(sp)
    return all_descs, all_imgs, all_specs[:spec_limit]


def get_plazi_keys_full(taxon_name: str, key_limit: int = 20) -> tuple:
    """Fetch Plazi treatments with identification keys via GgServer.
    Returns (key_records, pub_dicts) for the unified publications pool.
    Mirrors get_plazi_keys() in query_databases_sandbox.py.
    """
    search_records = _plazi_ggserver_search(taxon_name, limit=key_limit * 4)
    if not search_records:
        return [], []

    seen_article_uuids: set = set()
    records_to_process = []
    for rec in search_records:
        a_uuid = rec["article_uuid"]
        if a_uuid and a_uuid not in seen_article_uuids:
            seen_article_uuids.add(a_uuid)
            records_to_process.append(rec)
        if len(records_to_process) >= key_limit:
            break

    results:   list = []
    pub_dicts: list = []
    for rec in records_to_process:
        uuid  = rec["article_uuid"]
        entry = {
            "taxon":       rec["taxon_name"],
            "uuid":        uuid,
            "summary_url": f"https://tb.plazi.org/GgServer/summary/{uuid}",
            "title": "", "authors": "", "year": "", "journal": "", "doi": "",
        }
        meta = _fetch_plazi_summary_html(uuid)
        if meta:
            entry.update({k: meta[k] for k in
                          ("title", "authors", "year", "journal", "doi", "summary_url")})
        results.append(entry)

        doi   = _normalize_doi(entry["doi"])
        title = entry["title"]
        csl   = None
        if title:
            csl = {"id": doi or uuid, "type": "article-journal", "title": title}
            if doi:
                csl["DOI"] = doi
            if entry["year"]:
                try:
                    csl["issued"] = {"date-parts": [[int(entry["year"])]]}
                except ValueError:
                    pass
            if entry["authors"]:
                csl["author"] = [{"literal": entry["authors"]}]
        if doi or title:
            pub_dicts.append({
                "doi": doi, "title": title, "csl": csl,
                "raw_citation": None, "sources": ["Plazi"],
                "plazi_url": entry["summary_url"],
            })
    return results, pub_dicts


# ============================================================
# BHL — ENRICHED (GetTitleMetadata + Wikidata chain)
# ============================================================

_BHL_KEY_DEFAULT = ""


def _bhl_get(params: dict, api_key: str, timeout: int = 20) -> dict:
    """GET a BHL API endpoint; return parsed JSON or {}."""
    try:
        r = _get_with_retry(_BHL_API, params={**params, "apikey": api_key,
                                              "format": "json"},
                            headers=_headers(), timeout=timeout)
        return r.json()
    except Exception as exc:
        log.warning("[BHL] %s → %s", params.get("op"), _redact_query(exc))
        return {}


def fetch_bhl_enriched(name: str, api_key: str = "",
                        max_titles: int = 20, max_pages: int = 10) -> tuple:
    """Fetch BHL with GetTitleMetadata + Wikidata enrichment.
    Returns (publications, pages) where publications include place/dates/author_str.
    Mirrors get_bhl_records() in query_databases_sandbox.py.
    """
    bhl_key = api_key or _BHL_KEY_DEFAULT
    try:
        data       = _bhl_get({"op": "GetNameMetadata", "name": name}, bhl_key)
        results    = data.get("Result", [])
        if not results or not isinstance(results, list):
            return [], []

        result     = results[0] if isinstance(results[0], dict) else {}
        titles_raw = result.get("Titles", []) or []
        publications: list = []
        pages:        list = []

        for title_rec in titles_raw:
            if len(publications) >= max_titles:
                break
            title_id         = str(title_rec.get("TitleID", "") or "")
            title_url        = title_rec.get("TitleUrl", "")
            bibliography_url = (f"https://www.biodiversitylibrary.org/bibliography/{title_id}"
                                if title_id else "")

            full_title   = ""
            wikidata_qid = ""
            if title_id:
                tmeta_data = _bhl_get({"op": "GetTitleMetadata", "id": title_id,
                                       "items": "f"}, bhl_key)
                tmeta_results = tmeta_data.get("Result") or []
                tmeta_rec     = next((x for x in tmeta_results
                                      if isinstance(x, dict)), {})
                full_title    = (tmeta_rec.get("FullTitle") or
                                 tmeta_rec.get("ShortTitle") or "").strip()
                for ident in (tmeta_rec.get("Identifiers") or []):
                    if (isinstance(ident, dict) and
                            ident.get("IdentifierName") == "Wikidata"):
                        wikidata_qid = (ident.get("IdentifierValue") or "").strip()
                        break

            place = start_year = end_year = author_str = ""
            if wikidata_qid:
                wd = _wikidata_title_meta(wikidata_qid)
                if not full_title:
                    full_title = wd.get("title", "")
                place      = wd.get("place", "")
                start_year = wd.get("start_year", "")
                end_year   = wd.get("end_year", "")
                author_str = wd.get("author_str", "")

            publications.append({
                "title":            full_title,
                "year":             start_year,
                "start_year":       start_year,
                "end_year":         end_year,
                "place":            place,
                "author_str":       author_str,
                "url":              title_url,
                "bibliography_url": bibliography_url,
                "wikidata_qid":     wikidata_qid,
            })

            for item in (title_rec.get("Items") or []):
                for page in (item.get("Pages") or []):
                    if len(pages) >= max_pages:
                        break
                    pages.append({
                        "title":    full_title,
                        "page_id":  str(page.get("PageID", "") or ""),
                        "page_url": page.get("PageUrl", ""),
                        "year":     str(page.get("Year", "") or ""),
                    })
                if len(pages) >= max_pages:
                    break
            if len(pages) >= max_pages:
                break

        return publications, pages
    except Exception as exc:
        log.warning("[fetch_bhl_enriched] %s → %s", name, exc)
        return [], []


def get_bhl_pub_dicts(page_ids: list, api_key: str = "") -> list:
    """Fetch BHL GetPageMetadata for article-level pub dicts.
    Returns list of publication dicts for resolve_publications.
    Mirrors get_bhl_pub_dicts() in query_databases_sandbox.py.
    """
    bhl_key       = api_key or _BHL_KEY_DEFAULT
    pub_dicts:    list = []
    seen_part_ids: set = set()
    for page_id in page_ids:
        if not page_id:
            continue
        try:
            data        = _bhl_get({"op": "GetPageMetadata", "pageid": page_id,
                                    "ocr": "f", "names": "f"}, bhl_key)
            result_list = data.get("Result", [])
            if not result_list or not isinstance(result_list, list):
                continue
            page_data = result_list[0] if isinstance(result_list[0], dict) else {}
            for part in (page_data.get("Parts") or []):
                part_id = str(part.get("PartID", "") or "")
                if part_id in seen_part_ids:
                    continue
                seen_part_ids.add(part_id)
                doi      = _normalize_doi(part.get("Doi") or part.get("DOI") or "")
                title    = (part.get("Title") or "").strip()
                container = (part.get("ContainerTitle") or "").strip()
                volume   = str(part.get("Volume") or "")
                issue    = str(part.get("Issue") or "")
                pages    = (part.get("PageRange") or "").strip()
                year_raw = str(part.get("Date") or "")
                yr_m     = re.search(r'\b(\d{4})\b', year_raw)
                year     = int(yr_m.group(1)) if yr_m else None
                csl_authors = []
                for a in (part.get("Authors") or []):
                    entry = {}
                    if a.get("LastName"):  entry["family"] = a["LastName"]
                    if a.get("FirstName"): entry["given"]  = a["FirstName"]
                    if not entry and a.get("Name"): entry["literal"] = a["Name"]
                    if entry: csl_authors.append(entry)
                csl = None
                if title:
                    csl = {"id":   doi or part_id or title[:20],
                           "type": "article-journal", "title": title}
                    if doi: csl["DOI"] = doi
                    if year: csl["issued"] = {"date-parts": [[year]]}
                    if csl_authors: csl["author"] = csl_authors
                    if container: csl["container-title"] = container
                    for k, v in [("volume", volume), ("issue", issue), ("page", pages)]:
                        if v: csl[k] = v
                if doi or title:
                    pub_dicts.append({
                        "doi": doi, "title": title, "csl": csl,
                        "raw_citation": None, "sources": ["BHL"],
                    })
        except Exception as exc:
            log.warning("[get_bhl_pub_dicts] page %s → %s", page_id, exc)
    return pub_dicts


# ============================================================
# PUBLICATIONS RESOLUTION PIPELINE
# ============================================================

def resolve_publications(all_pubs: list) -> tuple:
    """Deduplicate and APA-format all publications from all sources.

    Each entry in all_pubs: {"doi", "title", "csl", "raw_citation", "sources"}.
    Resolution: CSL direct → CrossRef DOI → CrossRef title → CrossRef bib → background.
    Dedup: normalized DOI first, then 60-char alphanum title key.
    Returns (formatted_list, background_list) sorted chronologically.
    """
    formatted: list  = []
    background: list = []
    seen_dois:   dict = {}
    seen_titles: dict = {}

    for pub in all_pubs:
        doi       = _normalize_doi(pub.get("doi") or "")
        title     = pub.get("title") or ""
        csl       = pub.get("csl")
        raw       = pub.get("raw_citation") or ""
        sources   = list(pub.get("sources") or [])
        title_key = _normalize_title_key(title)
        plazi_url = pub.get("plazi_url") or ""

        # ── Deduplication ──
        if doi and doi in seen_dois:
            idx = seen_dois[doi]
            formatted[idx]["sources"] = list(dict.fromkeys(
                formatted[idx]["sources"] + sources))
            if plazi_url and not formatted[idx].get("plazi_url"):
                formatted[idx]["plazi_url"] = plazi_url
            continue
        if title_key and title_key in seen_titles:
            idx = seen_titles[title_key]
            existing = formatted[idx]
            existing["sources"] = list(dict.fromkeys(
                existing["sources"] + sources))
            if doi and not existing["doi"]:
                existing["doi"] = doi
                seen_dois[doi]  = idx
            if plazi_url and not existing.get("plazi_url"):
                existing["plazi_url"] = plazi_url
            continue

        # ── Resolution ──
        citation_str = ""
        resolved_doi = doi

        if (csl and csl.get("author")
                and (csl.get("issued") or csl.get("year"))
                and csl.get("title")):
            citation_str = _format_apa(csl)

        if not citation_str and doi:
            cr_csl = _crossref_fetch_csl(doi)
            if cr_csl:
                citation_str = _format_apa(cr_csl)
                if cr_csl.get("DOI"):
                    resolved_doi = _normalize_doi(cr_csl["DOI"])

        if not citation_str and title:
            found_doi = _crossref_title_search_doi(title)
            if found_doi and found_doi not in seen_dois:
                cr_csl = _crossref_fetch_csl(found_doi)
                if cr_csl:
                    resolved_doi = found_doi
                    citation_str = _format_apa(cr_csl)

        if not citation_str:
            if not raw:
                continue
            # Use the raw citation string as-is — no CrossRef guessing.
            # This guarantees nothing is suppressed; DOI-based lookups above
            # already handle APA formatting where structured metadata is available.
            citation_str = raw

        pub_year = None
        yr_m = re.search(r'\((\d{4})\)', citation_str)
        if yr_m:
            pub_year = int(yr_m.group(1))

        idx = len(formatted)
        formatted.append({
            "citation":  citation_str,
            "doi":       resolved_doi,
            "sources":   sources,
            "plazi_url": plazi_url,
            "year":      pub_year,
        })
        if resolved_doi:
            seen_dois[resolved_doi] = idx
        tk = _normalize_title_key(csl.get("title") if csl else title)
        if tk:
            seen_titles[tk] = idx

    formatted.sort(key=lambda p: (p.get("year") or 9999, p.get("citation", "")))
    return formatted, background


# ============================================================
# WIKIPEDIA LLM SUMMARIZATION (Groq)
# ============================================================

def summarize_wikipedia_llm(wiki_report: dict, taxon_name: str,
                             api_key: str, model: str) -> tuple:
    """Summarize Wikipedia article for a taxon using Groq LLM.
    Returns (description_str, summary_str). Either may be "" on failure.
    Mirrors summarize_wikipedia() in query_databases_sandbox.py.
    """
    if not wiki_report.get("found") or not api_key:
        return "", ""

    parts = []
    if wiki_report.get("extract"):
        parts.append(wiki_report["extract"])
    for sec in wiki_report.get("sections", []):
        parts.append(f"\n\n=== {sec['heading']} ===\n{sec['text']}")
    full_text = "\n".join(parts).strip()
    if not full_text:
        return "", ""

    system_prompt = (
        "You are a taxonomic assistant summarising Wikipedia content for a "
        "professional taxonomist. Be concise and factual. Use scientific names "
        "where appropriate. Do not speculate beyond the source material."
    )
    user_prompt = (
        f"Summarise the following Wikipedia article about {taxon_name} for a "
        "taxonomist. Structure your response using exactly these two labels:\n\n"
        "DESCRIPTION:\n"
        "One concise paragraph covering the morphological description of the taxon "
        "(body size, colouration, key anatomical features). If the article contains "
        "no morphological detail, write 'No morphological description available.'\n\n"
        "SUMMARY:\n"
        "3-5 concise paragraphs covering: taxonomic history, geographic range, "
        "ecology, economic/medical significance, notable species, conservation status "
        "(only topics present in the article). Do not reproduce verbatim.\n\n"
        f"ARTICLE:\n{full_text[:15000]}"
    )
    try:
        import requests as _req
        r = _req.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": model or "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                "temperature": 0.2,
            },
            timeout=60,
        )
        raw = r.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.warning("[summarize_wikipedia_llm] %s → %s", taxon_name, exc)
        return "", ""

    if "SUMMARY:" in raw:
        desc_block, summ_block = raw.split("SUMMARY:", 1)
        description = desc_block.replace("DESCRIPTION:", "").strip()
        summary     = summ_block.strip()
    else:
        description = ""
        summary     = raw.replace("DESCRIPTION:", "").strip()

    return description, summary


# ============================================================
# SANDBOX-COMPATIBLE HELPERS AND ALIASES
# The functions and constants below are provided so that
# query_databases_sandbox.py can import everything it needs
# from this module rather than defining them locally.
# ============================================================

import requests as _requests_mod
import defusedxml.ElementTree as _ET_mod

# ── API base URLs (re-exported for sandbox use) ──────────────────────────────
GBIF_API      = "https://api.gbif.org/v1"
GBIF_BACKBONE = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"
NCBI_ESEARCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
ITIS_BASE     = "https://www.itis.gov/ITISWebService/jsonservice"
CROSSREF_API  = "https://api.crossref.org/works"
ZOOBANK_API   = "https://zoobank.org"
COL_API       = "https://api.checklistbank.org"
COL_DATASET   = "3"
PLAZI_API     = "https://api.plazi.org/v1"
PLAZI_XML     = "https://tb.plazi.org/GgServer/xml"
BHL_API       = "https://www.biodiversitylibrary.org/api3"
BHL_KEY       = ""
WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData"

# ── Limit constants (re-exported for sandbox use) ────────────────────────────
GBIF_CHILDREN_LIMIT = 300
GBIF_LIT_LIMIT      = 100
GBIF_IMG_LIMIT      = 20
GBIF_SPEC_LIMIT     = 100
COL_SYN_LIMIT       = 30
NCBI_ACC_LIMIT      = 50
PLAZI_UUID_LIMIT    = 20
PLAZI_SPEC_LIMIT    = 50
PLAZI_KEY_LIMIT     = 20
BHL_MAX_TITLES      = 20
BHL_MAX_PAGES       = 10

# ── Rank helpers (re-exported for sandbox use) ────────────────────────────────
_RANK_PLURAL = {
    "KINGDOM":    "kingdoms",   "PHYLUM":     "phyla",
    "CLASS":      "classes",    "ORDER":      "orders",
    "FAMILY":     "families",   "SUBFAMILY":  "subfamilies",
    "TRIBE":      "tribes",     "GENUS":      "genera",
    "SUBGENUS":   "subgenera",  "SPECIES":    "species",
    "SUBSPECIES": "subspecies", "VARIETY":    "varieties",
    "FORM":       "forms",
}


def safe_get(url, params=None, silent_404=False, headers=None, timeout=15):
    """Simple GET helper that returns parsed JSON or {}.
    Matches the interface used by query_databases_sandbox.py.
    """
    try:
        response = _requests_mod.get(
            url, params=params, timeout=timeout, headers=headers)
        if response.status_code == 200:
            return response.json()
        if response.status_code == 404 and silent_404:
            return {}
        log.warning("HTTP %s from %s", response.status_code, url)
    except Exception as exc:
        log.warning("Request failed (%s): %s", url, exc)
    return {}


def safe_get_xml(url, params=None, timeout=20):
    """Like safe_get() but returns raw response text (for XML or HTML endpoints)."""
    try:
        response = _requests_mod.get(url, params=params, timeout=timeout)
        if response.status_code == 200:
            return response.text
        log.warning("HTTP %s from %s", response.status_code, url)
    except Exception as exc:
        log.warning("Request failed (%s): %s", url, exc)
    return ""


# ── Function aliases matching sandbox names ───────────────────────────────────

# resolve_gbif_backbone in the sandbox returns the rich form (authorship,
# hierarchy, publishedIn, numDescendants, parent) that resolve_gbif_backbone_rich
# provides.  The lightweight resolve_gbif_backbone already defined above is the
# INFO-report version; here we shadow it for the sandbox import surface.
resolve_gbif_backbone = resolve_gbif_backbone_rich


def get_gbif_images(usage_key):
    """Alias for sandbox compatibility. Returns plain image URL list."""
    return fetch_gbif_image_urls(usage_key, max_results=GBIF_IMG_LIMIT)


def get_gbif_children(usage_key, taxon_rank=""):
    """Alias for sandbox compatibility."""
    return fetch_gbif_children(usage_key, rank=taxon_rank)


def get_gbif_publications(usage_key):
    """Alias for sandbox compatibility."""
    return fetch_gbif_pub_dicts(usage_key, limit=GBIF_LIT_LIMIT)


def get_gbif_synonyms(usage_key):
    """Alias for sandbox compatibility."""
    return fetch_gbif_synonyms(usage_key)


def get_gbif_specimens(usage_key):
    """Alias for sandbox compatibility."""
    return fetch_gbif_specimens(usage_key, max_results=GBIF_SPEC_LIMIT)


def get_gbif_references(usage_key):
    """Alias for sandbox compatibility."""
    return fetch_gbif_references(usage_key)


def get_gbif_species_profiles(usage_key):
    """Alias for sandbox compatibility."""
    return fetch_gbif_species_profiles(usage_key)


def get_itis_records(tsn, name):
    """Alias for sandbox compatibility. Returns (resolved_tsn | None, summary_str)."""
    return fetch_itis_summary(tsn, name)


def _zoobank_act_detail(guid, headers):
    """Fetch a single ZooBank act by GUID; return the first record dict or {}."""
    data = safe_get(f"{ZOOBANK_API}/NomenclaturalActs.json/{guid}", headers=headers)
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {}
    return data if isinstance(data, dict) else {}


def _zoobank_fetch_ref(ref_guid, headers):
    """Fetch a ZooBank reference by GUID; return the full record dict or {}."""
    data = safe_get(f"{ZOOBANK_API}/References.json/{ref_guid}", headers=headers)
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {}
    return data if isinstance(data, dict) else {}


def get_zoobank_records(name):
    """Alias for sandbox compatibility.
    Returns (lsid | None, summary_str, pub_dicts).
    """
    return get_zoobank_full(name)


def get_crossref_records(name):
    """Alias for sandbox compatibility.
    Returns list of publication dicts for the unified publications pool.
    """
    return get_crossref_pub_dicts(name)


def get_col_records(name):
    """Alias for sandbox compatibility.
    Returns (accepted_name | None, synonyms_list, summary_str, pub_dicts).
    """
    return get_col_full(name)


def _parse_plazi_xml(xml_text):
    """Alias for sandbox compatibility (sandbox version returns 3-tuple).
    Calls _parse_plazi_xml_full which returns (descriptions, image_urls, specimens).
    """
    return _parse_plazi_xml_full(xml_text)


def get_plazi_treatments(taxon_name):
    """Alias for sandbox compatibility.
    Returns (descriptions, image_urls, specimens).
    """
    return get_plazi_all(taxon_name,
                         uuid_limit=PLAZI_UUID_LIMIT,
                         spec_limit=PLAZI_SPEC_LIMIT)


def _fetch_plazi_summary(uuid):
    """Alias for sandbox compatibility."""
    return _fetch_plazi_summary_html(uuid)


def get_plazi_keys(taxon_name):
    """Alias for sandbox compatibility.
    Returns (key_records, pub_dicts).
    """
    return get_plazi_keys_full(taxon_name, key_limit=PLAZI_KEY_LIMIT)


def get_bhl_records(taxon_name):
    """Alias for sandbox compatibility.
    Returns (publications, pages) with Wikidata enrichment.
    """
    return fetch_bhl_enriched(taxon_name, api_key=BHL_KEY,
                               max_titles=BHL_MAX_TITLES, max_pages=BHL_MAX_PAGES)


