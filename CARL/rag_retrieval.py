"""
rag_retrieval.py

Production RAG retrieval module for CARL.
All retrieval logic lives here; sandbox and experiment scripts import from this.

Public API:
  CODE_REGISTRY  — maps code keys to index paths and system prompts
  load_index()   — loads FAISS index, chunks, and embedding model from disk
  build_context()— formats retrieved chunks into a context string for the LLM
  retrieve_chain()— greedy citation-chain retrieval (production algorithm)
"""

import os
import re
import sys
import json
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

EMBED_MODEL = "all-MiniLM-L6-v2"


def _data_path(filename: str) -> str:
    """Absolute path to an index/chunks file that sits beside this module, so that
    retrieval does not depend on the directory CARL was launched from."""
    if os.path.isabs(filename):
        return filename
    base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)

# Article/rule number pattern: 23, 23.9, 11.3.2, 5a, F.1, H.3
_ART_NUM_RE = re.compile(r"\b([FH]\.\d+|\d+[a-z]?(?:\.\d+[a-z]?){0,3})\b")

CODE_REGISTRY = {
    "iczn": {
        "name":     "International Code of Zoological Nomenclature (ICZN)",
        "markdown": "ICZN.md",
        "index":    "iczn_index.faiss",
        "chunks":   "iczn_chunks.json",
        "system": (
            "You are an expert nomenclatural assistant specialised in the "
            "International Code of Zoological Nomenclature (ICZN). "
            "Answer using ONLY the articles provided in the context below. "
            "Always cite specific Article numbers for every claim. "
            "If the context does not contain enough information to answer "
            "fully, say so explicitly."
        ),
    },
    "icn": {
        "name":     "International Code of Nomenclature for algae, fungi and plants (ICN)",
        "markdown": "ICN.md",
        "index":    "icn_index.faiss",
        "chunks":   "icn_chunks.json",
        "system": (
            "You are an expert nomenclatural assistant specialised in the "
            "International Code of Nomenclature for algae, fungi and plants "
            "(ICN / Madrid Code). "
            "Answer using ONLY the articles provided in the context below. "
            "Always cite specific Article numbers for every claim. "
            "If the context does not contain enough information to answer "
            "fully, say so explicitly."
        ),
    },
    "icnp": {
        "name":     "International Code of Nomenclature of Prokaryotes (ICNP)",
        "markdown": "ICNP.md",
        "index":    "icnp_index.faiss",
        "chunks":   "icnp_chunks.json",
        "system": (
            "You are an expert nomenclatural assistant specialised in the "
            "International Code of Nomenclature of Prokaryotes (ICNP). "
            "Answer using ONLY the rules provided in the context below. "
            "Always cite specific Rule, Principle, or Chapter numbers. "
            "If the context does not contain enough information to answer "
            "fully, say so explicitly."
        ),
    },
    "icvcn": {
        "name":     "International Code of Virus Classification and Nomenclature (ICVCN)",
        "markdown": "ICVCN.md",
        "index":    "icvcn_index.faiss",
        "chunks":   "icvcn_chunks.json",
        "system": (
            "You are an expert nomenclatural assistant specialised in the "
            "International Code of Virus Classification and Nomenclature (ICVCN). "
            "Answer using ONLY the rules provided in the context below. "
            "Always cite specific Rule numbers for every claim. "
            "If the context does not contain enough information to answer "
            "fully, say so explicitly."
        ),
    },
}


# ── Index I/O ─────────────────────────────────────────────────────────────────

def load_index(index_file: str, chunks_file: str):
    """Load FAISS index, chunk list, and embedding model from disk.
    Returns (index, chunks, model)."""
    index_file, chunks_file = _data_path(index_file), _data_path(chunks_file)
    print(f"Loading index: {index_file}")
    index = faiss.read_index(index_file)
    with open(chunks_file, "r", encoding="utf-8") as f:
        chunks = json.load(f)
    model = SentenceTransformer(EMBED_MODEL)
    return index, chunks, model


def build_context(hits: list) -> str:
    """Format a list of chunk dicts into a context string for the LLM."""
    return "\n\n---\n\n".join(
        f"[{c['heading']}]\n{c['text']}" for c in hits
    )


# ── Retrieval helpers ─────────────────────────────────────────────────────────

def _article_number_hits(query: str, chunks: list) -> list:
    """Return indices of chunks whose heading matches an article number in query."""
    nums = set(_ART_NUM_RE.findall(query))
    hits, seen = [], set()
    for i, chunk in enumerate(chunks):
        for num in nums:
            if re.search(rf"\b{re.escape(num)}\b", chunk["heading"], re.IGNORECASE):
                if i not in seen:
                    hits.append(i)
                    seen.add(i)
                break
    return hits


def _cosine_sims(Q_vec: np.ndarray, embs: np.ndarray,
                 eps: float = 1e-10) -> np.ndarray:
    Q_norm = Q_vec / (np.linalg.norm(Q_vec) + eps)
    norms  = np.linalg.norm(embs, axis=1)
    return (embs @ Q_norm) / (norms + eps)


# ── Production retrieval algorithm ───────────────────────────────────────────

def retrieve_chain(query_emb: np.ndarray, all_embs: np.ndarray,
                   chunks: list, k: int, seeds: list):
    """
    Greedy citation-chain retrieval.

    1. Seed with programmatic hits (if any); start chain from the hit with
       highest cosine(Q). If no hits, first chain start is argmax cosine(Q).
    2. At each step: collect ALL unseen chunks referenced in C_current
       (articles and sub-articles via _ART_NUM_RE), pick the one with highest
       cosine(Q), add it, continue chain from it.
    3. If no unseen references remain: fall back to argmax cosine(Q, unseen)
       as a new chain start.
    4. Repeat until k chunks selected. Deduplication via seen set.

    Returns (selected, cited) where cited is the set of citation-chased indices.
    """
    EPS       = 1e-10
    Q         = query_emb.astype(np.float64)
    selected  = []
    seen      = set()
    cited     = set()
    remaining = list(range(len(chunks)))

    def _add(idx):
        selected.append(idx)
        seen.add(idx)
        if idx in remaining:
            remaining.remove(idx)

    def _best(indices):
        arr  = np.array(indices)
        sims = _cosine_sims(Q, all_embs[arr], EPS)
        return int(arr[np.argmax(sims)])

    def _references(idx):
        nums  = set(_ART_NUM_RE.findall(chunks[idx]["text"]))
        found = set()
        for i, chunk in enumerate(chunks):
            if i in seen:
                continue
            for num in nums:
                if re.search(rf"\b{re.escape(num)}\b", chunk["heading"], re.IGNORECASE):
                    found.add(i)
                    break
        return list(found)

    for idx in seeds:
        if idx not in seen and len(selected) < k:
            _add(idx)

    if selected:
        C_current = _best(list(selected))
    elif remaining:
        C_current = _best(remaining)
        _add(C_current)
    else:
        return selected, cited

    while len(selected) < k and remaining:
        refs = _references(C_current)
        if refs:
            C_next = _best(refs)
            _add(C_next)
            cited.add(C_next)
            C_current = C_next
        else:
            C_current = _best(remaining)
            _add(C_current)

    return selected, cited
