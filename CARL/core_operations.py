"""
core_operations.py

Deterministic analytical operations for TaxonGPT.

This module provides functionality for:
- Knowledge graph construction
- Taxon selection
- Taxon comparison
- Description generation
- Identification of distinguishing features

The module is intentionally free of:
- LLM-related logic
- Semantic interpretation
- Legacy or deprecated functionality
"""

from typing import List, Dict, Union, Optional
from data_model import Dataset, Taxon, Character
from group_operations import resolve_selection
from description_generator import build_base_description

# ============================================================
# TAXON RETRIEVAL
# ============================================================

def select_taxa(dataset: Dataset, names: Optional[List[str]] = None) -> List[Taxon]:
    """
    Return a subset of taxa by name.

    Parameters
    ----------
    dataset : Dataset
        The dataset containing taxa.
    names : list[str] or None
        List of taxon names. If None, all taxa are returned.

    Returns
    -------
    list[Taxon]
        Matching Taxon objects.
    """
    if not names:
        return list(dataset.taxa)

    name_set = set(names)
    return [t for t in dataset.taxa if t.name in name_set]


def insert_into_hierarchy(tree, path, state):
    """
    Insert a character state into a nested dictionary based on a path.

    Parameters
    ----------
    tree : dict
        The current hierarchy
    path : list[str]
        Character path (e.g. ["A", "B", "C"])
    state : str
        State value
    """
    node = tree

    for i, level in enumerate(path):
        if level not in node:
            node[level] = {"_state": None, "_children": {}}

        if i == len(path) - 1:
            # Final level → assign state
            node[level]["_state"] = state
        else:
            node = node[level]["_children"]


# ============================================================
# KNOWLEDGE GRAPH
# ============================================================

def build_knowledge_graph(dataset: Dataset) -> Dict[str, Dict]:
    """
    Build the knowledge graph from the dataset.
    
    M = Missing/Unknown data - stored as "M" for display as "Unknown" in compare_taxa
    N = Not Applicable - stored as "N" for display as "Not Applicable" in compare_taxa
    """
    kg = {}

    for taxon in dataset.taxa:
        char_map = {}

        for char in dataset.characters:
            raw_state = taxon.states.get(char.index)

            if isinstance(raw_state, set):
                labels = [char.states.get(s, str(s)) for s in raw_state]
                state_str = _format_polymorphic_states(labels)
            elif raw_state == "M":
                state_str = "M"  # Store M explicitly for compare_taxa to show as "Unknown"
            elif raw_state == "N":
                state_str = "N"  # Store N explicitly for compare_taxa to show as "Not Applicable"
            else:
                state_str = char.states.get(raw_state, str(raw_state))

            # 🔥 NEW: hierarchical insertion
            if isinstance(char.name, list):
                insert_into_hierarchy(char_map, char.name, state_str)
            else:
                insert_into_hierarchy(char_map, [char.name], state_str)

        kg[taxon.name] = {"Characteristics": char_map}

    return kg

# ============================================================
# COMPARISON
# ============================================================



def _format_polymorphic_states(states: List[str]) -> str:
    """
    Format polymorphic states into a readable string without altering
    the original state labels.
    """
    if not states:
        return ""  # Return empty string for M/N (skip in KG)

    # Remove duplicates while preserving order
    unique_states = list(dict.fromkeys(states))

    if len(unique_states) == 1:
        return unique_states[0]

    if len(unique_states) == 2:
        return f"{unique_states[0]}, or {unique_states[1]}"

    return ", ".join(unique_states[:-1]) + ", or " + unique_states[-1]


def flat_name(char):
    """Return a character's flat (single-level) display name, or ``None`` if its
    name is a multi-level hierarchical path.

    The NEXUS parser wraps every character name in a list, so a non-hierarchical
    ("flat") name arrives as a one-element list (or, from other code paths, a
    plain string). Multi-element lists are genuine hierarchies. Flat names are
    resolved by character index (collision-free); hierarchical names keep the
    knowledge-graph path.
    """
    n = char.name
    if isinstance(n, str):
        return n
    if isinstance(n, list) and len(n) == 1:
        return n[0]
    return None


def state_for(taxon, char):
    """Return the formatted state string for ``taxon``'s cell at ``char.index``,
    or ``None`` if there is no data.

    This resolves state **by character index** (the matrix column), so two
    characters that happen to share the same name still get their own distinct
    states -- unlike the name-keyed knowledge graph, which collapses them.

    Handles both representations found in the app:
      * real taxa store raw state ids / sets / ``"M"`` / ``"N"`` -> formatted here;
      * group (virtual) taxa already store formatted label strings -> passed
        through unchanged.
    """
    raw = taxon.states.get(char.index)
    if raw is None:
        return None
    if raw in ("M", "N"):
        return raw
    if isinstance(raw, set):
        # Match build_knowledge_graph exactly (same order/dedup) so existing
        # non-duplicate output is byte-for-byte unchanged.
        labels = [char.states.get(s, str(s)) for s in raw]
        return _format_polymorphic_states(labels)
    if isinstance(raw, str) and ", or " in raw:
        return raw   # already a formatted polymorphic string (e.g. a group taxon)
    return char.states.get(raw, str(raw))


