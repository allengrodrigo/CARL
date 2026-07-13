from llm_interface import call_llm, call_llm_stream, LLMConfig, DEFAULT_MODELS

CHATBOT_MODEL = DEFAULT_MODELS.get("chat") or "llama3.2:1b"

_CARL_SYSTEM = (
    "You are Carl, a knowledgeable taxonomy assistant. Your role is to answer "
    "questions about taxonomy, systematics, nomenclature, and general biology "
    "accurately and concisely.\n\n"
    "Rules:\n"
    "- Answer only what you know with confidence. If uncertain, say so clearly.\n"
    "- Do not fabricate taxon names, author citations, publication dates, or "
    "identifiers (LSIDs, catalogue numbers, etc.).\n"
    "- Use correct biological terminology.\n"
    "- If a question is outside biology or taxonomy, politely redirect."
)

_CARL_SYSTEM_RAG = (
    "You are Carl, a knowledgeable taxonomy assistant specialised in "
    "nomenclatural codes. Official rules from the relevant Code are provided "
    "below — always cite specific Articles when giving decisions based on them.\n\n"
    "Rules:\n"
    "- Base your answers on the provided rules first; supplement with your "
    "general knowledge only where the rules are silent.\n"
    "- Cite specific Articles or sub-articles when referencing the Code.\n"
    "- Do not fabricate article numbers or rule text not present in the context.\n"
    "- If a question is outside biology or taxonomy, politely redirect."
)

# ── RAG support ───────────────────────────────────────────────────────────────

_rag_cache: dict = {}   # {code: (index, chunks, embed_model, all_embs)}


def _get_rag_context(user_query: str, code: str, k: int = 12) -> str:
    """Lazy-load FAISS index for code, run retrieve_chain, return context string."""
    import numpy as np

    if code not in _rag_cache:
        try:
            from rag_retrieval import load_index, CODE_REGISTRY
            cfg = CODE_REGISTRY.get(code)
            if not cfg:
                print(f"[RAG] Unknown code: {code}")
                return ""
            idx, chunks, embed_model = load_index(cfg["index"], cfg["chunks"])
            all_embs = idx.reconstruct_n(0, idx.ntotal).astype(np.float64)
            _rag_cache[code] = (idx, chunks, embed_model, all_embs)
        except Exception as e:
            print(f"[RAG] Failed to load '{code}' index: {e}")
            return ""

    _, chunks, embed_model, all_embs = _rag_cache[code]

    try:
        from rag_retrieval import retrieve_chain, _article_number_hits, build_context
        q_emb = embed_model.encode([user_query], normalize_embeddings=True)[0].astype(np.float64)
        art_hits = _article_number_hits(user_query, chunks)
        selected, _ = retrieve_chain(q_emb, all_embs, chunks, k, art_hits)
        return build_context([chunks[i] for i in selected])
    except Exception as e:
        print(f"[RAG] Retrieval error: {e}")
        return ""


# ── Message builders ──────────────────────────────────────────────────────────

def _build_messages(user_query: str, history: list, rag_context: str = "") -> list:
    """Build messages array: system prompt + up to 3 prior exchanges + current query."""
    system = _CARL_SYSTEM_RAG if rag_context else _CARL_SYSTEM
    msgs = [{"role": "system", "content": system}]
    for q, r in history:
        msgs.append({"role": "user",      "content": q})
        msgs.append({"role": "assistant", "content": r})
    if rag_context:
        user_content = f"--- OFFICIAL RULES ---\n\n{rag_context}\n\n---\n\n{user_query}"
    else:
        user_content = user_query
    msgs.append({"role": "user", "content": user_content})
    return msgs


# ── Error translation ─────────────────────────────────────────────────────────

