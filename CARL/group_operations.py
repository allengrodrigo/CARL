from data_model import Taxon
from carl_parser import NONE_ID, _is_real


# =========================
# GROUPS (VIRTUAL TAXA)
# =========================

def build_group_taxon(dataset, groups, group_name, cache=None, kg=None,
                      group_data_ids=None, member_data_ids=None):
    """
    Build a virtual Taxon representing a group.

    If the group subject has a DataID in group_data_ids, its KG row is used
    directly (fast path). NONE_ID means explicit no-data; returns empty Taxon.
    Otherwise character states are aggregated from group members (slow path).

    member_data_ids — {(group_name, member_name): data_id} — supplies the
    effective DataID for each member (in-statement value or own declaration).
    When present, members are looked up in the KG by DataID rather than name.

    Guarantees:
    - KG is source of truth for base taxa
    - Nested groups handled correctly
    - All states are strings ("A", "A, or B", "M", "N")
    - No sets ever used internally or returned
    """
    if cache is None:
        cache = {}

    if group_name in cache:
        return cache[group_name]

    # Resolve a KG key (taxon name / DataID) back to its source Taxon so member
    # states can be read by character INDEX -- flat characters that share a name
    # would otherwise collapse to the last state via the name-keyed KG.
    taxa_by_name = {t.name: t for t in dataset.taxa}

    # ── Fast path: group subject has its own coded DataID ────────────────────
    data_id = (group_data_ids or {}).get(group_name)
    if data_id == NONE_ID:
        group_taxon = Taxon(group_name)
        cache[group_name] = group_taxon
        return group_taxon
    if data_id:
        if kg is None:
            from core_operations import build_knowledge_graph
            kg = build_knowledge_graph(dataset)
        if data_id in kg:
            from core_operations import get_state_from_kg, state_for, flat_name
            group_taxon = Taxon(group_name)
            src = taxa_by_name.get(data_id)
            for char in dataset.characters:
                char_path = char.name if isinstance(char.name, list) else [char.name]
                if flat_name(char) is not None and src is not None:
                    state = state_for(src, char)          # by index (flat names)
                else:
                    state = get_state_from_kg(kg, data_id, char_path)  # hierarchical
                if state is not None:
                    group_taxon.states[char.index] = state
            cache[group_name] = group_taxon
            return group_taxon

    members = groups.get(group_name)
    if members is None:
        raise ValueError(f"Group '{group_name}' is undefined.")

    # Lazy KG build
    if kg is None:
        from core_operations import build_knowledge_graph
        kg = build_knowledge_graph(dataset)

    from core_operations import get_state_from_kg, _format_polymorphic_states, state_for, flat_name

    resolved_members = []

    for member in members:
        member_did = (member_data_ids or {}).get((group_name, member))
        if member_did == NONE_ID:
            continue  # member has explicit no-data; contributes nothing to union
        lookup_key = member_did if member_did is not None else member
        if lookup_key in kg:
            resolved_members.append(lookup_key)
        elif member in groups:
            resolved_members.append(
                build_group_taxon(dataset, groups, member, cache, kg,
                                  group_data_ids=group_data_ids,
                                  member_data_ids=member_data_ids)
            )
        else:
            raise ValueError(
                f"Member '{member}' in group '{group_name}' "
                "is neither a taxon nor a defined group."
            )

    group_taxon = Taxon(group_name)

    for char in dataset.characters:
        char_path = char.name if isinstance(char.name, list) else [char.name]

        flattened_states = []
        m_count = 0
        n_count = 0

        for member in resolved_members:

            # -------------------------
            # GET STATE  (by character INDEX for flat names, so identically
            # named characters keep distinct states; hierarchical names still
            # resolve through the KG path)
            # -------------------------
            if isinstance(member, str):
                src = taxa_by_name.get(member) if flat_name(char) is not None else None
                if src is not None:
                    state = state_for(src, char)
                else:
                    state = get_state_from_kg(kg, member, char_path)
            else:
                # sub-group Taxon member — states already keyed by index
                state = member.states.get(char.index)

            # -------------------------
            # HANDLE M / N
            # -------------------------
            if state == "M":
                m_count += 1
                continue

            if state == "N":
                n_count += 1
                continue

            if not state:
                continue

            # -------------------------
            # NORMALISE STATE (CRITICAL FIX)
            # -------------------------

            # Case 1: set → flatten immediately
            if isinstance(state, set):
                for s in state:
                    if isinstance(s, str) and ", or " in s:
                        flattened_states.extend([x.strip() for x in s.split(", or ")])
                    else:
                        flattened_states.append(s)

            # Case 2: already polymorphic string
            elif isinstance(state, str) and ", or " in state:
                flattened_states.extend([x.strip() for x in state.split(", or ")])

            # Case 3: single value
            else:
                flattened_states.append(state)

        total = len(resolved_members)

        # -------------------------
        # FINAL STATE LOGIC
        # -------------------------

        if total == 0:
            continue

        if m_count == total:
            final_state = "M"

        elif n_count == total:
            final_state = "N"

        elif not flattened_states:
            final_state = "M"

        else:
            unique_states = sorted(set(flattened_states))

            if len(unique_states) == 1:
                final_state = unique_states[0]
            else:
                final_state = _format_polymorphic_states(unique_states)

        # -------------------------
        # FINAL SAFETY CHECK
        # -------------------------
        if isinstance(final_state, set):
            raise TypeError(f"SET LEAKED: {group_name}, {char.name}, {final_state}")

        group_taxon.states[char.index] = final_state

    cache[group_name] = group_taxon
    return group_taxon


