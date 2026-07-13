
import ast as _ast
import math as _math

from core_operations import get_state_from_kg, build_temp_kg, state_for, flat_name


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def format_char_name(char_name):
    if isinstance(char_name, list):
        char_str = ", ".join(char_name)
    else:
        char_str = char_name
    return char_str.replace("_", " ")


def _get_char_path(char):
    return char.name if isinstance(char.name, list) else [char.name]


def _kstate(kg, taxon, char):
    """Resolve a taxon's state for one character.

    By character INDEX for flat (string) names -- so two characters that share a
    name keep distinct states instead of collapsing to the last one in the
    name-keyed KG -- and via the hierarchical KG for list-valued names.
    """
    if flat_name(char) is not None:
        return state_for(taxon, char)
    return get_state_from_kg(kg, taxon.name, _get_char_path(char))


def _count_m(kg, taxa_subset, char):
    return sum(
        1 for t in taxa_subset
        if _kstate(kg, t, char) in (None, "M", "N")
    )


def _definite_state_counts(kg, taxa_subset, char):
    """
    Return {state: count} for taxa with a single definite (non-M, non-N, non-poly) state.
    Polymorphic taxa are excluded — they contribute no net splitting power.
    """
    counts = {}
    for t in taxa_subset:
        state = _kstate(kg, t, char)
        if state is None or state in ("M", "N"):
            continue
        if ", or " in state:
            continue
        counts[state] = counts.get(state, 0) + 1
    return counts


def _get_precluded_chars(branch_states, preclusion, kg, taxa, characters):
    """
    Return the set of 0-based character indices blocked by KEY sub-block rules.

    Case 1 — conditioning state established in this branch:
        branch_states[cond_char] == state_label → block all dependents.
    Case 2 — dependent has at least one N-taxon in current subset:
        Block that character until its conditioning char is resolved.
        Does NOT fire when conditioning char is constant (no taxa have N),
        preventing deadlock when a conditioning char has no discriminating power.
    """
    precluded = set()
    for (cond_char, state_label), blocked in preclusion.items():
        if branch_states.get(cond_char) == state_label:
            precluded.update(blocked)
        else:
            for b_char in blocked:
                bc = characters[b_char]
                if any(_kstate(kg, t, bc) == "N" for t in taxa):
                    precluded.add(b_char)
    return precluded


def is_useful_character_kg(kg, taxa_subset, char, fallback=False):
    if not fallback and _count_m(kg, taxa_subset, char) > 0:
        return False
    return len(_definite_state_counts(kg, taxa_subset, char)) >= 2


def _split(kg, taxa_subset, char):
    """Partition taxa by definite state; polymorphic taxa placed in every matching group."""
    groups = {}
    for taxon in taxa_subset:
        state = _kstate(kg, taxon, char)
        if state is None or state in ("M", "N"):
            continue
        if ", or " in state:
            for s in state.split(", or "):
                s = s.strip()
                if taxon not in groups.get(s, []):
                    groups.setdefault(s, []).append(taxon)
        else:
            groups.setdefault(state, []).append(taxon)
    return groups


# ---------------------------------------------------------------------------
# Shannon IG scoring
# ---------------------------------------------------------------------------

def _score_kg(kg, taxa_subset, char, global_char_counts=None,
              char_weights=None, repeat_penalty=0.05):
    """
    effective_IG = H(definite states) × (t_def/t_total) × W × α^use_count
    """
    t_total      = len(taxa_subset)
    state_counts = _definite_state_counts(kg, taxa_subset, char)
    if len(state_counts) < 2:
        return 0.0
    t_def = sum(state_counts.values())
    if t_def == 0:
        return 0.0
    h       = -sum((n / t_def) * _math.log2(n / t_def) for n in state_counts.values())
    w       = (char_weights or {}).get(char.index, 1.0)
    uses    = (global_char_counts or {}).get(char.index, 0)
    return h * (t_def / t_total) * w * (repeat_penalty ** uses)


def _choose_best_kg(kg, dataset, taxa_subset, used_chars,
                    global_char_counts=None, precluded_chars=None,
                    char_weights=None, repeat_penalty=0.05):
    """Select highest-IG character. Returns (char, is_fallback)."""
    counts  = global_char_counts or {}
    pc      = precluded_chars or set()
    weights = char_weights or {}

    def _rank(use_fallback):
        scored = []
        for char in dataset.characters:
            if char.index in used_chars:
                continue
            if char.index in pc:
                continue
            if weights.get(char.index, 1.0) == 0.0:
                continue
            if not is_useful_character_kg(kg, taxa_subset, char, fallback=use_fallback):
                continue
            scored.append((_score_kg(kg, taxa_subset, char, counts, weights, repeat_penalty),
                           _count_m(kg, taxa_subset, char),
                           char))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored

    strict = _rank(False)
    if strict:
        return strict[0][2], False
    fb = _rank(True)
    if fb:
        return fb[0][2], True
    return None, False


