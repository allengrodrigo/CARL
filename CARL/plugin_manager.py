"""
plugin_manager.py
Descriptor I/O and validation for the CARL Plugins panel.
No Tkinter dependency — pure data layer.
"""

import json
import os

SCHEMA_VERSION = "1.0"

VALID_TYPES        = {"boolean", "string", "integer", "float", "choice", "file", "outfile", "directory"}
VALID_DISPLAY_MODES = {"terminal", "file", "both"}
VALID_OUTPUT_TYPES  = {"text", "table", "image", "tree", "trace"}

REQUIRED_TOP_LEVEL = ["schema_version", "plugin_id", "name", "executable", "sections"]

# Keys to strip when value is empty / falsy / matches default
_FIELD_DEFAULTS = {
    "required":        False,
    "common":          False,
    "default":         None,
    "value_hint":      "",
    "help":            "",
    "options":         [],
    "mutex_group":     "",
    "condition":       None,
    "multiple":        False,
    "separator":       " ",
    "positional_order": 0,
    "multi_separator": "",
}


# ── public API ─────────────────────────────────────────────────────────────────

def load(path: str) -> dict:
    """Read and parse a descriptor JSON file.  Raises on I/O or parse error."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def validate(descriptor: dict) -> list[str]:
    """Return a list of error strings.  Empty list means the descriptor is valid."""
    errors = []

    for key in REQUIRED_TOP_LEVEL:
        if key not in descriptor:
            errors.append(f"Missing required top-level field: '{key}'")

    sv = descriptor.get("schema_version", "")
    if sv:
        try:
            major = int(str(sv).split(".")[0])
            if major != int(SCHEMA_VERSION.split(".")[0]):
                errors.append(
                    f"Unsupported schema major version '{sv}' "
                    f"(expected {SCHEMA_VERSION.split('.')[0]}.x)"
                )
        except (ValueError, IndexError):
            errors.append(f"schema_version '{sv}' is not a valid MAJOR.MINOR string")

    for sec in descriptor.get("sections", []):
        sec_id = sec.get("id") or sec.get("name") or "(unnamed)"
        if not sec.get("fields"):
            continue
        for f in sec["fields"]:
            ftype = f.get("type", "")
            if ftype not in VALID_TYPES:
                errors.append(
                    f"Section '{sec_id}', flag '{f.get('flag', '?')}': "
                    f"unknown type '{ftype}'"
                )
            if ftype == "choice" and not f.get("options"):
                errors.append(
                    f"Section '{sec_id}', flag '{f.get('flag', '?')}': "
                    f"type 'choice' requires a non-empty 'options' list"
                )
            flag = f.get("flag", "")
            po   = f.get("positional_order", 0)
            if not flag and not po:
                errors.append(
                    f"Section '{sec_id}', label '{f.get('label', '?')}': "
                    f"positional field (flag='') must have positional_order >= 1"
                )

    dm = descriptor.get("output", {}).get("display_mode", "")
    if dm and dm not in VALID_DISPLAY_MODES:
        errors.append(f"output.display_mode '{dm}' is not one of {sorted(VALID_DISPLAY_MODES)}")

    for i, fe in enumerate(descriptor.get("output", {}).get("files", [])):
        ot = fe.get("output_type", "")
        if ot and ot not in VALID_OUTPUT_TYPES:
            errors.append(
                f"output.files[{i}] pattern '{fe.get('pattern','?')}': "
                f"unknown output_type '{ot}' (expected one of {sorted(VALID_OUTPUT_TYPES)})"
            )

    return errors


def save(descriptor: dict, path: str) -> None:
    """Serialise descriptor to path, stripping empty/default keys."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    cleaned = _clean_descriptor(descriptor)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cleaned, fh, indent=2, ensure_ascii=False)


# ── internal helpers ───────────────────────────────────────────────────────────

def _clean_descriptor(d: dict) -> dict:
    """Return a copy of the descriptor with empty/default-value keys stripped."""
    out = {}

    for key in ["schema_version", "plugin_id", "name", "executable"]:
        if d.get(key, "") != "":
            out[key] = d[key]

    alts = [a for a in d.get("alt_executables", []) if a]
    if alts:
        out["alt_executables"] = alts

    for key in ["description", "homepage", "citation", "license", "min_version"]:
        val = d.get(key, "")
        if val:
            out[key] = val

    cleaned_secs = []
    for sec in d.get("sections", []):
        cleaned_fields = [_clean_field(f) for f in sec.get("fields", [])]
        cleaned_fields = [f for f in cleaned_fields if f]
        if cleaned_fields or sec.get("id") or sec.get("name"):
            cs = {}
            if sec.get("id"):   cs["id"]   = sec["id"]
            if sec.get("name"): cs["name"] = sec["name"]
            cs["fields"] = cleaned_fields
            cleaned_secs.append(cs)
    if cleaned_secs:
        out["sections"] = cleaned_secs

    raw_out = d.get("output", {})
    clean_out = {}
    dm = raw_out.get("display_mode", "")
    if dm:
        clean_out["display_mode"] = dm
    sf = raw_out.get("stdout_file", "")
    if sf:
        clean_out["stdout_file"] = sf
    files = []
    for fe in raw_out.get("files", []):
        if not fe.get("pattern"):
            continue
        cfe = {"pattern": fe["pattern"]}
        ot = fe.get("output_type", "")
        if ot:
            cfe["output_type"] = ot
        desc = fe.get("description", "")
        if desc:
            cfe["description"] = desc
        files.append(cfe)
    if files:
        clean_out["files"] = files
    if clean_out:
        out["output"] = clean_out

    return out


def _clean_field(f: dict) -> dict | None:
    if not f:
        return None
    out = {}
    for key in ["flag", "label", "type"]:
        if f.get(key, "") != "":
            out[key] = f[key]
        elif key == "flag":
            out["flag"] = ""  # empty string is valid for positionals
    for key, default in _FIELD_DEFAULTS.items():
        val = f.get(key, default)
        if val != default and val not in (None, "", [], {}):
            out[key] = val
    return out if out else None
