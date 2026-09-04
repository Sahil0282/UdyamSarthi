"""L4/L5 orchestration — assemble the result envelope (PART 5.2).

This is the whole deterministic system: everything L1-L5. No LLM is imported
anywhere below this line, and `advise()` never takes a model client. Phase 4's
narration consumes the envelope this returns and adds prose beside it; it can
never change a number, because it is not in this call graph.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from core import decision as M6
from core import market as M2
from core import plp as PLP
from core import risk as M5
from core.affordability import analyse as M4
from core.db import engine
from core.facts import Fact, encode, flatten_provenance
from core.finance import analyse as M3
from core.finance import eligible_schemes, load_schemes
from core.geo import (catchment_points, geometry, is_ambiguous,
                      resolve, ring_geojson)

SECTORS_DIR = Path(__file__).resolve().parents[1] / "data" / "sectors"
SCHEMA_VERSION = "1.0"


def load_sectors(d: Path | None = None) -> dict[str, dict]:
    d = d or SECTORS_DIR
    out = {}
    for p in sorted(d.glob("*.yaml")):
        s = yaml.safe_load(p.read_text())
        out[s["sector_id"]] = s
    return out


def _sector_by_name(sectors: dict[str, dict], name: str) -> dict:
    if name in sectors:
        return sectors[name]
    for sid, s in sectors.items():
        if sid.startswith(name) or name in sid:
            return s
    raise KeyError(f"unknown sector {name!r}; have {sorted(sectors)}")


def run_id(query: dict) -> str:
    """Deterministic: same question, same id. Not a timestamp, not a uuid —
    PART 7 requires two identical runs to be byte-identical."""
    blob = json.dumps({**query, "schema": SCHEMA_VERSION}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _evaluate(shrid: str, sector: dict, scheme: dict, capital: float, eng):
    """One sector at one village. Used for the request and for every alternative."""
    mk = M2.analyse(shrid, sector, eng=eng)
    fin = M3(scheme, capital)
    aff = M4(shrid, sector, scheme, float(fin["eligible_loan"].value), eng=eng)
    fl = M5.flags(shrid, sector, mk, eng=eng)
    surv_rec = M5.monte_carlo(aff, scheme, float(aff["recommended_loan"].value))
    surv_elig = M5.monte_carlo(aff, scheme, float(fin["eligible_loan"].value))
    sc = M6.score(mk, aff, fl, surv_rec, sector)
    return mk, fin, aff, fl, surv_rec, surv_elig, sc


def advise(village: str, capital_inr: float, sector: str,
           target_group: str | None = "OBC",
           annual_income_inr: float | None = None,
           scheme_id: str | None = None,
           shrid: str | None = None,
           override: bool = False,
           district_hint: str | None = None,
           eng=None) -> dict:
    """Produce the full result envelope. Deterministic and LLM-free."""
    eng = eng or engine()
    sectors = load_sectors()
    sec = _sector_by_name(sectors, sector)

    query = {
        "village": village, "capital_inr": capital_inr,
        "sector": sec["sector_id"], "target_group": target_group,
        "annual_income_inr": annual_income_inr, "override": override,
        "shrid": shrid,
    }

    # ---- L3 resolution: never auto-pick an ambiguous name ----
    cands = resolve(village, district_hint=district_hint, eng=eng)
    if not cands:
        return {"query": query, "run_id": run_id(query),
                "schema_version": SCHEMA_VERSION,
                "error": f"No village matching {village!r}."}
    if shrid:
        chosen = next((c for c in cands if c.shrid2 == shrid), None)
        if chosen is None:
            raise KeyError(f"{shrid} is not among the candidates for {village!r}")
        confirmed = True
    else:
        ambiguous = is_ambiguous(cands)
        chosen = cands[0]
        confirmed = not ambiguous
        if ambiguous:
            return {
                "query": query, "run_id": run_id(query),
                "schema_version": SCHEMA_VERSION,
                "resolution": {
                    "candidates": [c.to_dict() for c in cands],
                    "chosen": None, "confirmed_by_user": False,
                    "needs_confirmation": True,
                    "message": (
                        f"{len(cands)} places match {village!r} and the top two "
                        "are too close to call. India has heavy duplicate "
                        "village names; pick one with --shrid and re-run."),
                },
            }

    # ---- scheme selection ----
    schemes = eligible_schemes(load_schemes(), target_group, annual_income_inr)
    if scheme_id:
        schemes = [s for s in schemes if s["scheme_id"] == scheme_id]
    if not schemes:
        return {"query": query, "run_id": run_id(query),
                "schema_version": SCHEMA_VERSION,
                "error": "No scheme matches this applicant."}
    # Largest cap first: the applicant should be assessed against the scheme
    # that could actually fund the project, then told if it is too much.
    scheme = max(schemes, key=lambda s: s["per_beneficiary_cap_inr"])

    mk, fin, aff, fl, surv_rec, surv_elig, sc = _evaluate(
        chosen.shrid2, sec, scheme, capital_inr, eng)

    # ---- alternatives: score every OTHER sector at this village ----
    alts = []
    for sid, alt in sectors.items():
        if sid == sec["sector_id"]:
            continue
        try:
            a_mk, a_fin, a_aff, a_fl, a_surv, _, a_sc = _evaluate(
                chosen.shrid2, alt, scheme, capital_inr, eng)
        except Exception:
            continue
        alts.append({
            "sector": sid,
            "display_name": alt["display_name"]["en"],
            "score": Fact(
                a_sc["overall"], "score 0-1",
                "deterministic weighted score (market/affordability/risk)",
                None, "village", a_surv.confidence,
                note="Scored for THIS village and THIS capital using the same "
                     "engines as the requested sector."),
            "recommended_loan": a_aff["recommended_loan"],
            "survival_probability": a_surv,
            "why": _why(alt, a_sc, a_aff, a_fl),
            "plp": PLP.cite_sector(alt),
        })
    alts.sort(key=lambda x: -float(x["score"].value))
    alts = alts[:M6.T.N_ALTERNATIVES]

    dec = M6.decide(mk, fin, aff, fl, surv_rec, sec, alternatives=alts,
                    override=override)

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id(query),
        "query": query,
        "resolution": {
            "candidates": [c.to_dict() for c in cands],
            "chosen": chosen.to_dict(),
            "confirmed_by_user": confirmed,
            "needs_confirmation": False,
        },
        "geo": {
            "catchment_km": M2.CATCHMENT_KM,
            "village_geojson": geometry(chosen.shrid2, eng=eng)["geojson"],
            "ring_geojson": ring_geojson(chosen.shrid2, M2.CATCHMENT_KM, eng=eng),
            "points": catchment_points(
                chosen.shrid2, int(sec["market_mapping"]["shric_bucket"]),
                M2.CATCHMENT_KM, eng=eng),
            "points_role": sec["market_mapping"].get("role"),
            "points_label": sec["market_mapping"].get("shric_desc"),
        },
        "plp": {
            "available": PLP.available(),
            "sector": PLP.cite_sector(sec),
            "note": None if PLP.available() else
                    "PLP index not built — ranking uses market and risk "
                    "scoring only and claims no NABARD backing.",
        },
        "market": mk,
        "finance": fin,
        "affordability": aff,
        "risk": {
            "flags": fl,
            "seasonality_index": [],
            "seasonality_note": sec.get("seasonality", {}).get("reason"),
            "survival_at_recommended": surv_rec,
            "survival_at_eligible": surv_elig,
        },
        "decision": dec,
    }
    envelope["provenance"] = flatten_provenance(
        {k: v for k, v in envelope.items()
         if k in ("market", "finance", "affordability", "risk", "decision")})
    return envelope


def _why(sector: dict, sc: dict, aff: dict[str, Fact], flags: list[dict]) -> str:
    bits = [f"score {sc['overall']:.2f} "
            f"(market {sc['market_fit']:.2f}, afford {sc['affordability']:.2f}, "
            f"risk {sc['risk']:.2f})"]
    rec = aff["recommended_loan"].value
    if rec is not None:
        bits.append(f"supports a loan of INR {float(rec):,.0f}")
    highs = [f["code"] for f in flags if f["severity"] == "high"]
    if highs:
        bits.append("blocking flags: " + ", ".join(highs))
    return "; ".join(bits)


def to_json(envelope: dict, indent: int = 2) -> str:
    return json.dumps(encode(envelope), indent=indent, ensure_ascii=False,
                      default=str)