def build_tree_kg(kg, dataset, taxa_subset=None, used_chars=None,
                  _global_counts=None, preclusion=None, branch_states=None,
                  char_weights=None, repeat_penalty=0.05):
    """
    Recursively build the decision tree using Shannon IG character selection.

    _global_counts — shared dict {char_index: use_count}, incremented before
        recursing so all child branches see the updated repeat-penalty count.
    preclusion     — {(cond_char_0, state_label): [blocked_0, ...]} from KEY block.
    branch_states  — {char_0based: state_label} path from root to this node.
    char_weights   — {char_0based: float}; W=0 hard exclusion; default 1.0.
    repeat_penalty — α in score × α^use_count.
    """
    if taxa_subset is None:
        taxa_subset = list(dataset.taxa)
    if used_chars is None:
        used_chars = set()
    if _global_counts is None:
        _global_counts = {}
    if preclusion is None:
        preclusion = {}
    if branch_states is None:
        branch_states = {}
    if char_weights is None:
        char_weights = {}

    if len(taxa_subset) == 1:
        return taxa_subset[0].name

    precluded_chars = _get_precluded_chars(branch_states, preclusion,
                                           kg, taxa_subset, dataset.characters)

    char, is_fallback = _choose_best_kg(
        kg, dataset, taxa_subset, used_chars,
        global_char_counts=_global_counts,
        precluded_chars=precluded_chars,
        char_weights=char_weights,
        repeat_penalty=repeat_penalty)

    if char is None:
        return f"UNRESOLVED: {[t.name for t in taxa_subset]}"

    used_chars.add(char.index)
    _global_counts[char.index] = _global_counts.get(char.index, 0) + 1

    if is_fallback:
        m_taxa      = [t for t in taxa_subset
                       if _kstate(kg, t, char) in (None, "M", "N")]
        taxa_subset = [t for t in taxa_subset
                       if _kstate(kg, t, char) not in (None, "M", "N")]
    else:
        m_taxa = []

    groups = _split(kg, taxa_subset, char)
    if not groups:
        return f"UNRESOLVED: {[t.name for t in taxa_subset + m_taxa]}"

    node = {"character": char, "groups": {}, "taxa": taxa_subset}
    for state, group in groups.items():
        child_branch_states = {**branch_states, char.index: state}
        node["groups"][state] = build_tree_kg(
            kg, dataset, group, used_chars.copy(),
            _global_counts=_global_counts,
            preclusion=preclusion,
            branch_states=child_branch_states,
            char_weights=char_weights,
            repeat_penalty=repeat_penalty)

    if m_taxa:
        node["groups"]["__unresolved_M__"] = f"UNRESOLVED: {[t.name for t in m_taxa]}"

    return node


# ---------------------------------------------------------------------------
# Simpson's Index scoring
# ---------------------------------------------------------------------------

def _compute_si(kg, taxa, char):
    """Simpson's diversity = 1 − Σ(count_s/n)² over definite-state taxa."""
    counts = _definite_state_counts(kg, taxa, char)
    n = sum(counts.values())
    if n == 0:
        return 0.0
    return 1.0 - sum((c / n) ** 2 for c in counts.values())


def _compute_within_si(kg, def_groups, char):
    """Weighted within-group SI using p_s² weights (exact SI decomposition)."""
    n_total = sum(len(g) for g in def_groups.values())
    if n_total == 0:
        return 0.0
    result = 0.0
    for group_taxa in def_groups.values():
        p_s = len(group_taxa) / n_total
        result += (p_s ** 2) * _compute_si(kg, group_taxa, char)
    return result


def _mean_si(kg, taxa, chars):
    if not chars:
        return 0.0
    return sum(_compute_si(kg, taxa, c) for c in chars) / len(chars)


