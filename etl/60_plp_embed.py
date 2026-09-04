#!/usr/bin/env python3
"""Phase 7 — embed the district PLP for retrieval-backed sector ranking.

The PLP is NABARD's own official answer to "is dairy viable in this district",
written by the District Development Manager. Citing it is the difference
between "our model scored goat rearing highly" and "NABARD's own credit plan
for your district projects X crore for goat rearing".

The index is written to data/derived/plp_index/ as plain files, not to a
database. That keeps the offline bundle self-contained: once built, retrieval
needs no network at all.

Usage:  python etl/60_plp_embed.py [--pdf data/raw/plp/ahilyanagar.pdf]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

# LOCAL embeddings, per the plan's own stack (PART 4: FAISS +
# sentence-transformers). Two reasons over the Gemini embedding API:
#   1. the offline district bundle must not need a network for retrieval
#   2. the free-tier embedding quota cannot cover 184 chunks anyway
EMBED_MODEL = os.getenv("PLP_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
OUT = ROOT / "data" / "derived" / "plp_index"
MIN_CHARS = 220
MAX_CHARS = 1400


def pdf_to_text(pdf: Path) -> str:
    txt = pdf.with_suffix(".txt")
    if not txt.exists():
        subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)], check=True)
    return txt.read_text(encoding="utf-8", errors="replace")


def chunk(text: str) -> list[dict]:
    """Split into page-aware, heading-tagged chunks.

    Pages come from the form feeds pdftotext emits. `str.splitlines()` treats
    \f as a line break and drops it, so the page must be recovered by
    splitting on \f FIRST — otherwise every citation says page 1.
    """
    # Section numbers are short (2.1.6), and a real heading's title starts
    # with a letter. Without the letter anchor, table rows like
    # "1520.00 1685.00 1345.00" parse as headings and become citations.
    head_re = re.compile(
        r"^\s*(\d{1,2}(?:\.\d{1,2}){1,3})\s+([A-Za-z][^\n]{3,89})$")
    sections: list[dict] = []
    cur_head, buf, head_page = "front matter", [], 1

    for page_no, page in enumerate(text.split("\f"), start=1):
        for ln in page.splitlines():
            m = head_re.match(ln.strip())
            if m:
                if buf:
                    sections.append({"heading": cur_head, "text": "\n".join(buf),
                                     "page": head_page})
                cur_head = f"{m.group(1)} {m.group(2).strip()}"
                head_page, buf = page_no, []
            else:
                buf.append(ln)
    if buf:
        sections.append({"heading": cur_head, "text": "\n".join(buf),
                         "page": head_page})

    out: list[dict] = []
    for sec in sections:
        body = re.sub(r"[ \t]+", " ", sec["text"])
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        if len(body) < MIN_CHARS:
            continue
        for i in range(0, len(body), MAX_CHARS):
            piece = body[i:i + MAX_CHARS].strip()
            if len(piece) < MIN_CHARS:
                continue
            out.append({
                "heading": sec["heading"],
                "page": sec["page"],
                "text": piece,
                # The heading carries most of the topical signal ("2.1.6 Animal
                # Husbandry - Dairy"). Embedding body text alone made every
                # sector query match the document's front matter.
                "embed_text": f"{sec['heading']}\n{piece}",
                "is_front_matter": sec["heading"] == "front matter",
            })
    return out


def embed(texts: list[str], batch: int = 32) -> np.ndarray:
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(EMBED_MODEL)
    return np.asarray(
        m.encode(texts, batch_size=batch, show_progress_bar=True,
                 normalize_embeddings=True),
        dtype=np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="data/raw/plp/ahilyanagar.pdf")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap chunks (embedding quota is finite)")
    args = ap.parse_args()

    pdf = Path(args.pdf).resolve()
    if not pdf.exists():
        print(f"[plp] {pdf} not found — RAG will stay disabled and the ranker "
              "will degrade to market+risk only.", file=sys.stderr)
        return 1

    chunks = chunk(pdf_to_text(pdf))
    n_front = sum(c["is_front_matter"] for c in chunks)
    print(f"[plp] {n_front} front-matter chunks retained but flagged; "
          "retrieval demotes them")
    if args.limit:
        chunks = chunks[:args.limit]
    print(f"[plp] {len(chunks)} chunks from {pdf.name}")

    vecs = embed([c["embed_text"] for c in chunks])
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9

    OUT.mkdir(parents=True, exist_ok=True)
    np.save(OUT / "vectors.npy", vecs)
    (OUT / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "meta.json").write_text(json.dumps({
        "source_pdf": str(pdf.relative_to(ROOT)),
        "document": "NABARD Potential Linked Credit Plan, Ahilyanagar 2025-26",
        "model": EMBED_MODEL, "dims": int(vecs.shape[1]),
        "chunks": len(chunks),
    }, indent=1), encoding="utf-8")
    print(f"[plp] wrote {OUT} — {vecs.shape[0]} vectors x {vecs.shape[1]} dims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