def get_state_from_kg(kg, taxon_name, path):
    """
    Retrieve a state from the hierarchical KG using a character path.
    """

    if taxon_name not in kg:
        return None

    node = kg[taxon_name]["Characteristics"]

    for i, level in enumerate(path):
        if level not in node:
            return None

        if i == len(path) - 1:
            return node[level].get("_state")

        node = node[level].get("_children", {})

    return None



def _build_comparison_header(
    taxa: List[Taxon],
    dataset: Dataset
) -> str:
    """Generate comparison header including group composition."""
    group_map = dataset.taxon_groups if hasattr(dataset, "taxon_groups") else {}

    labels = []
    for taxon in taxa:
        if taxon.name in group_map:
            members = ", ".join(group_map[taxon.name])
            labels.append(f"{taxon.name} (comprising {members})")
        else:
            labels.append(taxon.name)

    return "COMPARISON: " + " vs ".join(labels)


def compare_taxa(
    dataset: Dataset,
    taxa_input: List[Union[str, Taxon]],
    kg: Dict[str, Dict],
    char_exclusions: set = None
) -> Dict[str, List]:
    """
    Compare taxa or groups using hierarchical KG and dataset ordering.
    """

    if not taxa_input:
        return {
            "header": "",
            "differences": [],
            "similarities": []
        }

    # ----------------------------
    # Resolve taxa or groups
    # ----------------------------
    if isinstance(taxa_input[0], str):
        taxa = resolve_selection(
            dataset,
            dataset.taxon_groups,
            selected_taxa=taxa_input,
            selected_groups=[],
            flatten_groups=False
        )
    else:
        taxa = taxa_input

    # ✅ FIX
    kg = build_temp_kg(dataset, kg, taxa)

    header = _build_comparison_header(taxa, dataset)

    differences = []
    similarities = []

    # ----------------------------
    # Iterate in dataset order
    # ----------------------------
    for char in dataset.characters:
        if char_exclusions and char.index in char_exclusions:
            continue
        path = char.name if isinstance(char.name, list) else [char.name]
        is_flat = flat_name(char) is not None

        entity_states = {}

        # ----------------------------
        # Extract states — by character INDEX for flat names (so identically
        # named characters keep distinct states); via the hierarchical KG for
        # list-valued names.
        # ----------------------------
        for taxon in taxa:
            if is_flat:
                state = state_for(taxon, char)
            else:
                state = get_state_from_kg(kg, taxon.name, path)

            # Differentiate M (Missing/Unknown) vs N (Not Applicable)
            if state == "M" or state is None:
                entity_states[taxon.name] = ["Unknown"]
            elif state == "N":
                entity_states[taxon.name] = ["Not Applicable"]
            else:
                entity_states[taxon.name] = [state]

        # Skip if no valid data
        if not entity_states:
            continue

        # ----------------------------
        # Group taxa by state
        # ----------------------------
        grouped = group_taxa_by_state(
            entity_states,
            _format_polymorphic_states
        )

        # ----------------------------
        # Build entry
        # ----------------------------
        entry = {
            "character_number": char.index + 1,
            "character_name": ", ".join(path),
            "groups": grouped
        }

        # ----------------------------
        # Similarity vs difference
        # ----------------------------
        if len(grouped) == 1:
            similarities.append(entry)
        else:
            differences.append(entry)

    return {
        "header": header,
        "differences": differences,
        "similarities": similarities
    }

def group_taxa_by_state(entity_states, format_polymorphic_states):
    """
    Group taxa (or groups) that share identical state combinations.

    Parameters
    ----------
    entity_states : dict
        Mapping of entity names to lists of state labels.
        Example: {"Hexurella": ["two"], "Atypus": ["one"]}
    format_polymorphic_states : function
        Function used to format polymorphic state labels.

    Returns
    -------
    list of tuples
        List of (taxa_list, state_string) pairs.
    """
    state_to_entities = {}

    for entity, states in entity_states.items():
        state_str = format_polymorphic_states(states)
        state_to_entities.setdefault(state_str, []).append(entity)

    # Sort taxa names within each group for consistency
    grouped = []
    for state_str, entities in state_to_entities.items():
        grouped.append((sorted(entities), state_str))

    # Optional: sort groups alphabetically by taxa names
    grouped.sort(key=lambda x: ", ".join(x[0]))
    return grouped



# ============================================================
# DESCRIPTIONS
# ============================================================
def generate_descriptions(dataset, kg, taxa, build_base_description,
                          char_exclusions=None, char_groups=None):

    lines = []

    if taxa and isinstance(taxa[0], str):
        taxa_objects = select_taxa(dataset, taxa)
    else:
        taxa_objects = taxa

    temp_kg = build_temp_kg(dataset, kg, taxa_objects)

    for t in taxa_objects:
        display_name = t.name.replace("_", " ")
        lines.append(f"DESCRIPTION FOR {display_name}\n")
        desc = build_base_description(t, temp_kg, dataset,
                                      char_exclusions=char_exclusions,
                                      char_groups=char_groups)
        lines.append(desc)
        lines.append("")

    return "\n".join(lines)



