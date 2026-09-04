"""Phase 7 — PLP retrieval. Cites NABARD's own district credit plan.

Degrades to nothing if the index is absent: `available()` returns False, the
ranker falls back to market+risk scoring only, and the UI must not claim PLP
backing. PART 3.4 is explicit about that.

Retrieval is local (sentence-transformers over a saved matrix). No network, so
this works inside the offline district bundle.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

INDEX = Path(__file__).resolve().parents[1] / "data" / "derived" / "plp_index"


def available() -> bool:
    return (INDEX / "vectors.npy").exists() and (INDEX / "chunks.json").exists()


@lru_cache(maxsize=1)
def _load():
    vecs = np.load(INDEX / "vectors.npy")
    chunks = json.loads((INDEX / "chunks.json").read_text(encoding="utf-8"))
    meta = json.loads((INDEX / "meta.json").read_text(encoding="utf-8"))
    return vecs, chunks, meta


@lru_cache(maxsize=1)
def _model():
    """Only the SEMANTIC fallback needs this. Exact section retrieval does not,
    so the deployed image can skip a multi-GB torch install; `search()`
    degrades to returning nothing rather than failing."""
    from sentence_transformers import SentenceTransformer
    _, _, meta = _load()
    return SentenceTransformer(meta["model"])


def semantic_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return available()
    except ImportError:
        return False


FRONT_MATTER_PENALTY = 0.15


def search(query: str, k: int = 3, min_score: float = 0.30) -> list[dict]:
    """Top-k PLP passages for a query, with page numbers for citation.

    Front matter is penalised rather than deleted: the PLP's preamble is
    genuinely similar to any sector query, and citing "every effort has been
    made" as NABARD backing for goat rearing would be worse than citing
    nothing at all.
    """
    if not semantic_available():
        return []
    vecs, chunks, meta = _load()
    q = _model().encode([query], normalize_embeddings=True)[0]
    sims = vecs @ q
    sims = sims - np.array(
        [FRONT_MATTER_PENALTY if c.get("is_front_matter") else 0.0
         for c in chunks], dtype=np.float32)
    order = np.argsort(-sims)[:k]
    out = []
    for i in order:
        if float(sims[i]) < min_score:
            continue
        c = chunks[int(i)]
        out.append({
            "score": round(float(sims[i]), 4),
            "heading": c["heading"],
            "page": c["page"],
            "text": c["text"][:600],
            "document": meta["document"],
        })
    return out


def by_section(prefixes: list[str], k: int = 2) -> list[dict]:
    """Exact retrieval by PLP section number.

    The PLP has a table of contents; which section covers dairy is a fact a
    human can read off it, not something to infer from cosine similarity.
    Transcribing it is the same discipline as transcribing the scheme rules,
    and it makes the citation deterministic and auditable.
    """
    if not available():
        return []
    _, chunks, meta = _load()
    out = []
    for c in chunks:
        head = c["heading"]
        if any(head.startswith(p + " ") or head.startswith(p + ".")
               for p in prefixes):
            out.append({"score": None, "heading": head, "page": c["page"],
                        "text": c["text"][:600], "document": meta["document"],
                        "match": "section"})
    return out[:k]


def cite_sector(sector: dict, k: int = 2) -> dict:
    """PLP evidence for one sector, shaped for the alternatives ranker."""
    if not available():
        return {"available": False, "citations": [],
                "note": "PLP index not built; ranking uses market and risk "
                        "scoring only and makes no claim of NABARD backing."}
    name = sector["display_name"]["en"]
    hits = by_section(sector.get("plp_sections") or [], k=k)
    how = "section"
    if not hits:
        query = sector.get("plp_query") or (
            f"{name} credit potential status of the sector in the district")
        hits = search(query, k=k)
        how = "semantic"
    if not hits:
        return {"available": True, "citations": [],
                "note": f"No PLP passage matched '{name}' above the relevance "
                        "threshold. No NABARD backing is claimed for this sector."}
    return {
        "available": True,
        "citations": [{"_citation": True,
                       "document": h["document"], "section": h["heading"],
                       "page": h["page"], "score": h["score"],
                       "match": h.get("match", "semantic"),
                       "excerpt": h["text"][:300]} for h in hits],
        "retrieval": how,
        "note": None if how == "section" else
                "No declared PLP section for this sector; citation found by "
                "semantic search and may be less precise.",
    }