def _score_si(kg, taxa_subset, char, c_available,
              global_char_counts=None, char_weights=None, repeat_penalty=0.05):
    """
    Score = (D̄_B(c) / D̄_res) × (t_def/t_total) × W × α^use_count

    D̄_B  = mean between-group SI across C_after = C_available \\ {char}
    D̄_res = mean SI over C_after within definite-state taxa for char
    Edge case (C_after empty): score = diversity of the split itself.
    """
    t_total      = len(taxa_subset)
    state_counts = _definite_state_counts(kg, taxa_subset, char)

    if len(state_counts) < 2:
        return 0.0
    t_def = sum(state_counts.values())
    if t_def == 0:
        return 0.0

    def_groups = {}
    n_poly = 0
    for t in taxa_subset:
        state = _kstate(kg, t, char)
        if state is None or state in ("M", "N"):
            continue
        if ", or " in state:
            n_poly += 1
            continue
        def_groups.setdefault(state, []).append(t)

    if len(def_groups) < 2:
        return 0.0

    c_after = [c for c in c_available if c.index != char.index]

    if not c_after:
        raw = _compute_si(kg, taxa_subset, char)
    else:
        t_def_taxa = [t for g in def_groups.values() for t in g]
        d_res = _mean_si(kg, t_def_taxa, c_after)
        if d_res == 0.0:
            return 0.0

        total_between = 0.0
        for ci in c_after:
            d_i_total  = _compute_si(kg, t_def_taxa, ci)
            d_i_within = _compute_within_si(kg, def_groups, ci)
            total_between += max(0.0, d_i_total - d_i_within)

        d_bar_b = total_between / len(c_after)
        if n_poly > 0:
            d_bar_b *= t_def / (t_def + n_poly)
        raw = d_bar_b / d_res

    w    = (char_weights or {}).get(char.index, 1.0)
    uses = (global_char_counts or {}).get(char.index, 0)
    return raw * (t_def / t_total) * w * (repeat_penalty ** uses)


def _choose_best_si(kg, dataset, taxa_subset, used_chars,
                    global_char_counts=None, precluded_chars=None,
                    char_weights=None, repeat_penalty=0.05):
    """Select highest-SI character. Returns (char, is_fallback)."""
    counts  = global_char_counts or {}
    pc      = precluded_chars or set()
    weights = char_weights or {}

    def _rank_si(use_fallback):
        eligible = [
            c for c in dataset.characters
            if c.index not in used_chars
            and c.index not in pc
            and weights.get(c.index, 1.0) != 0.0
            and is_useful_character_kg(kg, taxa_subset, c, fallback=use_fallback)
        ]
        scored = [
            (_score_si(kg, taxa_subset, c, eligible, counts, weights, repeat_penalty),
             _count_m(kg, taxa_subset, c),
             c)
            for c in eligible
        ]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored

    strict = _rank_si(False)
    if strict:
        return strict[0][2], False
    fb = _rank_si(True)
    if fb:
        return fb[0][2], True
    return None, False


def build_tree_si(kg, dataset, taxa_subset=None, used_chars=None,
                  _global_counts=None, preclusion=None, branch_states=None,
                  char_weights=None, repeat_penalty=0.05):
    """
    Recursively build the decision tree using Simpson's Index character selection.
    Identical structure to build_tree_kg; only character scoring differs.
    """
    if taxa_subset is None:
        taxa_subset = list(dataset.taxa)
    if used_chars is None:
        used_chars = set()
    if _global_counts is None:
        _global_counts = {}
    if preclusion is None:
        preclusion = {}
    if branch_states is None:
        branch_states = {}
    if char_weights is None:
        char_weights = {}

    if len(taxa_subset) == 1:
        return taxa_subset[0].name

    precluded_chars = _get_precluded_chars(branch_states, preclusion,
                                           kg, taxa_subset, dataset.characters)

    char, is_fallback = _choose_best_si(
        kg, dataset, taxa_subset, used_chars,
        global_char_counts=_global_counts,
        precluded_chars=precluded_chars,
        char_weights=char_weights,
        repeat_penalty=repeat_penalty)

    if char is None:
        return f"UNRESOLVED: {[t.name for t in taxa_subset]}"

    used_chars.add(char.index)
    _global_counts[char.index] = _global_counts.get(char.index, 0) + 1

    if is_fallback:
        m_taxa      = [t for t in taxa_subset
                       if _kstate(kg, t, char) in (None, "M", "N")]
        taxa_subset = [t for t in taxa_subset
                       if _kstate(kg, t, char) not in (None, "M", "N")]
    else:
        m_taxa = []

    groups = _split(kg, taxa_subset, char)
    if not groups:
        return f"UNRESOLVED: {[t.name for t in taxa_subset + m_taxa]}"

    node = {"character": char, "groups": {}, "taxa": taxa_subset}
    for state, group in groups.items():
        child_branch_states = {**branch_states, char.index: state}
        node["groups"][state] = build_tree_si(
            kg, dataset, group, used_chars.copy(),
            _global_counts=_global_counts,
            preclusion=preclusion,
            branch_states=child_branch_states,
            char_weights=char_weights,
            repeat_penalty=repeat_penalty)

    if m_taxa:
        node["groups"]["__unresolved_M__"] = f"UNRESOLVED: {[t.name for t in m_taxa]}"

    return node


