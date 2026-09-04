#!/usr/bin/env python3
"""Validation 2 — the two demo scenarios, end to end.

Runs against the API (the containerised stack if that is what is on :8000),
so this exercises the same path the UI uses, not a private shortcut.

Voice is attempted first and falls back to text when the LLM quota is spent —
which is exactly the degradation the system is designed for, and is reported
rather than hidden.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8000"


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as fh:
        return json.load(fh)


def inr(x):
    return "n/a" if x is None else f"{float(x):,.0f}"


def voice_status() -> str:
    sys.path.insert(0, ".")
    from core.voice import synthesize
    r = synthesize("नमस्कार")
    if r["ok"]:
        return "available"
    return f"unavailable ({(r['error'] or '')[:70]})"


def scenario(title: str, village: str, capital: float, sector: str,
             expect: str, override: bool = False) -> bool:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    env = post("/advise", {"village": village, "capital_inr": capital,
                           "sector": sector, "override": override})
    d, m, f, a = (env["decision"], env["market"], env["finance"],
                  env["affordability"])
    ok = d["verdict"] == expect

    print(f"query      : {village}, capital INR {inr(capital)}, {sector}")
    print(f"run_id     : {env['run_id']}")
    print(f"VERDICT    : {d['verdict']}   (expected {expect})  "
          f"{'OK' if ok else 'MISMATCH'}")
    print(f"confidence : {d['confidence']}")
    print(f"market     : {inr(m['catchment_population']['value'])} people / "
          f"{m['villages_in_catchment']['value']} villages in 8 km; "
          f"buyer capacity {m.get('procurement_capacity', {}).get('value')}")
    print(f"finance    : eligible {inr(f['eligible_loan']['value'])} @ "
          f"{float(f['interest_rate']['value']):.0%}, "
          f"EMI {inr(f['emi']['value'])}/mo")
    print(f"cash flow  : {inr(a['monthly_revenue']['value'])} revenue - "
          f"{inr(a['monthly_opex']['value'])} opex - "
          f"{inr(a['household_drawings']['value'])} drawings = "
          f"{inr(a['net_available_for_emi']['value'])}/mo")
    print(f"ADVICE     : borrow {inr(a['recommended_loan']['value'])}, "
          f"reserve {inr(a['working_capital_floor']['value'])} working capital")
    print(f"survival   : {env['risk']['survival_at_recommended']['value']} at "
          f"recommended vs {env['risk']['survival_at_eligible']['value']} at eligible")
    if env["risk"]["flags"]:
        print("risk flags :")
        for fl in env["risk"]["flags"]:
            print(f"   [{fl['severity']:<6}] {fl['code']}")
    if d["hard_gates_triggered"]:
        print("hard gates :")
        for g in d["hard_gates_triggered"]:
            print(f"   - {g[:88]}")
    if d["alternatives"]:
        print("alternatives (ranked, with NABARD PLP citations):")
        for alt in d["alternatives"]:
            cites = "; ".join(f"{c['section'][:34]} p.{c['page']}"
                              for c in alt.get("plp", {}).get("citations", []))
            print(f"   {alt['display_name']:<28} {alt['score']['value']:<8} "
                  f"{cites}")
    if d.get("override_applied"):
        print(f"OVERRIDE   : applied; verdict still {d['verdict']}, "
              f"mode {d['mode']}")
        for x in d.get("mitigations", [])[:3]:
            print(f"   - {x[:86]}")
    print(f"map        : polygon + {env['geo']['catchment_km']} km ring + "
          f"{len(env['geo']['points'])} buyer points")
    print(f"provenance : {len(env['provenance'])} facts, "
          f"store={env.get('provenance_store')}")
    print(f"narration  : [{env['narration']['path']}] "
          f"{env['narration']['text'][:250]}...")
    return ok


def main() -> int:
    print("VOICE:", voice_status())
    results = [
        scenario("SCENARIO A — the refusal. murmi (Shevgaon), 25,000 capital",
                 "murmi", 25_000, "dairy", "RECONSIDER"),
        scenario("SCENARIO A2 — the override is honoured, not blocked",
                 "murmi", 25_000, "dairy", "RECONSIDER", override=True),
        scenario("SCENARIO B — the healthy contrast. nimgaon jali, 1,00,000",
                 "nimgaon jali", 100_000, "dairy", "PROCEED"),
    ]
    print("\n" + "=" * 78)
    print(f"{sum(results)}/{len(results)} scenarios produced the expected verdict")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
