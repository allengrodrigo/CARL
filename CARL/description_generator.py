def _char_sentence(char, taxon):
    """Return ((name, state)_or_None, na_name_or_None, missing_name_or_None) for one character.

    State is resolved **by character index** (``state_for``), so two characters
    that share a name keep their distinct states instead of collapsing to the
    last one. Hierarchical (list-valued) names are left untouched -- they do not
    render today, and that behaviour is preserved (returned as skipped)."""
    from core_operations import state_for, flat_name  # lazy: avoid import cycle
    name = flat_name(char)
    if name is None:                 # multi-level hierarchical name -> skip (as before)
        return None, None, None
    state = state_for(taxon, char)
    if state in (None, "Unknown"):
        return None, None, None
    if state == "N":
        return None, name, None
    if state == "M":
        return None, None, name
    return (name, state), None, None


def _join_states(states):
    """Join state strings with an Oxford comma: [a] -> 'a'; [a, b] -> 'a and b';
    [a, b, c] -> 'a, b, and c'."""
    if len(states) == 1:
        return states[0]
    if len(states) == 2:
        return f"{states[0]} and {states[1]}"
    return ", ".join(states[:-1]) + ", and " + states[-1]


def _collapse_sentences(pairs):
    """Turn (name, state) pairs into 'name: state.' sentences, merging runs of
    *consecutive* pairs whose character name is *identical* into a single
    'name: s1, s2, and s3.' sentence. Callers pass one block's pairs at a time,
    so a heading always breaks a run."""
    sentences = []
    i = 0
    while i < len(pairs):
        name, state = pairs[i]
        states = [state]
        j = i + 1
        while j < len(pairs) and pairs[j][0] == name:
            states.append(pairs[j][1])
            j += 1
        sentences.append(f"{name}: {_join_states(states)}.")
        i = j
    return sentences


def build_base_description(taxon, kg, dataset, char_exclusions=None, char_groups=None):
    """Deterministic description compatible with hierarchical KG.

    When char_groups is provided (OrderedDict from parse_charsets), output is
    structured into labelled paragraphs followed by an **Other Features** block
    for any remaining characters.  When char_groups is None or empty, output is
    a flat sentence list (existing behaviour, unchanged).
    """
    char_by_index = {c.index: c for c in dataset.characters}

    not_applicable = []
    missing = []

    if not char_groups:
        pairs = []
        for char in dataset.characters:
            if char_exclusions and char.index in char_exclusions:
                continue
            sent, na, mis = _char_sentence(char, taxon)
            if sent:
                pairs.append(sent)
            elif na:
                not_applicable.append(na)
            elif mis:
                missing.append(mis)

        result = " ".join(_collapse_sentences(pairs))
        if not_applicable:
            result += "\n(Not applicable: " + "; ".join(not_applicable) + ".)"
        if missing:
            result += "\n(Missing data: " + "; ".join(missing) + ".)"
        return result

    # --- Paragraph mode ---
    covered = set()
    for indices in char_groups.values():
        covered.update(indices)

    paragraphs = []

    for label, indices in char_groups.items():
        pairs = []
        for i in indices:
            char = char_by_index.get(i)
            if char is None:
                continue
            if char_exclusions and i in char_exclusions:
                continue
            sent, na, mis = _char_sentence(char, taxon)
            if sent:
                pairs.append(sent)
            elif na:
                not_applicable.append(na)
            elif mis:
                missing.append(mis)
        if pairs:
            paragraphs.append(f"**{label}**\n" + " ".join(_collapse_sentences(pairs)))

    other_pairs = []
    for char in dataset.characters:
        if char.index in covered:
            continue
        if char_exclusions and char.index in char_exclusions:
            continue
        sent, na, mis = _char_sentence(char, taxon)
        if sent:
            other_pairs.append(sent)
        elif na:
            not_applicable.append(na)
        elif mis:
            missing.append(mis)

    if other_pairs:
        paragraphs.append("**Other Features**\n" + " ".join(_collapse_sentences(other_pairs)))

    result = "\n\n".join(paragraphs)
    if not_applicable:
        result += "\n(Not applicable: " + "; ".join(not_applicable) + ".)"
    if missing:
        result += "\n(Missing data: " + "; ".join(missing) + ".)"
    return result