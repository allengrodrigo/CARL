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
# MODEL TOKEN UTILITIES — model-aware output budgeting
#
# Rather than guessing an output length from input length (the old approach:
# a hand-picked "expansion factor" times a word count), this asks the more
# useful question directly: given this model/provider's REAL limits and how
# much of the prompt is already spoken for, how much room is actually left?
# Providers bill for tokens actually generated, not the requested ceiling,
# and models stop on their own once done — so there's no need to predict
# output length at all; just grant the real available room and let the model
# stop naturally. This is what fixed the correction-pass truncation bug: the
# old heuristic sized the budget off the *original* raw text length, which
# undersized it badly once a verifier's report demanded restoring many
# omitted items — the corrected output needed to be longer than the input
# it was scaled from.
# ============================================================

import subprocess
import re


def get_model_context_size(model_name):
    """
    Attempt to extract context length from `ollama show` (local models only).
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


# Absolute sanity bounds, independent of any per-model lookup: a guard against
# a lookup returning something absurd (upper) or a near-empty budget (lower).
# CARL operates per-taxon, so realistic content — even a full corrected
# redescription restoring many omitted characters — shouldn't need more than
# this regardless of how large a model's true window is.
OUTPUT_CEILING = 16384
OUTPUT_FLOOR = 512

# Generic, deliberately conservative fallback for providers/models with no
# live or hardcoded limit data (OpenAI, Anthropic, Google, HuggingFace today).
# Real CARL prompts are normally well under this regardless of the model's
# true window, so this is a safety net, not something expected to bind often.
_GENERIC_CONTEXT_FALLBACK = 16384
_GENERIC_OUTPUT_FALLBACK = 4096

_OPENROUTER_MODEL_CACHE: dict | None = None


def _fetch_openrouter_limits(bare_model: str) -> tuple[int | None, int | None]:
    """Return (context_length, max_completion_tokens) for an OpenRouter model
    id, from OpenRouter's own live model catalogue — exact, per-model, not a
    guess. Cached for the process lifetime since this would otherwise be a
    live HTTP call on every single LLM call."""
    global _OPENROUTER_MODEL_CACHE
    if _OPENROUTER_MODEL_CACHE is None:
        _OPENROUTER_MODEL_CACHE = {}
        try:
            import requests
            resp = requests.get("https://openrouter.ai/api/v1/models", timeout=6)
            resp.raise_for_status()
            for m in resp.json().get("data", []):
                _OPENROUTER_MODEL_CACHE[m.get("id")] = m
        except Exception:
            pass  # leave cache empty for this process; caller falls back

    m = _OPENROUTER_MODEL_CACHE.get(bare_model)
    if not m:
        return None, None
    context = m.get("context_length")
    completion = (m.get("top_provider") or {}).get("max_completion_tokens")
    return context, completion


def get_model_output_budget(model_name: str | None, prompt_tokens: int) -> int:
    """The real usable output-token budget for THIS model and THIS prompt:
    how much room is actually left in the model's context window, capped by
    whatever the provider or model's own max-completion-tokens limit is —
    not a guess based on input length.
    """
    if not model_name:
        return min(_GENERIC_OUTPUT_FALLBACK, OUTPUT_CEILING)

    # Ollama (local): "model:tag", no "/" — same convention llm_interface
    # uses to route calls.
    if ":" in model_name and "/" not in model_name:
        context = get_model_context_size(model_name) or _GENERIC_CONTEXT_FALLBACK
        available = context - prompt_tokens - OUTPUT_FLOOR
        return max(min(available, OUTPUT_CEILING), OUTPUT_FLOOR)

    provider, bare_model = (
        model_name.split("/", 1) if "/" in model_name else ("groq", model_name)
    )

    # Some providers enforce their own output cap regardless of what the
    # underlying model could technically produce (e.g. Groq currently rejects
    # Groq-side requests above 8,192 output tokens for every model CARL
    # exposes there). Single source of truth, shared with the same clamp
    # call_llm applies as a final safety net.
    from llm_interface import _PROVIDER_MAX_OUTPUT_TOKENS
    if provider in _PROVIDER_MAX_OUTPUT_TOKENS:
        return min(_PROVIDER_MAX_OUTPUT_TOKENS[provider], OUTPUT_CEILING)

    if provider == "openrouter":
        context, completion = _fetch_openrouter_limits(bare_model)
        if context is not None:
            available = context - prompt_tokens - OUTPUT_FLOOR
            budget = min(available, completion) if completion else available
            return max(min(budget, OUTPUT_CEILING), OUTPUT_FLOOR)

    # openai / huggingface / anthropic / google, or an unrecognised model:
    # no clean live introspection available — conservative generic default.
    return min(_GENERIC_OUTPUT_FALLBACK, OUTPUT_CEILING)


# ============================================================
# TOKEN ESTIMATION — thin wrappers over get_model_output_budget()
# ============================================================

def estimate_num_predict_from_kg(dataset, taxa, kg, model_name=None,
                                  model_size_gb=None, mode="fast"):
    """Output-token budget for a KG-driven call. model_size_gb is accepted
    for backwards compatibility but no longer used — real per-model/provider
    limits are looked up directly instead of estimated from model size."""
    total_chars = 0
    for taxon in taxa:
        if taxon.name in kg:
            for state in kg[taxon.name]["Characteristics"].values():
                total_chars += len(str(state))
    prompt_tokens = max(1, total_chars // 4)
    return get_model_output_budget(model_name, prompt_tokens)


def estimate_num_predict_from_text(raw_text, model_name=None, mode="fast"):
    """Output-token budget for a specific prompt's actual text. Pass the full
    text that will actually be sent (e.g. for a correction pass, that's the
    raw + current draft + verifier report combined, not just the raw text) —
    the budget is sized from what's really being asked, not a proxy for it.
    """
    prompt_tokens = max(1, len(raw_text) // 4)
    return get_model_output_budget(model_name, prompt_tokens)