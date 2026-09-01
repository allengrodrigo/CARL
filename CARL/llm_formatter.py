"""
LLM Formatter for TaxonGPT.

Responsibilities:
- Convert structured outputs into natural language
- Improve readability of keys and descriptions
- Integrate user-defined stylistic guidance
- NEVER modify underlying biological meaning
"""

import re
import threading
from llm_interface import call_llm

# ============================================================
# PROMPT CONSTRUCTION
# ============================================================

def _build_style_instruction(style: str = "verbose") -> str:
    """Reserved for a future verbose/concise toggle in the UI. Not currently called."""
    if style == "verbose":
        return (
            "Write fluent, cohesive scientific prose combining multiple "
            "character states into well-structured sentences."
        )
    else:
        return (
            "Write concise, grammatically correct scientific prose. "
            "Combine related character states into sentences rather than "
            "listing one character per sentence."
        )


_DEFAULT_STYLE_GUIDE = (
    "Write fluent, cohesive scientific prose appropriate for an academic publication. "
    "Combine multiple character states into well-structured sentences. "
    "Do not add or infer information beyond what is provided."
)


def _build_prompt(raw_text: str, config, style: str = "verbose") -> str:
    style_guide = (config.style_guide or "").strip() or _DEFAULT_STYLE_GUIDE

    return f"""You are a taxonomy assistant.

TASK:
Rewrite the following structured biological description into clear, natural language.

STYLE:
{style_guide}

INPUT:
{raw_text}

OUTPUT RULES:
Return only the final rewritten description. Do not include reasoning,
analysis, Markdown fences, or <think> blocks.

OUTPUT:
"""


