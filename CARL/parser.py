"""
NEXUS parser for TaxonGPT.

Responsibilities:
- Parse CHARSTATELABELS into Character objects
- Parse MATRIX into Taxon objects
- Parse optional TAXONGPT_CONDITIONS
- Normalize raw state tokens
- Serialise Dataset → NEXUS DATA block (generate_data_block)
- Assemble complete NEXUS file content (build_nexus_content)
- Atomic file write (write_nexus_atomic)
"""

import os
import re
import tempfile
from collections import OrderedDict
from data_model import Dataset, Character, Taxon, Condition

MISSING = "M"
NOT_APPLICABLE = "N"


# -----------------------------
# STATE PARSING
# -----------------------------

def parse_state(token):
    """
    Convert a raw token into a standardized state representation.

    Returns:
    - "M" (missing)
    - "N" (not applicable)
    - set(...) for polymorphic states  e.g. (0,1) → {0, 1}
    - raw token otherwise
    """
    token = token.strip()

    if token in ["?", MISSING]:
        return MISSING
    if token == NOT_APPLICABLE:
        return NOT_APPLICABLE

    if token.startswith("(") and token.endswith(")"):
        return set(v.strip() for v in token[1:-1].split(","))

    return token


# -----------------------------
# CHARSTATELABELS PARSER
# -----------------------------
def parse_charstatelabels(lines):
    """
    Strict-mode parser for CHARSTATELABELS.

    Supports hierarchical character names.
    """

    characters = []
    current_block = []

    def flush_block(block_lines):
        if not block_lines:
            return None

        full_text = " ".join(block_lines).strip()

        # Split index, char part, states part
        match = re.match(r'^(\d+)\s+(.+?)\s*/\s*(.+)$', full_text)
        if not match:
            raise ValueError(f"Invalid CHARSTATELABELS entry: {full_text}")

        index = int(match.group(1)) - 1
        char_part = match.group(2).strip()
        states_part = match.group(3).strip()

        # Extract hierarchical character names — double-quoted, single-quoted, or unquoted
        char_names = re.findall(r'"([^"]+)"', char_part)
        if not char_names:
            char_names = re.findall(r"'([^']+)'", char_part)
        if not char_names:
            char_names = [char_part]  # whole char_part is the name

        # Extract states — double-quoted, single-quoted, or unquoted
        state_matches = re.findall(r'(\d+)\s+"([^"]+)"', states_part)
        if not state_matches:
            state_matches = re.findall(r"(\d+)\s+'([^']+)'", states_part)
        if not state_matches:
            # Unquoted: split on integer IDs at word boundaries
            pieces = re.split(r'\b(\d+)\s+', states_part)
            state_matches = [
                (pieces[i], pieces[i + 1].strip())
                for i in range(1, len(pieces) - 1, 2)
                if i + 1 < len(pieces) and pieces[i + 1].strip()
            ]

        if not state_matches:
            raise ValueError(f"No valid state labels found: {full_text}")

        states = {sid: label for sid, label in state_matches}
        return Character(index, char_names, states)

    # ----------------------------
    # MAIN LOOP (THIS WAS MISSING)
    # ----------------------------
    for line in lines:
        line = line.strip()

        if not line:
            continue

        # Remove trailing commas
        if line.endswith(","):
            line = line[:-1]

        # Detect new character block
        if re.match(r'^\d+\s', line):
            # Flush previous block
            if current_block:
                char = flush_block(current_block)
                if char:
                    characters.append(char)
                current_block = []

        current_block.append(line)

    # Flush last block
    if current_block:
        char = flush_block(current_block)
        if char:
            characters.append(char)

    return characters
# -----------------------------
# CONDITIONS PARSER
# -----------------------------

def parse_conditions(block, dataset):
    """Parse custom TAXONGPT_CONDITIONS block."""
    for line in block:
        parts = line.strip().split()
        if not parts:
            continue

        char_idx = int(parts[0]) - 1
        depends_on = int(parts[2]) - 1
        states = parts[4].split(",")

        dataset.characters[char_idx].condition = Condition(depends_on, states)


# -----------------------------
# MATRIX PARSER
# -----------------------------