# ---------------------------------------------------------------------------
# Invariant checker
# ---------------------------------------------------------------------------

def _collect_key_taxa(node, found=None):
    if found is None:
        found = set()
    if isinstance(node, str):
        if node.startswith("UNRESOLVED:"):
            try:
                names = _ast.literal_eval(node[len("UNRESOLVED:"):].strip())
                found.update(names)
            except Exception:
                pass
        else:
            found.add(node.replace("_", " "))
        return found
    for arm in node.get("arms", []):
        _collect_key_taxa(arm["group"], found)
    return found


def _check_no_taxa_dropped(structured_tree, input_taxa):
    input_names = {t.name for t in input_taxa}
    found_names = _collect_key_taxa(structured_tree)
    found_norm  = {n.replace(" ", "_") for n in found_names} | found_names
    missing = {n for n in input_names if n not in found_norm
               and n.replace("_", " ") not in found_names}
    if missing:
        raise AssertionError(
            f"INVARIANT VIOLATED — {len(missing)} taxon/taxa silently dropped "
            f"from key: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# Key statistics
# ---------------------------------------------------------------------------

def _collect_depths(node, depth=0):
    if isinstance(node, str):
        if node.startswith("UNRESOLVED:"):
            try:
                names = _ast.literal_eval(node[len("UNRESOLVED:"):].strip())
                return [(name, depth) for name in names]
            except Exception:
                return [("UNRESOLVED", depth)]
        return [(node, depth)]
    result = []
    for arm in node.get("arms", []):
        result.extend(_collect_depths(arm["group"], depth + 1))
    return result


def _format_key_stats(structured_tree, algo):
    depths = _collect_depths(structured_tree)
    if not depths:
        return []
    avg   = sum(d for _, d in depths) / len(depths)
    min_d = min(d for _, d in depths)
    max_d = max(d for _, d in depths)
    by_depth = {}
    for name, d in depths:
        by_depth.setdefault(d, []).append(name)

    SEP = "-" * 70
    lines = [
        "",
        SEP,
        (f"Key statistics  [{algo}]:  avg {avg:.2f} steps/taxon"
         f"  (min {min_d}, max {max_d})  |  {len(depths)} taxa"),
    ]
    for d in sorted(by_depth):
        label = f"{d} step{'s' if d != 1 else ''}"
        lines.append(f"  {label}: {', '.join(sorted(by_depth[d]))}")
    lines.append(SEP)
    return lines


# ---------------------------------------------------------------------------
# Key formatting — unified multi-arm structure
#
# Structured tree format: {"char": ..., "arms": [{"state": ..., "group": ...}], "step": N}
# "arms" may have 2 entries (binary) or k entries (multi-arm).
# Leaf nodes are strings (taxon name or "UNRESOLVED: [...]").
# ---------------------------------------------------------------------------

def _best_binary_partition(char, groups_dict):
    """
    Find the binary partition of state keys that maximises split IG.
    Tie-break: smallest |n_A − n_B|.  Returns (states_A, states_B).
    """
    states = [s for s in groups_dict if s != "__unresolved_M__"]
    sizes  = {s: len(groups_dict[s]) for s in states}

    if len(states) <= 2:
        return states[:1], states[1:]

    best_ig = best_diff = -1.0
    best_a = best_b = None
    n_states = len(states)
    for mask in range(1, 1 << (n_states - 1)):
        a = [states[i] for i in range(n_states) if mask & (1 << i)]
        b = [states[i] for i in range(n_states) if not (mask & (1 << i))]
        if not a or not b:
            continue
        n_a = sum(sizes[s] for s in a)
        n_b = sum(sizes[s] for s in b)
        n   = n_a + n_b
        if n == 0:
            continue
        p_a, p_b = n_a / n, n_b / n
        ig = 0.0
        if p_a > 0:
            ig -= p_a * _math.log2(p_a)
        if p_b > 0:
            ig -= p_b * _math.log2(p_b)
        diff = abs(n_a - n_b)
        if ig > best_ig or (ig == best_ig and diff < best_diff):
            best_ig, best_diff, best_a, best_b = ig, diff, a, b

    return best_a or states[:1], best_b or states[1:]


def _merge_groups(groups_dict, state_keys):
    seen, merged = set(), []
    for s in state_keys:
        for t in groups_dict.get(s, []):
            if id(t) not in seen:
                seen.add(id(t))
                merged.append(t)
    return merged


def build_key_lines(node, mode="binary"):
    """
    Convert the raw decision tree into a structured arm tree.

    mode="binary"  — two arms per keylet using optimal binary partition.
    mode="multi"   — one arm per distinct character state.

    Returns a dict {"char", "arms": [{"state", "group"}, ...]} or a string (leaf).
    """
    if isinstance(node, str):
        return node

    char       = node["character"]
    unresolved = node["groups"].get("__unresolved_M__")
    groups     = {s: g for s, g in node["groups"].items()
                  if s != "__unresolved_M__"}

    if len(groups) == 0:
        return unresolved or "UNRESOLVED: []"

    if len(groups) == 1 and unresolved is None:
        return build_key_lines(next(iter(groups.values())), mode=mode)

    if mode == "binary":
        states_a, states_b = _best_binary_partition(char, groups)

        def _state_label(keys):
            labels = [char.states.get(s, s) if hasattr(char, "states") else s
                      for s in keys]
            return " or ".join(labels)

        def _make_subtree(keys):
            if len(keys) == 1:
                return groups[keys[0]]
            return {"character": char,
                    "groups":    {s: groups[s] for s in keys},
                    "taxa":      _merge_groups(groups, keys)}

        arms = [
            {"state": _state_label(states_a),
             "group": build_key_lines(_make_subtree(states_a), mode=mode)},
            {"state": _state_label(states_b),
             "group": build_key_lines(_make_subtree(states_b), mode=mode)},
        ]
    else:
        def _state_label_single(key):
            return char.states.get(key, key) if hasattr(char, "states") else key

        arms = [
            {"state": _state_label_single(state),
             "group": build_key_lines(subtree, mode=mode)}
            for state, subtree in groups.items()
        ]

    if unresolved is not None:
        arms.append({"state": "UNKNOWN", "group": unresolved})

    return {"char": char, "arms": arms}


def assign_steps(node, counter):
    if isinstance(node, str):
        return node
    node["step"] = counter["step"]
    counter["step"] += 1
    for arm in node["arms"]:
        assign_steps(arm["group"], counter)
    return node


def render_key(node):
    lines = []

    def traverse(n):
        if isinstance(n, str):
            return
        step   = n["step"]
        char_s = format_char_name(n["char"].name)
        for i, arm in enumerate(n["arms"]):
            letter = chr(ord("a") + i)
            dest   = (arm["group"].replace("_", " ")
                      if isinstance(arm["group"], str)
                      else f"go to {arm['group']['step']}")
            lines.append(f"{step}{letter}. {char_s} = {arm['state']} → {dest}")
        for arm in n["arms"]:
            if not isinstance(arm["group"], str):
                traverse(arm["group"])

    traverse(node)
    return lines


def format_key(tree, mode="binary"):
    """Convert raw decision tree to key lines. mode='binary' or 'multi'."""
    structured = build_key_lines(tree, mode=mode)
    if isinstance(structured, str):
        return [structured]
    assign_steps(structured, {"step": 1})
    return render_key(structured)


# ---------------------------------------------------------------------------
# Top-level key generation API (used by ui_app.py)
# ---------------------------------------------------------------------------

def generate_key(kg, dataset, taxa_subset, algo="ig", mode="binary",
                 repeat_penalty=0.05, preclusion=None, char_weights=None):
    """
    Build and format a key. Returns (stats_lines, key_lines).

    algo          — "ig" (Shannon Information Gain) or "si" (Simpson's Index)
    mode          — "binary" (2-arm couplets) or "multi" (k-arm per character)
    repeat_penalty — α: score × α^use_count for cross-branch reuse
    preclusion    — from parse_key_block; {} if no KEY sub-block
    char_weights  — from parse_key_block; {} if no KEY sub-block
    """
    if preclusion is None:
        preclusion = {}
    if char_weights is None:
        char_weights = {}

    algo_label = algo.upper()

    if algo == "si":
        tree = build_tree_si(
            kg, dataset, taxa_subset=taxa_subset,
            preclusion=preclusion, char_weights=char_weights,
            repeat_penalty=repeat_penalty)
    else:
        tree = build_tree_kg(
            kg, dataset, taxa_subset=taxa_subset,
            preclusion=preclusion, char_weights=char_weights,
            repeat_penalty=repeat_penalty)

    structured = build_key_lines(tree, mode=mode)
    if not isinstance(structured, str):
        _check_no_taxa_dropped(structured, taxa_subset)
        assign_steps(structured, {"step": 1})
    key_lines   = render_key(structured) if not isinstance(structured, str) else [structured]
    stats_lines = _format_key_stats(structured, algo_label)

    return stats_lines, key_lines


# ---------------------------------------------------------------------------
# Legacy functions (kept for backward compatibility with older callers)
# ---------------------------------------------------------------------------

def score_character_kg(kg, taxa_subset, char):
    t_total      = len(taxa_subset)
    state_counts = _definite_state_counts(kg, taxa_subset, char)
    if len(state_counts) < 2:
        return 0.0
    t_def = sum(state_counts.values())
    if t_def == 0:
        return 0.0
    h = 0.0
    for n_s in state_counts.values():
        p = n_s / t_def
        h -= p * _math.log2(p)
    return h * (t_def / t_total)


def split_taxa_kg(kg, taxa_subset, char):
    return _split(kg, taxa_subset, char)


def choose_best_character_kg(kg, dataset, taxa_subset, used_chars):
    return _choose_best_kg(kg, dataset, taxa_subset, used_chars)


def is_useful_character(dataset, taxa_subset, char):
    return sum(1 for t in taxa_subset if t.states.get(char.index) != "N") >= 2


def score_character(dataset, taxa_subset, char):
    missing = polymorphic = 0
    valid_states = {}
    for taxon in taxa_subset:
        state = taxon.states.get(char.index)
        if state == "M":
            missing += 1
            continue
        if state == "N":
            continue
        if isinstance(state, set):
            polymorphic += 1
            for s in state:
                valid_states[s] = valid_states.get(s, 0) + 1
        else:
            valid_states[state] = valid_states.get(state, 0) + 1
    if not valid_states:
        return float("-inf")
    separation = len(valid_states)
    counts = list(valid_states.values())
    balance = min(counts) / max(counts) if len(counts) > 1 else 0
    return separation + balance - (10 * missing) - (2 * polymorphic)


def choose_best_character(dataset, taxa_subset, used_chars):
    best_char, best_score = None, float("-inf")
    for char in dataset.characters:
        if char.index in used_chars:
            continue
        if not is_useful_character(dataset, taxa_subset, char):
            continue
        score = score_character(dataset, taxa_subset, char)
        if score > best_score:
            best_score, best_char = score, char
    return best_char


def split_taxa(taxa_subset, char):
    groups = {}
    for taxon in taxa_subset:
        state = taxon.states.get(char.index)
        if state == "M":
            key = "M"
        elif state == "N":
            key = "N"
        elif isinstance(state, set):
            key = "POLY"
        else:
            key = state
        groups.setdefault(key, []).append(taxon)
    return groups


def build_tree(dataset, taxa_subset=None, used_chars=None):
    if taxa_subset is None:
        taxa_subset = dataset.taxa
    if used_chars is None:
        used_chars = set()
    if len(taxa_subset) == 1:
        return taxa_subset[0].name
    char = choose_best_character(dataset, taxa_subset, used_chars)
    if char is None:
        return f"UNRESOLVED: {[t.name for t in taxa_subset]}"
    used_chars.add(char.index)
    groups = split_taxa(taxa_subset, char)
    node = {"character": char, "groups": {}, "taxa": taxa_subset}
    for state, group in groups.items():
        node["groups"][state] = build_tree(dataset, group, used_chars.copy())
    return node


def format_state(state, char, taxa_subset=None):
    if state not in ["POLY", "M", "N"]:
        return char.states.get(state, state)
    if state == "POLY" and taxa_subset:
        values = set()
        for t in taxa_subset:
            s = t.states.get(char.index)
            if isinstance(s, set):
                values.update(s)
            elif s not in ["M", "N"]:
                values.add(s)
        return " or ".join(char.states.get(v, v) for v in sorted(values))
    return {"M": "unknown", "N": "not applicable"}.get(state, state)