def _friendly_error(e: Exception) -> str:
    """Convert a raw exception into a short, actionable message for the chat UI."""
    s = str(e)
    # HTTP status errors from requests
    try:
        status = e.response.status_code  # requests.HTTPError
    except AttributeError:
        status = None
    if status == 413:
        return (
            "Sorry, the request was too large for this model (413 Payload Too Large). "
            "Try reducing k, shortening your message, or switching to a model with a "
            "larger context window."
        )
    if status == 401:
        return (
            "The API key was rejected (401 Unauthorized). "
            "Please check your key in Settings > LM Settings."
        )
    if status == 429:
        return (
            "Rate limit reached (429 Too Many Requests). "
            "Wait a moment and try again, or switch to a different model."
        )
    if status in (502, 503, 504):
        return (
            f"The API service is temporarily unavailable ({status}). "
            "Try again in a few seconds."
        )
    if status:
        return f"The API returned an error ({status}): {s}"
    # Connection / timeout errors
    s_lower = s.lower()
    if "connection" in s_lower or "connectionerror" in s_lower:
        return (
            "Could not reach the API — check your internet connection and try again."
        )
    if "timeout" in s_lower or "timed out" in s_lower:
        return (
            "The request timed out. The model may be overloaded — try again shortly."
        )
    # Fallback: show the raw message but strip the noisy URL part
    import re as _re
    clean = _re.sub(r" for url: https?://\S+", "", s)
    return f"An error occurred: {clean}"


# ── RAR (Retrieval Augmented Response) ───────────────────────────────────────

def get_rar_chunks(user_query: str, code: str, k: int = 12):
    """
    Retrieve raw chunks for direct display (RAR).
    Returns (hit_chunks, code_name).
    Populates _rag_cache as a side effect so ask_stream reuses the loaded index.
    """
    import numpy as np

    if code not in _rag_cache:
        try:
            from rag_retrieval import load_index, CODE_REGISTRY
            cfg = CODE_REGISTRY.get(code)
            if not cfg:
                return [], code.upper()
            idx, chunks, embed_model = load_index(cfg["index"], cfg["chunks"])
            all_embs = idx.reconstruct_n(0, idx.ntotal).astype(np.float64)
            _rag_cache[code] = (idx, chunks, embed_model, all_embs)
        except Exception as e:
            print(f"[RAR] Failed to load '{code}' index: {e}")
            return [], code.upper()

    _, chunks, embed_model, all_embs = _rag_cache[code]

    try:
        from rag_retrieval import retrieve_chain, _article_number_hits, CODE_REGISTRY
        q_emb = embed_model.encode(
            [user_query], normalize_embeddings=True)[0].astype(np.float64)
        art_hits = _article_number_hits(user_query, chunks)
        selected, _ = retrieve_chain(q_emb, all_embs, chunks, k, art_hits)
        code_name = CODE_REGISTRY.get(code, {}).get("name", code.upper())
        return [chunks[i] for i in selected], code_name
    except Exception as e:
        print(f"[RAR] Retrieval error: {e}")
        return [], code.upper()



def format_rar_response(chunks: list, code_name: str) -> str:
    """List retrieved article headings for plain-text display in the chat window."""
    SEP = "─" * 200
    if not chunks:
        return f"[No relevant articles found in {code_name}]"
    seen: set = set()
    headings = []
    for chunk in chunks:
        h = chunk.get("heading", "").strip()
        if h and h not in seen:
            seen.add(h)
            headings.append(h)
    lines = [f"Relevant articles in {code_name}:", SEP, " · ".join(headings), SEP]
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def ask(user_query: str, llm_config=None, history=None) -> str:
    """Non-streaming call (kept for backwards compatibility)."""
    return "".join(ask_stream(user_query, llm_config, history=history))


def ask_stream(user_query: str, llm_config=None, history=None,
               rag_code: str = None, rag_k: int = 12, status_fn=None):
    """
    Generator yielding response tokens.
    If rag_code is provided, prepends retrieved context from that Code's index.
    status_fn(msg) is called with brief status strings during retrieval.
    """
    try:
        user_query = (user_query or "").strip()
        history    = history or []

        model = llm_config.model if llm_config else CHATBOT_MODEL
        chat_config = LLMConfig(
            model=model, temperature=0.1, num_predict=1024,
            style_guide="", think=False, use_chat=True,
        )

        rag_context = ""
        if rag_code:
            if status_fn:
                status_fn("Retrieving context…")
            rag_context = _get_rag_context(user_query, rag_code, k=rag_k)

        messages = _build_messages(user_query, history, rag_context)
        yield from call_llm_stream("", chat_config, messages=messages)

    except Exception as e:
        yield _friendly_error(e)
