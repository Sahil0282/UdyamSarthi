#!/usr/bin/env python3
"""Udyam Saarthi CLI.

    python cli.py advise --village "nimgaon jali" --capital 100000 \
                         --sector dairy --no-llm

`--no-llm` is the default and the only path that exists before Phase 4. The
unplug test requires that enabling the LLM changes no number, so the LLM is
kept out of the computation call graph entirely rather than merely switched off.
"""
from __future__ import annotations

import argparse
import sys

from core.pipeline import advise, load_sectors, to_json


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cli.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("advise")
    a.add_argument("--village", required=True)
    a.add_argument("--capital", type=float, required=True)
    a.add_argument("--sector", required=True)
    a.add_argument("--shrid", default=None,
                   help="disambiguate when several villages share a name")
    a.add_argument("--target-group", default="OBC")
    a.add_argument("--income", type=float, default=None,
                   help="applicant annual income, for the scheme ceiling")
    a.add_argument("--scheme", default=None)
    a.add_argument("--override", action="store_true",
                   help="proceed anyway; switches output to risk-mitigation mode")
    a.add_argument("--no-llm", action="store_true", default=True)
    a.add_argument("--summary", action="store_true",
                   help="human-readable digest instead of the raw envelope")

    sub.add_parser("sectors")
    args = ap.parse_args(argv)

    if args.cmd == "sectors":
        for sid, s in load_sectors().items():
            mm = s["market_mapping"]
            print(f"{sid:<20} {s['display_name']['en']:<28} "
                  f"SHRIC {mm['shric_bucket']:<3} {mm['role']}")
        return 0

    env = advise(
        village=args.village, capital_inr=args.capital, sector=args.sector,
        target_group=args.target_group, annual_income_inr=args.income,
        scheme_id=args.scheme, shrid=args.shrid, override=args.override,
    )

    if args.summary:
        return _summary(env)
    print(to_json(env))
    return 0


def _f(x):
    return "n/a" if x is None else f"{float(x):,.0f}"


def _summary(env: dict) -> int:
    if "error" in env:
        print("ERROR:", env["error"]); return 1
    r = env["resolution"]
    if r.get("needs_confirmation"):
        print(r["message"])
        for c in r["candidates"][:8]:
            print(f"  --shrid {c['shrid2']}  {c['place_name']} "
                  f"({c['subdistrict_name']}, pop {c['population']})")
        return 2

    c, d = r["chosen"], env["decision"]
    m, fin, aff = env["market"], env["finance"], env["affordability"]
    print(f"\n{c['place_name']} ({c['subdistrict_name']}, {c['district_name']}) "
          f"— {env['query']['sector']}")
    print(f"run_id {env['run_id']}\n")
    sc = {k: float(v.value) for k, v in d["score"].items()}
    print(f"VERDICT: {d['verdict']}   score {sc['overall']:.2f} "
          f"(market {sc['market_fit']:.2f} / afford {sc['affordability']:.2f} / "
          f"risk {sc['risk']:.2f})   confidence {d['confidence']}")
    if d.get("override_applied"):
        print(f"OVERRIDE APPLIED — mode {d['mode']}, "
              f"original verdict {d['original_verdict']}")
    print(f"\nMarket   catchment {_f(m['catchment_population'].value)} people "
          f"over {env['geo']['catchment_km']:g} km "
          f"({m['villages_in_catchment'].value} villages), "
          f"percentile {m['saturation_percentile'].value}")
    print(f"Finance  eligible {_f(fin['eligible_loan'].value)} @ "
          f"{float(fin['interest_rate'].value):.1%}, "
          f"EMI {_f(fin['emi'].value)}/mo"
          + ("  [CAP APPLIED]" if fin["cap_applied"].value else ""))
    print(f"Cashflow revenue {_f(aff['monthly_revenue'].value)} - opex "
          f"{_f(aff['monthly_opex'].value)} - drawings "
          f"{_f(aff['household_drawings'].value)} = "
          f"{_f(aff['net_available_for_emi'].value)}/mo")
    print(f"Advice   recommended {_f(aff['recommended_loan'].value)} "
          f"(EMI {_f(aff['emi_at_recommended'].value)}/mo), "
          f"working capital floor {_f(aff['working_capital_floor'].value)}")
    print(f"Survival {env['risk']['survival_at_recommended'].value} at "
          f"recommended vs {env['risk']['survival_at_eligible'].value} at eligible")

    if env["risk"]["flags"]:
        print("\nRisk flags:")
        for f in env["risk"]["flags"]:
            print(f"  [{f['severity']:<6}] {f['code']}")
    print("\nReasons:")
    for x in d["reasons"][:6]:
        print(f"  - {x}")
    if d["alternatives"]:
        print("\nAlternatives:")
        for alt in d["alternatives"]:
            print(f"  {alt['display_name']:<28} {alt['why']}")
    if d.get("mitigations"):
        print("\nRisk mitigation:")
        for x in d["mitigations"]:
            print(f"  - {x}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
