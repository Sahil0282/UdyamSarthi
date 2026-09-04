"""M8 — FastAPI.

Every response carries `run_id`, and every advise run is persisted to MongoDB
so `/provenance/{run_id}` can reproduce exactly which Facts backed a verdict.
That is the storage split doing its job: PostGIS answers the spatial question,
Mongo remembers what was answered.
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.facts import encode                      # noqa: E402
from core.geo import is_ambiguous, resolve         # noqa: E402
from core.narrate import narrate                   # noqa: E402
from core.pipeline import advise, load_sectors     # noqa: E402
from core.voice import parse_query, synthesize, transcribe   # noqa: E402

app = FastAPI(title="Udyam Saarthi", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

WEB = ROOT / "web"


# Run log. MongoDB is the store of record; this in-process ring is a fallback
# so /provenance still answers when Atlas is unreachable. It is explicitly
# labelled in the response — a degraded answer must say it is degraded rather
# than look identical to the real thing.
_RECENT: "OrderedDict[str, dict]" = OrderedDict()
_RECENT_MAX = 64


def _mongo():
    try:
        from core.db import mongo_db
        db = mongo_db()
        db.client.admin.command("ping")     # fail fast rather than on first use
        return db
    except Exception:
        return None


def _remember(doc: dict) -> None:
    _RECENT[doc["_id"]] = doc
    while len(_RECENT) > _RECENT_MAX:
        _RECENT.popitem(last=False)


class ResolveIn(BaseModel):
    village: str
    district_hint: str | None = None


class AdviseIn(BaseModel):
    village: str
    capital_inr: float = Field(gt=0)
    sector: str
    shrid: str | None = None
    target_group: str | None = "OBC"
    annual_income_inr: float | None = None
    scheme_id: str | None = None
    override: bool = False
    use_llm: bool = False
    lang: str = "en"


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/sectors")
def sectors():
    out = []
    for sid, s in load_sectors().items():
        mm = s["market_mapping"]
        out.append({
            "sector_id": sid,
            "display_name": s["display_name"],
            "shric_bucket": mm["shric_bucket"],
            "shric_desc": mm["shric_desc"],
            "role": mm["role"],
            "capex_inr": s["capex"]["unit_cost_inr"],
            "capex_verified": s["capex"]["verified"],
        })
    return {"sectors": out}


@app.post("/resolve")
def resolve_ep(body: ResolveIn):
    cands = resolve(body.village, district_hint=body.district_hint)
    if not cands:
        raise HTTPException(404, f"No village matching {body.village!r}")
    return {
        "candidates": [c.to_dict() for c in cands],
        "ambiguous": is_ambiguous(cands),
        "message": ("Several places share this name — confirm which one."
                    if is_ambiguous(cands) else None),
    }


@app.post("/advise")
def advise_ep(body: AdviseIn):
    env = advise(
        village=body.village, capital_inr=body.capital_inr,
        sector=body.sector, shrid=body.shrid,
        target_group=body.target_group,
        annual_income_inr=body.annual_income_inr,
        scheme_id=body.scheme_id, override=body.override,
    )
    if "error" in env:
        raise HTTPException(404, env["error"])

    out = encode(env)
    if not env.get("resolution", {}).get("needs_confirmation"):
        n = narrate(env, use_llm=body.use_llm, lang=body.lang)
        out["narration"] = n

        doc = {"_id": env["run_id"], "query": env["query"],
               "verdict": env["decision"]["verdict"],
               "confidence": env["decision"]["confidence"],
               "provenance": env["provenance"],
               "narration_path": n["path"],
               "created_at": datetime.now(timezone.utc)}
        _remember(doc)
        out["provenance_store"] = "memory"
        db = _mongo()
        if db is not None:
            try:
                db["runs"].replace_one({"_id": env["run_id"]}, doc, upsert=True)
                out["provenance_store"] = "mongodb"
            except Exception:
                pass          # a logging failure must never fail the advice
    return out


# ---------------------------------------------------------------- voice
# Additive only. Every endpoint degrades to ok:false with a reason, and the
# text path in /advise is untouched by anything here.

class SpeakIn(BaseModel):
    text: str
    voice: str = "Kore"


@app.post("/voice/transcribe")
async def voice_transcribe(audio: UploadFile = File(...),
                           lang: str = Form("mr")):
    """Speech in -> transcript + a PARSED, UNCONFIRMED query.

    The parsed query is never executed here. It comes back for the user to
    confirm, so a misheard rupee amount cannot silently drive a verdict.
    """
    data = await audio.read()
    t = transcribe(data, mime=audio.content_type or "audio/wav", lang=lang)
    if not t["ok"]:
        return {"ok": False, "stage": "asr", "error": t["error"],
                "hint": "Voice is optional — the text form still works."}
    q = parse_query(t["text"])
    return {"ok": True, "transcript": t["text"], "model": t["model"],
            "parsed": {k: q[k] for k in ("village", "capital_inr", "sector")},
            "parse_source": q["source"],
            "needs_confirmation": True}


@app.post("/voice/speak")
def voice_speak(body: SpeakIn):
    """Narration text -> WAV. The text is whatever /advise already returned,
    so the numeric validator has already run on it."""
    r = synthesize(body.text, voice=body.voice)
    if not r["ok"]:
        raise HTTPException(503, f"TTS unavailable: {r['error']}")
    return Response(content=r["audio"], media_type="audio/wav")


@app.get("/provenance/{run_id}")
def provenance_ep(run_id: str, path: str | None = Query(None)):
    doc, store, degraded = None, "mongodb", False
    db = _mongo()
    if db is not None:
        try:
            doc = db["runs"].find_one({"_id": run_id})
        except Exception:
            doc = None
    if doc is None:
        doc, store, degraded = _RECENT.get(run_id), "memory", True
    if doc is None:
        raise HTTPException(
            404, f"no run {run_id} in MongoDB or the in-process cache")

    facts = doc["provenance"]
    if path:
        facts = [f for f in facts if f["path"] == path]
    return {"run_id": run_id, "query": doc["query"],
            "verdict": doc["verdict"], "confidence": doc["confidence"],
            "count": len(facts), "provenance": facts,
            "store": store,
            "note": ("Served from the in-process cache because MongoDB was "
                     "unreachable; it holds only recent runs from this "
                     "process." if degraded else None)}


if WEB.exists():
    app.mount("/app", StaticFiles(directory=str(WEB), html=True), name="web")

    @app.get("/")
    def root():
        idx = WEB / "index.html"
        return FileResponse(str(idx)) if idx.exists() else {"ok": True}