def _strip_thinking_text(text: str) -> str:
    """Remove visible reasoning blocks from models that emit <think> text."""
    if not text:
        return text
    text = re.sub(r"<think>.*?</think>", "", text,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _partial_tag_suffix_len(text: str, tag: str) -> int:
    """Length of a trailing text suffix that may be the start of tag."""
    lower = text.lower()
    tag = tag.lower()
    for n in range(min(len(lower), len(tag) - 1), 0, -1):
        if tag.startswith(lower[-n:]):
            return n
    return 0


def _suppress_thinking_tokens(chunks):
    """Yield stream chunks with <think>...</think> sections removed."""
    open_tag = "<think>"
    close_tag = "</think>"
    buffer = ""
    in_think = False
    for chunk in chunks:
        if not chunk:
            continue
        buffer += chunk
        while buffer:
            lower = buffer.lower()
            if in_think:
                end = lower.find(close_tag)
                if end < 0:
                    keep = _partial_tag_suffix_len(buffer, close_tag)
                    buffer = buffer[-keep:] if keep else ""
                    break
                buffer = buffer[end + len(close_tag):]
                in_think = False
                continue

            start = lower.find(open_tag)
            if start < 0:
                keep = _partial_tag_suffix_len(buffer, open_tag)
                emit = buffer[:-keep] if keep else buffer
                buffer = buffer[-keep:] if keep else ""
                if emit:
                    yield emit
                break

            emit = buffer[:start]
            if emit:
                yield emit
            buffer = buffer[start + len(open_tag):]
            in_think = True
    if buffer and not in_think:
        yield buffer

# ============================================================
# KEY REWRITING
# ============================================================

# [a-z] (not [ab]) so multi-arm keylets (1a/1b/1c/1d…) are all parsed.
_LINE_RE = re.compile(r'^(\d+)([a-z])\.\s+(.+?)\s*→\s*(.+)$')
# Rewritten (natural-language) couplet line, no arrow.
_REWRITTEN_LINE_RE = re.compile(r'^(\d+)([a-z])\.\s+(.+)$')


def _lower_first(text: str) -> str:
    """Lowercase the first letter of a character name, leaving acronyms (a
    leading all-caps token of 2+ chars, e.g. PMS, ALS) untouched."""
    text = text.strip()
    if not text:
        return text
    first = text.split(None, 1)[0]
    if len(first) >= 2 and first.isupper():
        return text
    return text[0].lower() + text[1:]


def preformat_key_lines(key_lines):
    """Turn raw arrow couplets into a deterministic If/then scaffold for the LLM.

    ``1a. Type of burrow entrance = trap-door → go to 5``  becomes
    ``1a. If type of burrow entrance = trap-door, then go to 5.``  and a terminal
    ``1b. Chelicerae rastellum = present → Atypus``  becomes
    ``1b. If chelicerae rastellum = present, then the taxon is Atypus.``

    The couplet label, the ``=``/``≠`` condition, and the routing are fixed
    programmatically; only the ``X = Y`` condition is left for the model to
    naturalise. Non-couplet lines pass through unchanged."""
    out = []
    for line in key_lines:
        stripped = line.strip()
        m = _LINE_RE.match(stripped)
        if not m:
            out.append(stripped)
            continue
        num, letter = m.group(1), m.group(2)
        condition = _lower_first(m.group(3).strip())
        dest = m.group(4).strip()
        go_to = re.fullmatch(r"go to\s+(\d+)", dest, re.IGNORECASE)
        tail = f"go to {go_to.group(1)}" if go_to else f"the taxon is {dest}"
        out.append(f"{num}{letter}. If {condition}, then {tail}.")
    return out


_KEY_NATURALIZE_PROMPT = """\
You are polishing the wording of a taxonomic identification key. Each line is
already correctly structured. Rephrase ONLY the condition — the clause written as
"X = Y" (or "X ≠ Y") — into fluent, natural scientific English using the correct
verb (is / are / has / bears / lacks, and so on).

Keep EVERYTHING else exactly as written:
- the couplet label (e.g. "1a."),
- the words "If" and "then",
- every "go to <N>",
- every "the taxon is <name>", and every taxon name and number.

Do not add, remove, merge, or reorder lines. Output only the key lines, one per
input line — no headings, no commentary.

--- KEY LINES ---
{lines}

--- NATURALISED KEY ---
"""


def naturalize_key_stream(scaffold_lines, config, status_fn=None, cancel_fn=None):
    """Stream a naturalised key: the LLM rephrases only the '=' conditions,
    leaving the If/then scaffold, routing, and taxon names intact."""
    from llm_interface import call_llm_stream
    prompt = _KEY_NATURALIZE_PROMPT.format(lines="\n".join(scaffold_lines))
    yield from call_llm_stream(prompt, config, status_fn=status_fn,
                               cancel_fn=cancel_fn)


def _key_routing(line: str):
    """From a scaffold or naturalised key line, extract (label, routing) where
    routing is ('goto', N) or ('taxon', name). Returns None if not a key line."""
    m = re.match(r'^(\d+)([a-z])\.\s+(.*)$', line.strip(), re.IGNORECASE)
    if not m:
        return None
    label = f"{m.group(1)}{m.group(2)}"
    body = m.group(3)
    go_to = re.search(r'\bgo\s+to\s+(\d+)\b', body, re.IGNORECASE)
    if go_to:
        return label, ("goto", go_to.group(1))
    taxon = re.search(r'\bthe\s+taxon\s+is\s+(.+?)\s*\.?\s*$', body, re.IGNORECASE)
    if taxon:
        return label, ("taxon", taxon.group(1).strip().rstrip("."))
    return label, ("none", "")

_COUPLET_PROMPT = """\
Rewrite these couplet lines as complete natural-language sentences.

Rules:
- Keep the couplet label (e.g. 1a., 1b.) at the START of each line, then write "If"
- Replace "=" with the appropriate form of "to be" (are, is, has, etc.)
- Replace "≠" with "are not", "is not", "does not", etc.
- If the destination is "go to N", replace "→ go to N" with ", then go to N"
- If the destination is a taxon name, replace "→ Taxon" with \
", then the taxon is Taxon"
- Preserve the destination (couplet number or taxon name) exactly
- Output only the rewritten lines, nothing else

Example input:
1a. Body colour = red → go to 2
1b. Body colour ≠ red → Araneus
Example output:
1a. If the body colour is red, then go to 2
1b. If the body colour is not red, then the taxon is Araneus

{pair}"""


def _parse_couplet_pairs(key_lines):
    """
    Return an ordered list of (number_str, {'a': raw_line, 'b': raw_line}).
    Lines that do not match the expected pattern are collected under the
    sentinel key '_unparsed' for pass-through.
    """
    pairs = {}
    order = []
    unparsed = []

    for line in key_lines:
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if m:
            num, letter = m.group(1), m.group(2)
            if num not in pairs:
                pairs[num] = {}
                order.append(num)
            pairs[num][letter] = line
        else:
            unparsed.append(line)

    return order, pairs, unparsed


def rewrite_key_by_couplet(key_lines, config, status_fn=None):
    """
    Rewrite a taxonomic key couplet-pair by couplet-pair.
    Each a/b pair is sent to the LLM as a single small prompt so the
    model has enough context to write the If / Otherwise framing correctly.
    Falls back to the raw line if the LLM returns nothing for a pair.
    """
    order, pairs, unparsed = _parse_couplet_pairs(key_lines)

    if not order:
        return "\n".join(key_lines)

    rewritten_blocks = []
    total = len(order)

    for i, num in enumerate(order, 1):
        couplet = pairs[num]
        a_line = couplet.get("a", "")
        b_line = couplet.get("b", "")
        pair_text = "\n".join(filter(None, [a_line, b_line]))

        if status_fn:
            status_fn(f"Rewriting couplet {num} ({i}/{total})...")

        prompt = _COUPLET_PROMPT.format(pair=pair_text)

        try:
            result = call_llm(prompt, config)
            rewritten_blocks.append(result.strip() if result and result.strip()
                                    else pair_text)
        except Exception as e:
            print(f"[Key rewrite] couplet {num} error: {e}")
            rewritten_blocks.append(pair_text)

    return "\n".join(rewritten_blocks)

# ============================================================
# OUTPUT CLEANING
# ============================================================

def clean_key_output(text: str) -> str:
    """
    Clean LLM-generated key output.
    """
    lines = text.split("\n")
    cleaned = []

    for line in lines:
        line = line.strip()

        # Remove unwanted headers
        if line.lower().startswith("here is"):
            continue

        # Remove brackets
        line = line.replace("[", "").replace("]", "")

        cleaned.append(line)

    return "\n".join(cleaned)


# ============================================================
# VERIFICATION
# ============================================================

_NO_ISSUES_SENTINEL = "NO ISSUES FOUND"


def _is_no_issues_sentinel(text: str) -> bool:
    return bool(text) and text.strip().rstrip(".").upper() == _NO_ISSUES_SENTINEL


def _looks_like_no_issues_verdict(text: str) -> bool:
    """Recognise common non-compliant ways models say the verification passed."""
    if not text:
        return False
    if _is_no_issues_sentinel(text):
        return True
    tail = re.sub(r"\s+", " ", text.strip())[-1800:].lower()
    patterns = (
        r"\bthere (?:are|is) no (?:real |substantive |remaining |actual )?"
        r"(?:issues?|discrepanc(?:y|ies)|errors?|problems?)\b",
        r"\bno (?:real |substantive |remaining |actual )?"
        r"(?:issues?|discrepanc(?:y|ies)|errors?|problems?) "
        r"(?:were |are |was |is )?(?:found|detected|identified|reported|present)\b",
        r"\bi (?:do not|don't) (?:see|find|identify) any (?:real |substantive |actual )?"
        r"(?:issues?|discrepanc(?:y|ies)|errors?|problems?)\b",
        r"\bno incorrect interpretations of character states\b",
        r"\bdoes not introduce any new information or hallucinations\b",
        r"\bmeaning is preserved\b",
        r"\bmeaning was preserved\b",
    )
    return any(re.search(pattern, tail) for pattern in patterns)


def _extract_verification_section(text: str) -> str | None:
    match = re.search(r"\[Verification\]\s*(.*)\Z", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None


def _strip_verifier_wrappers(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:text|markdown)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    return text


def _normalise_verification_output(raw: str) -> str:
    """Convert verifier output to either the pass sentinel, an issue list, or a no-verdict marker."""
    raw = _strip_verifier_wrappers(raw or "")
    if not raw:
        return raw

    verification_body = _extract_verification_section(raw)
    if verification_body is not None:
        if _is_no_issues_sentinel(verification_body) or _looks_like_no_issues_verdict(verification_body):
            return _NO_ISSUES_SENTINEL
        if verification_body:
            return verification_body
        # Reasoning models sometimes leave the final section empty but state
        # their verdict in the reasoning.  Treat only clear pass language as a pass.
        if _looks_like_no_issues_verdict(raw):
            return _NO_ISSUES_SENTINEL
        return "[Verifier produced reasoning but no final verdict. Use a non-reasoning verifier model or increase the verifier token budget.]"

    if _is_no_issues_sentinel(raw):
        return _NO_ISSUES_SENTINEL

    # Small/local models sometimes append the pass sentinel to an actual issue
    # list.  Accept the sentinel only if the remaining text also reads as a pass.
    if _NO_ISSUES_SENTINEL in raw:
        without_sentinel = raw.replace(_NO_ISSUES_SENTINEL, "").strip()
        if without_sentinel and not _looks_like_no_issues_verdict(without_sentinel):
            return without_sentinel
        return _NO_ISSUES_SENTINEL

    if _looks_like_no_issues_verdict(raw):
        return _NO_ISSUES_SENTINEL

    return raw


def verification_display_text(verification: str, include_reasoning: bool = True) -> str:
    """Return a user-facing verification report.

    Keys and other single-shot analyses can keep the full reasoning-rich report.
    Repeated description runs can suppress reasoning so each taxon does not fill
    the output pane with verifier chain-of-thought.
    """
    raw = _strip_verifier_wrappers(verification or "")
    if not raw:
        return ""
    if include_reasoning:
        return raw

    raw = _strip_thinking_text(raw)
    verification_body = _extract_verification_section(raw)
    if verification_body is not None and verification_body.strip():
        return verification_body.strip()
    return _normalise_verification_output(raw)


def verify_output_with_llm(raw_text, formatted_text, config, status_fn=None, cancel_fn=None):
    import copy

    prompt = f"""
You are a critical scientific reviewer.

Your task is to rigorously compare the REWRITTEN text against the ORIGINAL text.

CRITICAL BALANCE RULE:
- Only report an issue if you are confident it is a real discrepancy.
- Do NOT invent issues to satisfy the task.
- If a statement is semantically equivalent to the original, it is NOT an issue.
- Avoid trivial or redundant criticisms.

PRECISION RULE:
- DO NOT flag spelling unless clearly incorrect.
- DO NOT flag wording differences if meaning is preserved.
- Prefer fewer, high-confidence issues over many weak ones.
- DO check for incorrect interpretations of character states
- DO check for missing information present in the original
- DO check for added (hallucinated) information or misleading rephrasings
- DO report an issue if the REWRITTEN text merely reproduces the ORIGINAL's
  structured or coded format instead of fluent natural-language prose

OUTPUT RULES (STRICT):

You must produce EXACTLY ONE of the following:

CASE 1 — Issues exist:
- Output ONLY a list of issues.
- Do NOT include "NO ISSUES FOUND".
- Do NOT include any additional commentary.

CASE 2 — No issues exist:
- Output EXACTLY:
NO ISSUES FOUND

Do NOT combine the two cases.
Do NOT add anything before or after the output.
Do NOT include reasoning, analysis, explanations, headings, Markdown, or labels.
If your reasoning concludes that the rewrite is semantically equivalent to the
original, your entire final answer must be exactly one line:
NO ISSUES FOUND

--- ORIGINAL ---
{raw_text}

--- REWRITTEN ---
{formatted_text}

--- CRITIQUE ---
"""

    # Compute required Ollama context: prompt tokens + output budget + headroom.
    # Uses ~4 chars/token as a conservative estimate.
    prompt_tokens = len(prompt) // 4
    output_budget = config.num_predict or 2048
    required_ctx = max(4096, prompt_tokens + output_budget + 256)

    cfg = copy.copy(config)
    cfg.num_ctx = required_ctx

    raw = call_llm(prompt, cfg, use_chat=config.use_chat, status_fn=status_fn, cancel_fn=cancel_fn).strip()

    # Handle <think>...</think> blocks from reasoning models (e.g. qwen3).
    #
    # Complete block: show reasoning as a labelled section above the output,
    # since the reviewer's chain-of-thought is often useful to the user.
    #
    # Incomplete block (</think> missing): the model hit its token limit
    # mid-reasoning and never produced output — discard the fragment and
    # surface a clear message rather than showing a wall of raw CoT.
    think_re = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)
    think_match = think_re.search(raw)
    if think_match:
        reasoning  = think_match.group(1).strip()
        after      = think_re.sub("", raw).strip()
        if after:
            raw = f"[Reasoning]\n{reasoning}\n\n[Verification]\n{after}"
        else:
            raw = reasoning   # edge case: think block with no trailing output
    elif re.search(r"<think>", raw, re.IGNORECASE):
        # Truncated mid-reasoning — discard the fragment
        raw = ("[Reasoning truncated — verifier ran out of tokens.\n"
               "Increase the verifier token budget in the LLM tab.]")

    # Return the display text, not the normalized verdict.  The UI still shows
    # detailed verifier reasoning when a reasoning model provides it, while
    # verification_passed()/verification_has_issues() normalize internally for
    # control-flow decisions.
    return raw


# ============================================================
# ITERATED VERIFICATION — verdict parsing + correction
# ============================================================

def verification_passed(verification: str) -> bool:
    """True only for the verifier's explicit success sentinel."""
    if not verification:
        return False
    return _is_no_issues_sentinel(_normalise_verification_output(verification))


def verification_has_issues(verification: str) -> bool:
    """True only when the verification is a usable issue report (not a pass,
    not a failure/timeout marker)."""
    if not verification:
        return False
    normalized = _normalise_verification_output(verification).strip()
    if _is_no_issues_sentinel(normalized):
        return False
    failure_markers = ("[Reasoning truncated", "[Verifier produced reasoning")
    return not normalized.startswith(failure_markers)


_PROSE_CORRECTION_PROMPT = """\
You are correcting a rewritten scientific {analysis_kind}.

GOAL: produce a fluent, natural-language scientific {analysis_kind} in readable
prose. The reader must see prose — never a list of codes, and never a copy of
the structured source data.

The ORIGINAL OUTPUT below is your authoritative fact-check reference — the sole
source for every character, state, count, comparison, taxon name, and qualifier.
Match its FACTS exactly, but NOT its format: do not reproduce its layout,
headings, or code-like phrasing.

Correct every issue the reviewer identified, and change ONLY what is needed to
fix those issues — leave all other sentences as they are, so corrections do not
introduce new discrepancies.

Rules:
- Return the COMPLETE corrected output, not only the changed sentences.
- Preserve every taxon name, character, state, count, comparison, qualifier, and
  conclusion present in the original output.
- When the reviewer says information is missing, add that fact in natural prose —
  do NOT paste raw lines to satisfy the reviewer.
- Do not add facts, interpretations, or certainty absent from the original output.
- Do not omit source information merely to avoid a reviewer issue.
- Keep the same scientific prose style as the current rewrite.
- Output only the corrected prose. Do not add a heading or commentary.

--- ORIGINAL OUTPUT (facts only; do not copy its format) ---
{raw_text}

--- CURRENT REWRITE (fix only the flagged issues) ---
{formatted_text}

--- REVIEWER ISSUES ---
{verification}

--- COMPLETE CORRECTED OUTPUT (natural-language prose) ---
"""


def _clean_corrected_prose(text: str) -> str:
    """Strip reasoning wrappers and Markdown fences from corrected prose."""
    text = re.sub(r"<think>.*?</think>", "", text,
                  flags=re.DOTALL | re.IGNORECASE).strip()
    text = re.sub(r"^```(?:text|markdown)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    if not text or verification_passed(text):
        raise ValueError("the correction model returned no usable prose")
    return text


def correct_prose_with_llm(raw_text, formatted_text, verification, config,
                           analysis_kind="analysis", status_fn=None, cancel_fn=None):
    """Correct a prose rewrite using the deterministic output as evidence.
    Runs on the WRITER config (which carries the style guide), not the verifier."""
    import copy
    verification = _normalise_verification_output(verification)
    prompt = _PROSE_CORRECTION_PROMPT.format(
        analysis_kind=analysis_kind, raw_text=raw_text,
        formatted_text=formatted_text, verification=verification)
    prompt_tokens = len(prompt) // 4
    output_budget = config.num_predict or 2048
    cfg = copy.copy(config)
    cfg.num_ctx = max(4096, prompt_tokens + output_budget + 256)
    response = call_llm(prompt, cfg, use_chat=config.use_chat, status_fn=status_fn, cancel_fn=cancel_fn)
    return _clean_corrected_prose(response)


_KEY_CORRECTION_PROMPT = """\
You are correcting a rewritten taxonomic identification key.

Use the ORIGINAL KEY as the sole source of biological meaning and routing.
Correct every issue identified by the reviewer while retaining clear,
natural-language sentences.

Rules:
- Return the COMPLETE corrected key, including every couplet line.
- Preserve every couplet label (for example 1a. and 1b.) exactly.
- Preserve every destination exactly: each "go to N" must still go to the same
  N, and every terminal taxon name must be unchanged.
- Do not add, remove, or reorder couplets.
- Do not add facts that are absent from the original key.
- Output only the corrected key lines. Do not add a heading or commentary.

--- ORIGINAL KEY ---
{raw_text}

--- CURRENT REWRITE ---
{formatted_text}

--- REVIEWER ISSUES ---
{verification}

--- CORRECTED KEY ---
"""


def _clean_corrected_key(text: str) -> str:
    """Extract only numbered couplet lines from a correction response."""
    text = re.sub(r"<think>.*?</think>", "", text,
                  flags=re.DOTALL | re.IGNORECASE)
    text = text.replace("```text", "").replace("```", "")
    return "\n".join(
        line.strip() for line in text.splitlines()
        if _REWRITTEN_LINE_RE.match(line.strip()))


def validate_corrected_key(raw_text: str, corrected_text: str):
    """Check that a corrected key preserves every couplet label and its routing
    ('go to N' / 'the taxon is X'). Works on the If/then scaffold format."""
    expected = [r for line in raw_text.splitlines()
                if (r := _key_routing(line)) is not None]
    if not expected:
        return False, "the original key contains no parseable couplet lines"

    actual, actual_labels = {}, []
    for line in corrected_text.splitlines():
        r = _key_routing(line)
        if r:
            actual_labels.append(r[0])
            actual[r[0]] = r[1]

    if actual_labels != [label for label, _ in expected]:
        return False, "couplet labels are missing, duplicated, or reordered"
    for label, route in expected:
        got = actual.get(label)
        kind, value = route
        if kind == "goto":
            if got != ("goto", value):
                return False, f"{label} does not preserve routing 'go to {value}'"
        elif kind == "taxon":
            if not got or got[0] != "taxon" or value.casefold() not in got[1].casefold():
                return False, f"{label} does not preserve terminal taxon '{value}'"
    return True, ""


def correct_key_with_llm(raw_text, formatted_text, verification, config,
                         status_fn=None, cancel_fn=None):
    """Correct a rewritten key; reject responses that break routing."""
    import copy
    verification = _normalise_verification_output(verification)
    prompt = _KEY_CORRECTION_PROMPT.format(
        raw_text=raw_text, formatted_text=formatted_text,
        verification=verification)
    prompt_tokens = len(prompt) // 4
    output_budget = config.num_predict or 2048
    cfg = copy.copy(config)
    cfg.num_ctx = max(4096, prompt_tokens + output_budget + 256)
    response = call_llm(prompt, cfg, use_chat=config.use_chat, status_fn=status_fn, cancel_fn=cancel_fn)
    corrected = _clean_corrected_key(response)
    valid, reason = validate_corrected_key(raw_text, corrected)
    if not valid:
        raise ValueError(reason)
    return corrected


# ============================================================
# DIAGNOSIS FORMATTER
# ============================================================

_DIAGNOSIS_PROMPT = """\
You are a taxonomic expert producing a formal written diagnosis.

Using the character and state labels provided (never numeric codes), write:

1. DIAGNOSIS — Present each level of unique character-state combination \
(1-state, 2-state, 3-state) in clear scientific prose. Start with the most \
parsimonious level. Use formal taxonomy language: \
"{taxon} differs from all other members of the comparison group by..."

2. NEAREST NEIGHBOURS — For each nearest neighbour listed, write a sentence \
describing how many states differ and name the specific characters that separate them.

3. If the taxon is UNDIAGNOSABLE, explain clearly what this implies about the \
available character sampling.

Structured input:
{raw_text}"""


def format_diagnosis(raw_text: str, config, status_fn=None) -> str:
    """LLM rendering for diagnose_taxon output."""
    first_line = raw_text.split("\n", 1)[0]
    taxon = first_line.replace("DIAGNOSIS OF:", "").strip()
    prompt = _DIAGNOSIS_PROMPT.format(taxon=taxon, raw_text=raw_text)
    try:
        return call_llm(prompt, config, use_chat=False, status_fn=status_fn).strip()
    except Exception as e:
        print(f"[format_diagnosis error] {e}")
        return raw_text


# ============================================================
# PREAMBLE BUILDER
# ============================================================

# Taxonomy ranks in display order for the hierarchy line
_HIERARCHY_RANKS = [
    "kingdom", "phylum", "class", "subclass", "order", "suborder",
    "infraorder", "superfamily", "family", "subfamily", "tribe",
    "subtribe", "genus", "subgenus",
]

# Fields consumed by the structured blocks; everything else is appended as key: value
_STRUCTURED_FIELDS: frozenset = frozenset({
    "scientificName", "scientificNameAuthorship", "namePublishedInYear",
    "originalNameUsage",
    "typeStatus", "sex", "locality", "municipality", "county",
    "stateProvince", "country", "catalogNumber", "institutionCode",
    "collectionCode", "otherCatalogNumbers",
    *_HIERARCHY_RANKS,
})

_NO_INFO = "No information"
_NO_DATA_SENTINEL = "No Information Available"   # emitted by literature_cache when no value found


def _fv(fields: dict, term: str) -> str | None:
    """Return the cached value for a Darwin Core term, or None if absent/empty/sentinel."""
    entry = fields.get(term)
    if not entry:
        return None
    v = entry.get("value", "").strip()
    return None if (not v or v == _NO_DATA_SENTINEL) else v


def build_preamble(entry: dict, include_fields: set, variant: str = "raw",
                   synonyms_text: str = "") -> str:
    """
    Build a taxonomic preamble string from a Darwin Core cache entry.

    variant="raw" — all included fields shown; missing values shown as "No information"
    variant="llm" — fields with no data are silently omitted
    """
    from literature_cache import is_new_format

    omit = (variant == "llm")
    fields = entry.get("fields", {}) if is_new_format(entry) else {}

    def get(term: str) -> str | None:
        return _fv(fields, term)

    lines: list[str] = []

    # --- Line 1: Scientific name  Authors  Date ---
    name       = get("scientificName") or "(unknown)"
    authorship = get("scientificNameAuthorship")
    year       = get("namePublishedInYear")

    if authorship:
        lines.append(f"{name} {authorship}")
    elif year:
        lines.append(f"{name} ({year})" if omit else
                     f"{name} ({_NO_INFO}: authorship, {year})")
    else:
        lines.append(name if omit else f"{name} ({_NO_INFO}: authorship)")

    # --- Line 2: Hierarchy ---
    hierarchy = [get(r) for r in _HIERARCHY_RANKS if r in include_fields and get(r)]
    if hierarchy:
        lines.append(": ".join(hierarchy))
    elif not omit:
        lines.append(_NO_INFO)

    lines.append("")

    # --- Synonyms block ---
    if synonyms_text:
        lines.append("Synonyms:")
        lines.append(synonyms_text)
    else:
        synonym = get("originalNameUsage") if "originalNameUsage" in include_fields else None
        if synonym and synonym != get("scientificName"):
            lines.append("Synonyms:")
            lines.append(synonym)
        elif not omit:
            lines.append(f"Synonyms: {_NO_INFO}")

    # --- Type specimens block ---
    type_fields = {
        "typeStatus", "sex", "locality", "municipality", "county",
        "stateProvince", "country", "catalogNumber",
        "institutionCode", "collectionCode", "otherCatalogNumbers",
    }
    type_included = bool(type_fields & include_fields)

    type_status = get("typeStatus") if "typeStatus" in include_fields else None
    sex_val     = get("sex")        if "sex"        in include_fields else None

    loc_parts: list[str] = []
    for term in ("locality", "municipality", "county", "stateProvince", "country"):
        if term in include_fields:
            v = get(term)
            if v:
                loc_parts.append(v)

    cat_parts: list[str] = []
    inst  = get("institutionCode")    if "institutionCode"    in include_fields else None
    coll  = get("collectionCode")     if "collectionCode"     in include_fields else None
    cat   = get("catalogNumber")      if "catalogNumber"      in include_fields else None
    other = get("otherCatalogNumbers") if "otherCatalogNumbers" in include_fields else None

    if inst and coll and cat:
        cat_parts.append(f"{inst}-{coll}-{cat}")
    elif inst and cat:
        cat_parts.append(f"{inst}-{cat}")
    elif cat:
        cat_parts.append(cat)
    if other:
        cat_parts.extend(c.strip() for c in other.split(";") if c.strip())

    has_type_data = bool(type_status or sex_val or loc_parts or cat_parts)

    if has_type_data:
        specimen_parts: list[str] = []
        if type_status:
            label = type_status.title()
            specimen_parts.append(f"{label} {sex_val.lower()}" if sex_val else label)
        elif sex_val:
            specimen_parts.append(sex_val.lower())
        if loc_parts:
            specimen_parts.append(", ".join(loc_parts))
        specimen_str = ", ".join(specimen_parts)
        if cat_parts:
            specimen_str += f" [{'; '.join(cat_parts)}]"
        lines.append("")
        lines.append(specimen_str + ".")
    elif type_included and not omit:
        lines.append("")
        lines.append(f"Type specimens: {_NO_INFO}")

    # --- Appended key: value lines for remaining included fields ---
    append_fields = sorted(f for f in include_fields if f not in _STRUCTURED_FIELDS)
    appended: list[str] = []
    for term in append_fields:
        v = get(term)
        if v:
            appended.append(f"{term}: {v}")
        elif not omit:
            appended.append(f"{term}: {_NO_INFO}")
    if appended:
        lines.append("")
        lines.extend(appended)

    return "\n".join(lines).rstrip()


# ============================================================
# LITERATURE-ENRICHED DESCRIPTION FORMATTER
# ============================================================

_LIT_DESCRIPTION_PROMPT = """\
You are a taxonomy assistant.

TASK:
Rewrite the following structured biological description into clear, natural language.

STYLE:
{style_guide}

TAXONOMIC CONTEXT for {taxon}:
{literature}

Do NOT invent any information not present in the sources above.

INPUT:
{raw_text}

OUTPUT RULES:
Return only the final rewritten description. Do not include reasoning,
analysis, Markdown fences, or <think> blocks.

OUTPUT:
"""


def format_with_literature(raw_text: str, literature: str, taxon_name: str,
                            config, style: str = "verbose", status_fn=None) -> str:
    """Format a taxon description enriched with cached literature data."""
    lit_text = (literature.strip()
                if literature and literature.strip()
                else "(no literature data available)")
    style_guide = (config.style_guide or "").strip() or _DEFAULT_STYLE_GUIDE
    prompt = _LIT_DESCRIPTION_PROMPT.format(
        taxon=taxon_name.replace("_", " "),
        style_guide=style_guide,
        raw_text=raw_text,
        literature=lit_text,
    )
    try:
        return _strip_thinking_text(
            call_llm(prompt, config, use_chat=False, status_fn=status_fn)
        )
    except Exception as e:
        print(f"[format_with_literature error] {e}")
        return raw_text


# ============================================================
# STREAMING VARIANTS
# ============================================================

def format_fast_stream(raw_text, config, style="concise", status_fn=None,
                       cancel_fn=None, suppress_reasoning=True):
    """Streams fluent-prose formatting of raw_text. Yields string tokens."""
    from llm_interface import call_llm_stream
    prompt = _build_prompt(raw_text, config, style)
    stream = call_llm_stream(prompt, config, status_fn=status_fn,
                             cancel_fn=cancel_fn)
    yield from (_suppress_thinking_tokens(stream) if suppress_reasoning else stream)


def format_with_literature_stream(raw_text, literature, taxon_name, config,
                                   style: str = "verbose", status_fn=None,
                                   cancel_fn=None, suppress_reasoning=True):
    """Streaming variant of format_with_literature. Yields string tokens."""
    from llm_interface import call_llm_stream
    lit_text = (literature.strip() if literature and literature.strip()
                else "(no literature data available)")
    prompt = _LIT_DESCRIPTION_PROMPT.format(
        taxon=taxon_name.replace("_", " "),
        style_guide=config.style_guide or "(none provided)",
        style_instruction=_build_style_instruction(style),
        raw_text=raw_text,
        literature=lit_text,
    )
    stream = call_llm_stream(prompt, config, status_fn=status_fn,
                             cancel_fn=cancel_fn)
    yield from (_suppress_thinking_tokens(stream) if suppress_reasoning else stream)


def format_diagnosis_stream(raw_text, config, status_fn=None, cancel_fn=None,
                            suppress_reasoning=True):
    """Streaming variant of format_diagnosis. Yields string tokens."""
    from llm_interface import call_llm_stream
    first_line = raw_text.split("\n", 1)[0]
    taxon = first_line.replace("DIAGNOSIS OF:", "").strip()
    prompt = _DIAGNOSIS_PROMPT.format(taxon=taxon, raw_text=raw_text)
    stream = call_llm_stream(prompt, config, status_fn=status_fn,
                             cancel_fn=cancel_fn)
    yield from (_suppress_thinking_tokens(stream) if suppress_reasoning else stream)


def rewrite_key_stream(key_lines, config, status_fn=None, cancel_fn=None):
    """Streaming variant of rewrite_key_by_couplet.

    Accumulates each couplet's tokens, cleans them, then yields the cleaned
    couplet text so per-couplet progress is visible without needing a
    post-processing replace pass on already-inserted tokens.
    """
    order, pairs, unparsed = _parse_couplet_pairs(key_lines)
    if not order:
        yield "\n".join(key_lines)
        return
    from llm_interface import call_llm_stream
    for num in order:
        couplet = pairs[num]
        pair_text = "\n".join(filter(None, [couplet.get("a", ""), couplet.get("b", "")]))
        prompt = _COUPLET_PROMPT.format(pair=pair_text)
        try:
            tokens = list(call_llm_stream(prompt, config, status_fn=status_fn,
                                          cancel_fn=cancel_fn))
            yield clean_key_output("".join(tokens)).strip() + "\n"
        except Exception as e:
            print(f"[rewrite_key_stream] couplet {num} error: {e}")
            yield pair_text + "\n"
