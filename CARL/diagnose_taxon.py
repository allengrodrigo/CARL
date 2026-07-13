"""Diagnose Taxon — deterministic diagnosis action for TaxonGPT.

Given an index taxon and a comparison group, produces:
1. Unique character-state combinations (size 1, 2, 3) that distinguish
   the index taxon from all members of the comparison group.
2. Nearest neighbours: comparison taxa sorted by state-difference count,
   with per-character difference details.
"""

from itertools import combinations


def get_scored_states(dataset, taxon, char_exclusions=None):
    """Return {char_index: state_value} for characters with a definite state.

    Excludes M (missing), N (not applicable), ? (unknown), and None.
    Used for the index taxon and for nearest-neighbour comparisons.
    """
    result = {}
    for char in dataset.characters:
        if char_exclusions and char.index in char_exclusions:
            continue
        state = taxon.states.get(char.index)
        if state not in (None, "M", "N", "?"):
            result[char.index] = state
    return result


def _get_comparison_scored(dataset, taxon, char_exclusions=None):
    """Return {char_index: state_value} for uniqueness checks against comparison taxa.

    Keeps N (not applicable) so it can participate in the check — a taxon with N
    cannot match any real state, so it reinforces uniqueness.
    Drops M, ?, and None so those taxa are excluded from the check entirely.
    """
    result = {}
    for char in dataset.characters:
        if char_exclusions and char.index in char_exclusions:
            continue
        state = taxon.states.get(char.index)
        if state not in (None, "M", "?"):
            result[char.index] = state  # "N" is kept
    return result


def _state_label(dataset, char_index, state_value):
    """Return the human-readable label for a state value."""
    char = dataset.characters[char_index]
    if isinstance(state_value, set):
        return ", or ".join(char.states.get(s, str(s)) for s in sorted(state_value))
    return char.states.get(state_value, str(state_value))


def _char_name(dataset, char_index):
    name = dataset.characters[char_index].name
    if isinstance(name, list):
        return ", ".join(name)
    return name


def _matches(index_state, comparison_state):
    """Return True if comparison_state matches index_state.

    N is treated as non-matching (a taxon to which a character does not apply
    cannot share the index taxon's state for that character).
    Polymorphic comparison state matches if any of its values equals index_state.
    Note: M/? comparison states are excluded before this function is called in
    the uniqueness check; this guard is retained for safety and for nearest-
    neighbour use.
    """
    if comparison_state in (None, "M", "N", "?"):
        return False
    if isinstance(comparison_state, set):
        if isinstance(index_state, set):
            return bool(comparison_state & index_state)
        return index_state in comparison_state
    if isinstance(index_state, set):
        return comparison_state in index_state
    return comparison_state == index_state


def _missing_count(char_index, comparison_comp_scored):
    """Count comparison taxa excluded from the uniqueness check due to M/? for char_index.

    comparison_comp_scored is built with _get_comparison_scored, so N states are
    present in the dict. A None result means the taxon had M/? (excluded from check).
    """
    return sum(1 for ss in comparison_comp_scored if ss.get(char_index) is None)


def find_unique_combinations(index_taxon_name, comparison_taxon_names,
                              index_scored, all_comp_scored, dataset, k):
    """Find all k-state combinations unique to the index taxon.

    Returns list of (combo, score) sorted by score ascending (lower = better sampled).
    Each combo entry is a 5-tuple:
      (char_index, char_name, state_value, index_state_label, comparison_by_state)
    where comparison_by_state is {state_label: [taxon_name, ...]} showing how
    comparison taxa are distributed, with N taxa labelled "not applicable" and
    M/? taxa labelled "missing".

    Uniqueness check rules:
    - A comparison taxon with M/? for ANY character in the combo is excluded from
      the check entirely (we cannot know whether it matches).
    - A comparison taxon with N for a character is included; N cannot match any
      real state, so it reinforces the uniqueness claim.
    """
    comp_scored_list = [all_comp_scored[t] for t in comparison_taxon_names]
    char_indices = list(index_scored.keys())
    results = []

    for combo_indices in combinations(char_indices, k):
        unique = True
        for comp_ss in comp_scored_list:
            # Skip this comparison taxon if M/? for any character in the combo
            if any(comp_ss.get(ci) is None for ci in combo_indices):
                continue
            # N states remain: _matches(state, "N") is False, so they can't match
            if all(_matches(index_scored[ci], comp_ss.get(ci)) for ci in combo_indices):
                unique = False
                break

        if unique:
            combo = []
            for ci in combo_indices:
                comparison_by_state = {}
                for j, comp_name in enumerate(comparison_taxon_names):
                    comp_state = comp_scored_list[j].get(ci)
                    if comp_state is None:
                        label = "missing"
                    elif comp_state == "N":
                        label = "not applicable"
                    else:
                        label = _state_label(dataset, ci, comp_state)
                    comparison_by_state.setdefault(label, []).append(
                        comp_name.replace("_", " ")
                    )
                combo.append((
                    ci,
                    _char_name(dataset, ci),
                    index_scored[ci],
                    _state_label(dataset, ci, index_scored[ci]),
                    comparison_by_state,
                ))
            score = sum(_missing_count(ci, comp_scored_list) for ci in combo_indices)
            results.append((combo, score))

    results.sort(key=lambda x: x[1])
    return results