def parse_matrix(lines, dataset):
    """Parse MATRIX block into Taxon objects."""

    for line in lines:
        line = line.strip()

        # detect block terminator BEFORE stripping
        if line == ";" or line.upper().startswith("END"):
            continue

        # remove trailing semicolons from data lines
        line = line.rstrip(";")

        if not line:
            continue

        parts = line.split()

        # guard against malformed lines
        if len(parts) < 2:
            continue

        taxon = Taxon(parts[0])

        for i, token in enumerate(parts[1:]):
            taxon.states[i] = parse_state(token)

        dataset.taxa.append(taxon)



# -----------------------------
# MAIN PARSER
# -----------------------------

def parse_nexus(filepath):
    """Parse a NEXUS file into a Dataset object."""

    dataset = Dataset()

    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()

    charlabel_lines = []
    matrix_lines = []
    condition_lines = []

    in_charlabels = False
    in_matrix = False
    in_conditions = False

    for line in lines:
        l = line.strip()
        upper_l = l.upper()

        # -------------------------
        # CHARSTATELABELS block
        # -------------------------
        if upper_l.startswith("CHARSTATELABELS"):
            in_charlabels = True
            continue

        if in_charlabels:
            if ";" in l:
                in_charlabels = False
            charlabel_lines.append(l)
            continue

        # -------------------------
        # TAXONGPT_CONDITIONS block
        # -------------------------
        if "[TAXONGPT_CONDITIONS" in upper_l:
            in_conditions = True
            continue

        if in_conditions:
            if "]" in l:
                in_conditions = False
            else:
                condition_lines.append(l)
            continue

        # -------------------------
        # MATRIX block
        # -------------------------
        if upper_l.startswith("MATRIX"):
            in_matrix = True
            continue

        if in_matrix:
            matrix_lines.append(l)
            if ";" in l:
                in_matrix = False
            continue

    # -------------------------
    # Parse core components
    # -------------------------
    dataset.characters = parse_charstatelabels(charlabel_lines)
    parse_matrix(matrix_lines, dataset)

    if condition_lines:
        parse_conditions(condition_lines, dataset)

    return dataset


# -----------------------------
# UPDATE NEXUS FILE
# -----------------------------
def update_charstatelabels_in_nexus(nexus_text, characters):
    """Replace the CHARSTATELABELS block with current in-memory character names and state labels."""
    entries = []
    for char in characters:
        if isinstance(char.name, list):
            name_part = " ".join(f'"{n}"' for n in char.name)
        else:
            name_part = f'"{char.name}"'
        states_part = " ".join(f'{sid} "{label}"' for sid, label in char.states.items())
        entries.append(f'\t{char.index + 1} {name_part} / {states_part}')

    body = "\n".join(
        line + ("," if i < len(entries) - 1 else "")
        for i, line in enumerate(entries)
    )
    new_block = f"CHARSTATELABELS\n{body}\n\t;"

    pattern = re.compile(r'CHARSTATELABELS\b[^;]*;', re.IGNORECASE)
    if pattern.search(nexus_text):
        return pattern.sub(new_block, nexus_text)
    return nexus_text  # block not found — leave file untouched


# -----------------------------
# FULL-FILE SERIALIZERS
# -----------------------------

def generate_data_block(dataset) -> str:
    """Serialise a Dataset to a complete NEXUS DATA block string."""
    if not dataset:
        return ""
    taxa  = dataset.taxa
    chars = dataset.characters
    if not taxa and not chars:
        return ""
    ntax  = len(taxa)
    nchar = len(chars)
    lines = [
        "BEGIN DATA;",
        f"DIMENSIONS NTAX={ntax} NCHAR={nchar};",
        "FORMAT DATATYPE=STANDARD MISSING=M GAP=-;",
        "CHARSTATELABELS",
    ]
    for i, char in enumerate(chars):
        if isinstance(char.name, list):
            name_part = " ".join(f'"{n}"' for n in char.name)
        else:
            name_part = f'"{char.name}"'
        states_part = " ".join(
            f'{sid} "{label}"' for sid, label in char.states.items()
        )
        comma = "," if i < nchar - 1 else ""
        lines.append(f"\t{char.index + 1} {name_part} / {states_part}{comma}")
    lines.append(";")
    lines.append("MATRIX")
    for taxon in taxa:
        tokens = []
        for char in chars:
            raw = taxon.states.get(char.index)
            if raw is None or raw == "M":
                tokens.append("M")
            elif raw == "N":
                tokens.append("N")
            elif isinstance(raw, set):
                tokens.append("(" + ",".join(sorted(raw)) + ")")
            else:
                tokens.append(str(raw))
        lines.append(f"{taxon.name}\t{' '.join(tokens)}")
    lines.append(";")
    lines.append("END;")
    return "\n".join(lines)


