def make_schema_json_safe(schema):
    """
    Convert schema into JSON-safe form for LLM usage:
    - remove internal fields (_*)
    - convert sets → lists
    """

    import copy

    safe = copy.deepcopy(schema)

    # remove internal fields
    keys_to_remove = [k for k in safe if k.startswith("_")]
    for k in keys_to_remove:
        safe.pop(k, None)

    # recursive conversion
    def convert(o):
        if isinstance(o, set):
            return list(o)
        elif isinstance(o, dict):
            return {k: convert(v) for k, v in o.items()}
        elif isinstance(o, list):
            return [convert(v) for v in o]
        return o

    return convert(safe)


# ============================================================
# MODEL TOKEN UTILITIES (NEW)
# ============================================================

import subprocess
import re


def get_model_context_size(model_name):
    """
    Attempt to extract context length from `ollama show`.
    Returns None if not found.
    """
    try:
        result = subprocess.run(
            ["ollama", "show", model_name],
            capture_output=True,
            text=True
        )

        output = result.stdout

        # Look for context/token hints
        match = re.search(r"(\d{3,5})\s*(context|tokens|ctx)", output, re.IGNORECASE)
        if match:
            return int(match.group(1))

    except Exception:
        pass

    return None


def estimate_context_from_size(model_size_gb):
    """
    Fallback heuristic based on model size.
    """
    try:
        size = float(model_size_gb)
    except Exception:
        return 4096

    if size < 2:
        return 2048
    elif size < 5:
        return 4096
    else:
        return 8192


def get_model_token_limit(model_name=None, model_size_gb=None):
    """
    Hybrid token limit estimator:
    1. Try ollama show
    2. Fall back to size heuristic
    3. Default fallback
    """

    # Try direct extraction
    if model_name:
        ctx = get_model_context_size(model_name)
        if ctx:
            return ctx

    # Fallback: size-based estimate
    if model_size_gb is not None:
        return estimate_context_from_size(model_size_gb)

    # Final fallback — generous default for API models (Groq, OpenRouter, Gemini)
    return 16384


# ============================================================
# TOKEN ESTIMATION (UPDATED)
# ============================================================

def estimate_num_predict_from_kg(
    dataset,
    taxa,
    kg,
    model_name=None,
    model_size_gb=None,
    mode="fast"
):
    """
    Estimate token budget based on dataset complexity and mode.

    mode:
        "fast" → single-pass formatting
        "full" → iterative adversarial refinement
    """

    total_words = 0

    for taxon in taxa:
        if taxon.name in kg:
            for state in kg[taxon.name]["Characteristics"].values():
                total_words += len(str(state).split())

    # ----------------------------------------
    # Expansion factors
    # ----------------------------------------
    if mode == "fast":
        expansion_factor = 5
    elif mode == "full":
        # RAW + OUTPUT + CRITIQUE + PROMPT overhead
        expansion_factor = 12
    else:
        expansion_factor = 6

    total_words *= expansion_factor

    # Convert words → tokens
    tokens = int(total_words / 0.75)

    # ----------------------------------------
    # Model-aware cap
    # ----------------------------------------
    max_tokens = get_model_token_limit(
        model_name=model_name,
        model_size_gb=model_size_gb
    )

    return min(max(tokens, 256), max_tokens)


# Cap dynamic output budgets at a realistic max-output size. A model's usable
# OUTPUT is usually far smaller than its context window, so capping on the
# context (what get_model_token_limit returns) can request more than the model
# will actually produce — which manifests as truncated output on some models.
OUTPUT_CEILING = 8192


def estimate_num_predict_from_text(raw_text, model_name=None, mode="fast"):
    """Estimate an output-token budget from the *actual raw text* to be rewritten.

    A prose rewrite is roughly proportional to its raw input (names + states,
    not just states), so measuring the real text is more accurate than counting
    knowledge-graph entries. Sized per call (e.g. per taxon), floored so short
    inputs still have room, and capped at a realistic output ceiling.

    mode: "full" leaves extra headroom for the correction pass (which reuses this
    budget); "fast" is a single rewrite.
    """
    input_tokens = max(1, len(raw_text) // 4)          # ~4 chars/token
    factor = 3.0 if mode == "full" else 1.5
    tokens = int(input_tokens * factor)
    cap = min(get_model_token_limit(model_name=model_name), OUTPUT_CEILING)
    return min(max(tokens, 1024), cap)