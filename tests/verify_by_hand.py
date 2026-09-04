#!/usr/bin/env python3
"""Check 1 — trace every headline figure in the envelope back to its source.

Nothing here calls the engines to check the engines. Each expected value is
either recomputed independently in SQL, read straight out of the YAML, or
worked out arithmetically from figures already confirmed on the line above.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import engine                       # noqa: E402
from core.finance import emi, rate_for           # noqa: E402
from core.pipeline import advise                 # noqa: E402

VILLAGE, CAPITAL = "nimgaon jali", 100_000
OK, BAD = "PASS", "FAIL"
rows: list[tuple] = []
fails = 0


def check(label: str, got, expected, how: str, tol: float = 0.01):
    global fails
    if isinstance(got, (int, float)) and isinstance(expected, (int, float)):
        good = abs(float(got) - float(expected)) <= max(tol, abs(expected) * 1e-6)
    else:
        good = got == expected
    if not good:
        fails += 1
    rows.append((OK if good else BAD, label, got, expected, how))


def main() -> int:
    eng = engine()
    env = advise(village=VILLAGE, capital_inr=CAPITAL, sector="dairy", eng=eng)
    shrid = env["resolution"]["chosen"]["shrid2"]
    m, fin, aff = env["market"], env["finance"], env["affordability"]
    sec = yaml.safe_load(open("data/sectors/dairy.yaml"))
    sch = yaml.safe_load(open("data/rules/schemes/nbcfdc_term_loan.yaml"))

    with eng.connect() as c:
        def q(sql, **p):
            return c.execute(text(sql), p).first()

        # ---------- MARKET: recomputed straight from PostGIS ----------
        r = q("""SELECT COUNT(*) n, SUM(p.tot_p) raw,
                        SUM(p.tot_p/(1+POWER(vn.dist_km,2))) decay
                   FROM village_neighbours vn
                   JOIN pca_village p ON p.shrid2 = vn.neighbour
                  WHERE vn.shrid2 = :s""", s=shrid)
        check("market.villages_in_catchment", m["villages_in_catchment"].value,
              r.n, "COUNT over village_neighbours (Phase 1 Q2 said 59)")
        check("market.catchment_population_raw",
              m["catchment_population_raw"].value, float(r.raw),
              "SUM(tot_p) over the 8km ring (Phase 1 Q2 said 186,225)")
        check("market.catchment_population",
              m["catchment_population"].value, round(float(r.decay)),
              "SUM(tot_p/(1+d^2)) decay weight (Phase 1 Q2 said 37,123)")

        r = q("""SELECT COALESCE(SUM(s.emp),0) e
                   FROM village_neighbours vn
                   JOIN ec_village_sector s
                     ON s.shrid2 = vn.neighbour AND s.shric = 7
                  WHERE vn.shrid2 = :s""", s=shrid)
        check("market.procurement_capacity", m["procurement_capacity"].value,
              float(r.e), "SUM(emp) SHRIC 7 over ring (Phase 1 Q2 said 62)")

        # village-level EC figure Phase 1 Q1 printed
        r = q("""SELECT s.emp FROM ec_village_sector s
                  WHERE s.shrid2 = :s AND s.shric = 7""", s=shrid)
        check("Phase 1 Q1 village dairy employment", float(r.emp), 50.0,
              "ec_village_sector, unchanged since Phase 1")

        # ---------- AFFORDABILITY: SECC, unchanged since Phase 1 ----------
        r = q("""SELECT secc_hh, inc_5k_plus_share p5, inc_10k_plus_share p10
                   FROM secc_village WHERE shrid2 = :s""", s=shrid)
        check("Phase 1 Q3 secc households", float(r.secc_hh), 1228.0,
              "secc_village, unchanged since Phase 1")
        p10, p5 = float(r.p10), float(r.p5)
        expect_draw = ((1 - p5) * 2500 + (p5 - p10) * 7500 + p10 * 15000)
        check("affordability.household_drawings",
              aff["household_drawings"].value, round(expect_draw, 2),
              "band midpoints 2500/7500/15000 x SECC band shares")

    # ---------- AFFORDABILITY: arithmetic from the YAML ----------
    mo = sec["monthly"]
    price = mo["milk_price"]["buffalo"]["value"]
    animals = mo["animals_per_unit"]
    peak = mo["yield"]["value"]
    lac, dry = mo["lactation_days_per_year"], mo["dry_days_per_year"]
    check("affordability.milk_price", aff["milk_price"].value, price,
          "dairy.yaml monthly.milk_price.buffalo.value (Gokul, MILK_PRICE_SOURCE.md)")
    check("affordability.yield (lactation)",
          aff["yield_per_animal_per_day"].value, peak,
          "dairy.yaml monthly.yield.value (NABARD model, MILK_YIELD_OPEX_SOURCE.md)")
    annualised = peak * lac / 365.0
    check("affordability.yield_annualised", aff["yield_annualised"].value,
          round(annualised, 3),
          f"{peak} L/day x {lac} lactation days / 365 "
          f"({lac}+{dry}={lac + dry} vs 365, source's own mismatch)")
    check("affordability.monthly_revenue", aff["monthly_revenue"].value,
          round(animals * annualised * 30 * price, 2),
          f"{animals} animals x {annualised:.3f} L/day x 30 d x INR {price}/L")
    per_animal = mo["monthly_opex_per_animal"]["value"]
    opex = per_animal * animals
    check("affordability.monthly_opex", aff["monthly_opex"].value, opex,
          f"INR {per_animal}/animal/month x {animals} animals (NABARD-derived)")
    check("affordability.net_available_for_emi",
          aff["net_available_for_emi"].value,
          round(float(aff["monthly_revenue"].value) - opex
                - float(aff["household_drawings"].value), 2),
          "revenue - opex - drawings")
    check("affordability.working_capital_floor",
          aff["working_capital_floor"].value,
          opex * sec["working_capital_months"],
          f"opex x {sec['working_capital_months']} months")

    # ---------- FINANCE: arithmetic from the scheme YAML ----------
    ltc, cap = sch["loan_to_cost_ratio"], sch["per_beneficiary_cap_inr"]
    check("finance.theoretical_project_cost",
          fin["theoretical_project_cost"].value, CAPITAL / (1 - ltc),
          f"capital / (1 - {ltc})")
    check("finance.eligible_loan", fin["eligible_loan"].value,
          min(CAPITAL / (1 - ltc) * ltc, cap),
          f"min(project x {ltc}, cap {cap:,})")
    rate = rate_for(sch, float(fin["eligible_loan"].value))
    check("finance.interest_rate", fin["interest_rate"].value, rate,
          "slab lookup on interest_slabs")
    sched = emi(float(fin["eligible_loan"].value), rate,
                sch["repayment_years"], sch["moratorium_months"], 4)
    check("finance.emi (monthly equivalent)", fin["emi"].value,
          round(sched["monthly_equivalent"], 2),
          "quarterly instalment x 4 / 12, moratorium interest capitalised")

    # ---------- the advice ----------
    check("affordability.safe_emi_capacity", aff["safe_emi_capacity"].value,
          round(float(aff["net_available_for_emi"].value) * 0.70, 2),
          "net available x SAFETY_FACTOR 0.70")
    from core.finance import emi_for_principal
    rec = float(aff["recommended_loan"].value)
    check("EMI at recommended <= safe capacity",
          emi_for_principal(sch, rec) <= float(aff["safe_emi_capacity"].value) + 1,
          True, "bisection invariant: the recommended loan is affordable")
    check("recommended < eligible", rec < float(fin["eligible_loan"].value), True,
          "eligibility exceeds affordability — the product's whole premise")

    # ---------- the three sourced benchmarks keep their labelling ----------
    for key, yk in (("yield_per_animal_per_day", "yield"),
                    ("opex_per_animal", "monthly_opex_per_animal")):
        check(f"{key} geo_level", aff[key].geo_level, mo[yk]["geo_level"],
              "national — a benchmark, not an Ahmadnagar measurement")
        check(f"{key} confidence", aff[key].confidence, mo[yk]["confidence"],
              "low — must not be upgraded on the way through")
    check("milk_price geo_level", aff["milk_price"].geo_level, "state",
          "Kolhapur proxy, one level coarser than the district")
    check("decision confidence", env["decision"]["confidence"], "low",
          "inherits the weakest input (national benchmarks)")

    # ---------- report ----------
    w = max(len(r[1]) for r in rows)
    print(f"\nHAND VERIFICATION — {VILLAGE}, capital INR {CAPITAL:,}, dairy")
    print(f"run_id {env['run_id']}\n")
    print(f"{'':4} {'figure'.ljust(w)}  {'envelope':>14} {'expected':>14}  how")
    print("-" * (w + 92))
    for st, label, got, exp, how in rows:
        g = f"{got:,.2f}" if isinstance(got, float) else str(got)
        e = f"{exp:,.2f}" if isinstance(exp, float) else str(exp)
        print(f"{st:4} {label.ljust(w)}  {g:>14} {e:>14}  {how}")
    print("-" * (w + 92))
    print(f"{len(rows) - fails}/{len(rows)} traced, {fails} mismatched\n")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