def resolve_selection(
    dataset,
    groups,
    selected_taxa,
    selected_groups,
    flatten_groups=False,
    group_data_ids=None,
    member_data_ids=None,
):
    """
    Resolve selected taxa and groups.

    Parameters
    ----------
    dataset : Dataset
        The dataset containing taxa.
    groups : dict
        Mapping of group names to their members.
    selected_taxa : list[str]
        Names of explicitly selected taxa.
    selected_groups : list[str]
        Names of selected groups.
    flatten_groups : bool, optional (default=False)
        If True, return the individual taxa that compose the groups.
        If False, return virtual Taxon objects representing groups,
        preserving hierarchical structure.

    Returns
    -------
    list[Taxon]
        Resolved taxa or group taxa depending on `flatten_groups`.
    """

    resolved = []
    cache = {}

    # Quick lookup for taxa
    taxon_lookup = {taxon.name: taxon for taxon in dataset.taxa}

    # ------------------------------------------------------------------
    # Helper function to recursively collect taxa names from groups
    # ------------------------------------------------------------------
    def collect_taxa(group_name, visited=None):
        if visited is None:
            visited = set()

        if group_name in visited:
            return set()  # Prevent circular references
        visited.add(group_name)

        members = groups.get(group_name)
        if members is None:
            raise ValueError(f"Group '{group_name}' is undefined.")

        taxa_names = set()

        for member in members:
            if member in taxon_lookup:
                taxa_names.add(member)
            elif member in groups:
                taxa_names.update(collect_taxa(member, visited))
            else:
                raise ValueError(
                    f"Member '{member}' in group '{group_name}' "
                    "is neither a taxon nor a defined group."
                )

        return taxa_names

    # ------------------------------------------------------------------
    # Add explicitly selected taxa
    # ------------------------------------------------------------------
    for name in selected_taxa:
        if name in taxon_lookup:
            resolved.append(taxon_lookup[name])
        else:
            raise ValueError(f"Taxon '{name}' is not defined in the dataset.")

    # ------------------------------------------------------------------
    # Add selected groups
    # ------------------------------------------------------------------
    for group_name in selected_groups:
        if group_name not in groups:
            raise ValueError(f"Group '{group_name}' is undefined.")

        if flatten_groups:
            # Return individual taxa within the group
            taxa_names = collect_taxa(group_name)
            for name in taxa_names:
                resolved.append(taxon_lookup[name])
        else:
            # Return a virtual taxon representing the group
            resolved.append(
                build_group_taxon(dataset, groups, group_name, cache,
                                  group_data_ids=group_data_ids,
                                  member_data_ids=member_data_ids)
            )

    # ------------------------------------------------------------------
    # Default: return all taxa if nothing selected
    # ------------------------------------------------------------------
    if not resolved:
        return dataset.taxa

    # ------------------------------------------------------------------
    # Remove duplicates while preserving order
    # ------------------------------------------------------------------
    unique_resolved = []
    seen = set()
    for taxon in resolved:
        if taxon.name not in seen:
            unique_resolved.append(taxon)
            seen.add(taxon.name)

    return unique_resolved