def format_comparison(result: dict) -> str:
    """
    Format comparison results into readable text.
    """

    lines = []

    # Header
    if result.get("header"):
        lines.append(result["header"])
        lines.append("")

    # ----------------------------
    # DIFFERENCES
    # ----------------------------
    if result.get("differences"):
        lines.append("DIFFERENCES:")

        for entry in result["differences"]:
            lines.append(f"{entry['character_number']}. {entry['character_name']}:")

            for taxa_list, state in entry["groups"]:
                taxa_str = ", ".join(t.replace("_", " ") for t in taxa_list)
                lines.append(f"  {taxa_str}: {state}")

            lines.append("")

    # ----------------------------
    # SIMILARITIES
    # ----------------------------
    if result.get("similarities"):
        lines.append("SIMILARITIES:")

        for entry in result["similarities"]:
            lines.append(f"{entry['character_number']}. {entry['character_name']}:")

            # Only one group exists for similarities
            _, state = entry["groups"][0]

            lines.append(f"  {state}")
            lines.append("")
    return "\n".join(lines)

#=======================================================
# DISTINGUISHING FEATURES
#=======================================================    
def distinguish_taxa(
    dataset: Dataset,
    taxa_input: List[Union[str, Taxon]],
    kg: Dict[str, Dict],
    top_n: int | None = None,
    char_exclusions: set = None
) -> str:

    result = compare_taxa(dataset, taxa_input, kg, char_exclusions=char_exclusions)

    all_diffs = result.get("differences", [])
    selected_diffs = all_diffs if top_n is None else all_diffs[:top_n]

    lines = ["\nDISTINGUISHING FEATURES:"]

    for entry in selected_diffs:
        char_num = entry["character_number"]
        char_name = entry["character_name"]
        groups = entry["groups"]   # ✅ FIXED

        lines.append(f"{char_num}. {char_name}:")

        for taxa_list, state_str in groups:
            taxa_str = ", ".join(t.replace("_", " ") for t in taxa_list)
            lines.append(f"   - {taxa_str}: {state_str}")

        lines.append("")

    return "\n".join(lines)

# ============================================================
# TEMPORARY KNOWLEDGE GRAPH EXTENSION
# ============================================================
def build_temp_kg(
    dataset: Dataset,
    kg: Dict[str, Dict],
    taxa: List[Taxon]
) -> Dict[str, Dict]:
    """
    Extend KG with virtual taxa (e.g. groups).

    Guarantees:
    - All states are strings ("A", "A, or B", "M", "N")
    - No sets or lists leave this function
    - Nested polymorphism is flattened
    - Nested dicts are deep-copied so mutations in temp_kg never reach self.kg
    """
    import copy
    temp_kg = copy.deepcopy(kg)

    for taxon in taxa:

        # Skip real taxa already in KG
        if taxon.name in temp_kg:
            continue

        char_map = {}

        for char in dataset.characters:
            raw_state = taxon.states.get(char.index)

            if raw_state is None:
                continue

            # -------------------------
            # NORMALISE STATE (STRICT)
            # -------------------------

            # Case 1: M / N
            if raw_state in ("M", "N"):
                state_str = raw_state

            # Case 2: Polymorphic (set)
            elif isinstance(raw_state, set):

                flattened = []

                for s in raw_state:

                    # Already formatted polymorphic string
                    if isinstance(s, str) and ", or " in s:
                        flattened.extend([x.strip() for x in s.split(", or ")])

                    # M / N inside set
                    elif s in ("M", "N"):
                        flattened.append(s)

                    # Raw state ID → label
                    else:
                        flattened.append(char.states.get(s, str(s)))

                # Deduplicate + sort
                unique = sorted(set(flattened))

                if len(unique) == 1:
                    state_str = unique[0]
                else:
                    state_str = _format_polymorphic_states(unique)

            # Case 3: Single state (may already be string)
            else:
                if isinstance(raw_state, str) and ", or " in raw_state:
                    # Already formatted polymorphic string
                    parts = [x.strip() for x in raw_state.split(", or ")]
                    parts = sorted(set(parts))

                    if len(parts) == 1:
                        state_str = parts[0]
                    else:
                        state_str = _format_polymorphic_states(parts)
                else:
                    state_str = char.states.get(raw_state, str(raw_state))

            # -------------------------
            # FINAL SAFETY CHECK
            # -------------------------

            if isinstance(state_str, set):
                raise TypeError(
                    f"SET LEAKED INTO KG: {taxon.name}, {char.name}, {state_str}"
                )

            if state_str is None:
                continue

            # -------------------------
            # INSERT INTO HIERARCHY
            # -------------------------

            if isinstance(char.name, list):
                insert_into_hierarchy(char_map, char.name, state_str)
            else:
                insert_into_hierarchy(char_map, [char.name], state_str)

        temp_kg[taxon.name] = {"Characteristics": char_map}

    return temp_kg