def build_nexus_content(dataset, carl_block, existing_content=None,
                        update_data=True) -> str:
    """
    Assemble NEXUS file content, touching only the blocks CARL owns.

    - CARL block: always replaced in place (or appended). Preclusion lines
      ('N(S) precludes ...') are carried over verbatim.
    - DATA block: regenerated only when ``update_data`` is True (i.e. there are
      pending matrix edits); otherwise left byte-for-byte.
    - SETS, ASSUMPTIONS, TREES and any third-party blocks: preserved verbatim.

    With existing_content=None a minimal file (DATA + CARL) is built from scratch.
    """
    from carl_parser import serialize_carl_block
    carl_text = (serialize_carl_block(carl_block, existing_content or "")
                 if (carl_block and carl_block.entities) else "")

    # --- New file from scratch ---
    if existing_content is None:
        parts = ["#NEXUS"]
        data_block = generate_data_block(dataset)
        if data_block:
            parts.append(data_block)
        if carl_text:
            parts.append(carl_text)
        return "\n\n".join(parts) + "\n"

    # --- Surgical update of an existing file ---
    text = existing_content

    # DATA block — only when data actually changed.
    if update_data:
        new_data = generate_data_block(dataset)
        if new_data:
            data_pat = re.compile(r'BEGIN\s+DATA\s*;.*?END\s*;',
                                  re.DOTALL | re.IGNORECASE)
            if data_pat.search(text):
                text = data_pat.sub(lambda _m: new_data, text, count=1)
            else:  # no DATA block yet — insert just after the #NEXUS header
                text = re.sub(r'(#NEXUS[^\n]*\n)',
                              lambda m: m.group(1) + "\n" + new_data + "\n",
                              text, count=1, flags=re.IGNORECASE)

    # CARL block — replace in place, append if absent, or remove if empty.
    carl_pat = re.compile(r'\n*BEGIN\s+CARL\s*;.*?END\s*;',
                          re.DOTALL | re.IGNORECASE)
    if carl_text:
        if carl_pat.search(text):
            text = carl_pat.sub(lambda _m: "\n\n" + carl_text, text, count=1)
        else:
            text = text.rstrip() + "\n\n" + carl_text + "\n"
    else:
        text = carl_pat.sub("", text)

    return text if text.endswith("\n") else text + "\n"


def write_nexus_atomic(path: str, content: str) -> None:
    """Write content to path atomically via a temp file. Raises OSError on failure."""
    dir_ = os.path.dirname(os.path.abspath(path))
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                dir=dir_, suffix=".tmp", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        os.replace(tmp_path, path)
    except OSError:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


_CHARSET_LINE = re.compile(
    r'^[ \t]*CHARSET\s+"?([^"=;\n]+?)"?\s*=\s*([\d \t\-]+)',
    re.IGNORECASE | re.MULTILINE
)


def parse_charsets(nexus_text: str) -> OrderedDict:
    """Parse CHARSET statements from the SETS block.

    Returns an OrderedDict mapping label → [0-based char indices], preserving
    declaration order.  Characters listed in multiple CHARSETs are assigned to
    the first one (first-wins).  Returns an empty OrderedDict when no SETS block
    or no CHARSET statements are present.
    """
    sets_m = re.search(r'BEGIN\s+SETS\s*;(.*?)END\s*;', nexus_text,
                       re.IGNORECASE | re.DOTALL)
    if not sets_m:
        return OrderedDict()

    result = OrderedDict()
    claimed: set = set()

    for m in _CHARSET_LINE.finditer(sets_m.group(1)):
        label    = m.group(1).strip()
        tok_str  = re.sub(r'\s*-\s*', '-', m.group(2).strip())
        indices  = []
        for tok in tok_str.split():
            tok = tok.strip()
            if not tok:
                continue
            if '-' in tok:
                a, b = tok.split('-', 1)
                for i in range(int(a) - 1, int(b)):
                    if i not in claimed:
                        indices.append(i)
                        claimed.add(i)
            else:
                i = int(tok) - 1
                if i not in claimed:
                    indices.append(i)
                    claimed.add(i)
        if indices:
            result[label] = indices

    return result