def create_group_from_character_states(dataset, selections):
    """
    Create a group of taxa based on selected character states.

    Logic:
    - Union within each character (any selected state).
    - Intersection across characters (must satisfy all characters).

    Parameters
    ----------
    dataset : Dataset
        The dataset containing taxa and characters.
    selections : dict
        Mapping of character names to sets of selected state labels.
        Example:
        {
            "Spinnerets, degree of s": {"long", "short"},
            "Retreat construction": {"burrow"}
        }

    Returns
    -------
    list[str]
        Sorted list of taxa names satisfying the selection criteria.
    """
    if not selections:
        return []

    # Start with all taxa for intersection
    matching_taxa = {taxon.name for taxon in dataset.taxa}

    for character_name, selected_states in selections.items():
        # Find the corresponding Character object
        char = next(
            (
                c for c in dataset.characters
                if (
                    ", ".join(c.name) if isinstance(c.name, list) else c.name
                ) == character_name
            ),
            None
        )

        if char is None:
            continue

        # Map state labels to their corresponding state IDs
        state_ids = {
            state_id
            for state_id, label in char.states.items()
            if label in selected_states
        }

        # Union within the character
        taxa_for_character = set()
        for taxon in dataset.taxa:
            state = taxon.states.get(char.index)

            if isinstance(state, set):  # Polymorphic state
                if state & state_ids:
                    taxa_for_character.add(taxon.name)
            else:
                if state in state_ids:
                    taxa_for_character.add(taxon.name)

        # Intersection across characters
        matching_taxa &= taxa_for_character

    return sorted(matching_taxa)


def evaluate_taxa_for_mak(dataset, selections):
    """
    Evaluate each taxon against multi-access key criteria.

    Same union-within-character / AND-across-characters logic as
    create_group_from_character_states, but distinguishes M (missing)
    from N (inapplicable) and definite non-matches.

    Parameters
    ----------
    dataset : Dataset
    selections : dict
        {char_name: set_of_state_labels}  (same format as create_group_from_character_states)

    Returns
    -------
    dict
        {taxon_name: {"grey": bool, "m_char_nums": list[int]}}
        m_char_nums are 1-based character positions of characters with M/None coding.
    """
    if not selections:
        return {taxon.name: {"grey": False, "m_char_nums": []}
                for taxon in dataset.taxa}

    # Pre-build lookup: char_name -> (char_object, 1-based_num, state_ids)
    char_lookup = {}
    for i, char in enumerate(dataset.characters):
        cname = ", ".join(char.name) if isinstance(char.name, list) else char.name
        if cname in selections:
            state_ids = {
                sid for sid, lbl in char.states.items()
                if lbl in selections[cname]
            }
            char_lookup[cname] = (char, i + 1, state_ids)

    results = {}
    for taxon in dataset.taxa:
        grey = False
        m_char_nums = []

        for cname, (char, char_num, state_ids) in char_lookup.items():
            state = taxon.states.get(char.index)

            if state == "N":
                grey = True
                break
            elif state is None or state == "M":
                m_char_nums.append(char_num)
            elif isinstance(state, set):  # Polymorphic — union within character
                if not (state & state_ids):
                    grey = True
                    break
            else:
                if state not in state_ids:
                    grey = True
                    break

        results[taxon.name] = {"grey": grey, "m_char_nums": m_char_nums}

    return results


# =========================
# GROUP DATAID BUILDERS
# =========================

def build_group_data_ids(carl_block) -> dict:
    """Return {group_name: data_id} for group subjects with an explicit dataID.
    Covers both synonymizes (_syn suffix) and includes groups.
    Passes through both real DataIDs and NONE_ID so build_group_taxon can
    distinguish explicit-none from blank.
    """
    result = {}
    if not carl_block:
        return result
    for e in carl_block.entities:
        if e.data_id is not None:  # real or NONE_ID — skip blank
            if e.action == 'synonymizes':
                result[f"{e.name}_syn"] = e.data_id
            elif e.action == 'includes':
                result[e.name] = e.data_id
    return result


def build_member_data_ids(carl_block) -> dict:
    """Return {(group_name, member_name): data_id} for group members.

    Priority: in-statement object_data_id if given, else effective_data_id()
    from the member's own declaration (picks up renames inheritance).
    Only members with a non-blank resolved DataID are included.
    """
    result = {}
    if not carl_block:
        return result
    for e in carl_block.entities:
        if e.action not in ('synonymizes', 'includes'):
            continue
        g_name = f"{e.name}_syn" if e.action == 'synonymizes' else e.name
        rel_type = e.action  # 'synonymizes' or 'includes'
        for r in carl_block.relationships:
            if r.subject_id != e.entity_id or r.rel_type != rel_type:
                continue
            if r.object_data_id is not None:
                did = r.object_data_id
            else:
                member_entity = carl_block._by_name(r.object_name)
                did = (carl_block.effective_data_id(member_entity.entity_id)
                       if member_entity is not None else None)
            if did is not None:
                result[(g_name, r.object_name)] = did
    return result