def find_nearest_neighbours(index_taxon_name, comparison_taxon_names,
                             index_scored, all_scored, dataset, threshold):
    """Return (taxon_name, n_differences, diff_details) for comparison taxa differing
    from the index taxon by at most `threshold` states. Sorted ascending by n_differences.

    diff_details is a list of (char_name, index_state_label, comp_state_label).
    Characters missing (M/N/?) in either taxon are excluded from the difference count.
    """
    results = []
    for comp_name in comparison_taxon_names:
        comp_scored = all_scored[comp_name]
        diffs = []
        for ci, index_state in index_scored.items():
            comp_state = comp_scored.get(ci)
            if comp_state in (None, "M", "N", "?"):
                continue
            if not _matches(index_state, comp_state):
                diffs.append((
                    _char_name(dataset, ci),
                    _state_label(dataset, ci, index_state),
                    _state_label(dataset, ci, comp_state),
                ))
        if len(diffs) <= threshold:
            results.append((comp_name, len(diffs), diffs))

    results.sort(key=lambda x: x[1])
    return results


def build_diagnosis_output(index_taxon, comparison_taxa, dataset, threshold=5,
                           char_exclusions=None):
    """Master function. Returns a structured dict with diagnosis and nearest-neighbour results."""
    # all_scored: definite states only (M, N, ?, None excluded) — used for index taxon
    # and nearest-neighbour comparisons
    all_scored = {t.name: get_scored_states(dataset, t, char_exclusions)
                  for t in [index_taxon] + comparison_taxa}

    # all_comp_scored: keeps N for comparison taxa so it participates in uniqueness checks
    all_comp_scored = {t.name: _get_comparison_scored(dataset, t, char_exclusions)
                       for t in comparison_taxa}

    index_scored = all_scored[index_taxon.name]
    comp_names = [t.name for t in comparison_taxa]

    unique_1 = find_unique_combinations(
        index_taxon.name, comp_names, index_scored, all_comp_scored, dataset, 1)
    unique_2 = find_unique_combinations(
        index_taxon.name, comp_names, index_scored, all_comp_scored, dataset, 2)
    unique_3 = find_unique_combinations(
        index_taxon.name, comp_names, index_scored, all_comp_scored, dataset, 3)

    nearest = find_nearest_neighbours(
        index_taxon.name, comp_names, index_scored, all_scored, dataset, threshold)

    return {
        "index_taxon": index_taxon.name,
        "comparison_group": comp_names,
        "unique_1": unique_1[:3],
        "unique_2": unique_2[:3],
        "unique_3": unique_3[:3],
        "diagnosable": bool(unique_1 or unique_2 or unique_3),
        "nearest_neighbours": nearest,
        "threshold": threshold,
    }


def format_diagnosis_output(result):
    """Serialise the diagnosis result dict to a structured string for LLM rendering."""
    lines = []
    index = result["index_taxon"].replace("_", " ")
    comp_display = [t.replace("_", " ") for t in result["comparison_group"]]

    lines.append(f"DIAGNOSIS OF: {index}")
    lines.append(
        f"COMPARISON GROUP ({len(comp_display)} taxa): " + ", ".join(comp_display))
    lines.append("")

    if not result["diagnosable"]:
        lines.append("DIAGNOSABILITY: UNDIAGNOSABLE within this comparison group")
        lines.append(
            "No unique character-state combination exists at levels 1, 2, or 3.")
        lines.append("")
    else:
        lines.append("UNIQUE CHARACTER-STATE COMBINATIONS")
        lines.append("")
        level_labels = {
            1: "Level 1 (unique single state(s))",
            2: "Level 2 (unique combination(s) of two states)",
            3: "Level 3 (unique combination(s) of three states)",
        }
        for level, key in [(1, "unique_1"), (2, "unique_2"), (3, "unique_3")]:
            combos = result[key]
            lines.append(f"{level_labels[level]}:")
            if not combos:
                lines.append("  None found.")
            else:
                for i, (combo, _score) in enumerate(combos, 1):
                    lines.append(f"  {i}.")
                    for _ci, char_name, _sv, idx_label, comp_by_state in combo:
                        lines.append(f"    {char_name}:")
                        lines.append(f"      {index}: {idx_label}")
                        for state_str, taxon_names in comp_by_state.items():
                            lines.append(f"      {', '.join(taxon_names)}: {state_str}")
            lines.append("")

    nn = result["nearest_neighbours"]
    lines.append(f"NEAREST NEIGHBOURS (threshold: <={result['threshold']} differences)")
    lines.append("")
    if not nn:
        lines.append(f"  No taxa differ by {result['threshold']} or fewer states.")
    else:
        for taxon_name, n_diffs, diffs in nn:
            disp = taxon_name.replace("_", " ")
            lines.append(f"{disp}: {n_diffs} difference(s)")
            for char_name, idx_lbl, comp_lbl in diffs:
                lines.append(
                    f"  {char_name}: {index} = {idx_lbl}; {disp} = {comp_lbl}")
            lines.append("")

    return "\n".join(lines)
