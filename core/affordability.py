"""M4 — Affordability Model. The module that makes this an advisor.

Eligibility is what the scheme will lend. Affordability is what the business
can actually service after the household has eaten. They are different numbers
and the gap between them is the product.

SECC-MORD carries no household consumption column (RECON.md section 0). It
carries income-bracket shares, so household drawings are ESTIMATED from those
and every Fact derived from them says so and inherits low confidence.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from core.db import engine
from core.facts import Fact, derive, fact_from_yaml
from core.finance import emi_for_principal

SAFETY_FACTOR = 0.70          # PART 6 M4
SECC_SOURCE = "SECC 2011-12 MORD rural (via SHRUG v2.2)"

# Midpoints used to turn SECC's three income bands into an expected value.
# These are ASSUMPTIONS, not data. The top band is open-ended, so its midpoint
# is the least defensible number in this module and is stated in the note.
BAND_MIDPOINTS = {"lt_5k": 2500.0, "5k_10k": 7500.0, "gt_10k": 15000.0}


def household_drawings(shrid: str, eng=None) -> Fact:
    """Estimate what the household must withdraw monthly to live."""
    eng = eng or engine()
    row = pd.read_sql(text("""
        SELECT s.secc_hh, s.inc_5k_plus_share, s.inc_10k_plus_share,
               n.subdistrict_name
          FROM secc_village s JOIN shrid_names n USING (shrid2)
         WHERE s.shrid2 = :s
    """), eng, params={"s": shrid})

    geo, conf = "village", "low"
    note_extra = ""
    if row.empty:
        # Degrade to subdistrict rather than silently substituting. PART 10.
        row = pd.read_sql(text("""
            SELECT AVG(s.inc_5k_plus_share)  AS inc_5k_plus_share,
                   AVG(s.inc_10k_plus_share) AS inc_10k_plus_share,
                   SUM(s.secc_hh)            AS secc_hh
              FROM secc_village s JOIN shrid_names n USING (shrid2)
             WHERE n.subdistrict_name = (
                     SELECT subdistrict_name FROM shrid_names WHERE shrid2 = :s)
        """), eng, params={"s": shrid})
        geo, conf = "subdistrict", "low"
        note_extra = (" No SECC row for this place (SECC-MORD is rural only, so "
                      "towns are absent); degraded to the subdistrict mean.")
        if row.empty or pd.isna(row.iloc[0]["inc_5k_plus_share"]):
            return Fact(None, "INR per month", SECC_SOURCE, 2012, "district",
                        "low",
                        note="No SECC data at village or subdistrict level.")

    r = row.iloc[0]
    p_gt10 = float(r["inc_10k_plus_share"])
    p_5_10 = max(float(r["inc_5k_plus_share"]) - p_gt10, 0.0)
    p_lt5 = max(1.0 - float(r["inc_5k_plus_share"]), 0.0)
    est = (p_lt5 * BAND_MIDPOINTS["lt_5k"]
           + p_5_10 * BAND_MIDPOINTS["5k_10k"]
           + p_gt10 * BAND_MIDPOINTS["gt_10k"])

    return Fact(
        round(est, 2), "INR per month", SECC_SOURCE, 2012, geo, conf,
        note=(
            "ESTIMATED, not measured. SECC-MORD has no household consumption "
            "column; this is an expected value over its three income bands "
            f"(<5k, 5k-10k, >10k) with assumed midpoints "
            f"{BAND_MIDPOINTS['lt_5k']:.0f}/{BAND_MIDPOINTS['5k_10k']:.0f}/"
            f"{BAND_MIDPOINTS['gt_10k']:.0f} INR. The top band is open-ended so "
            "its midpoint is an assumption. Band shares here: "
            f"{p_lt5:.1%} / {p_5_10:.1%} / {p_gt10:.1%}. SECC records the "
            "highest-earning member's income, so this understates total "
            "household income and is used as a floor on required drawings."
            + note_extra),
    )



def _revenue(m: dict, sector: dict, out: dict[str, Fact]) -> None:
    """Build the monthly revenue Fact according to the sector's revenue model.

    Two models, because the sectors genuinely differ:

    ``yield_price``  physical output x a published price (dairy: litres x the
                     cooperative procurement rate). The price keeps its own
                     provenance as a separate leaf so the user can tap it.
    ``fixed_margin`` a benchmark net margin per unit, for sectors where no
                     published per-unit price exists. Always low confidence.
    """
    model = m.get("revenue_model", "yield_price")

    if model == "yield_price":
        units = int(m["animals_per_unit"])
        yield_fact = fact_from_yaml(m["yield"])
        price_fact = fact_from_yaml(m["milk_price"][m["animal_type"]])
        peak = float(yield_fact.value)

        # The source figure is a LACTATION yield, not a year-round one. A
        # buffalo is dry for ~150 days, so applying the lactation figure flat
        # across 12 months would overstate revenue by about a third. The
        # annualisation is done here, in the open, and recorded in the note.
        lac = int(m.get("lactation_days_per_year", 365))
        dry = int(m.get("dry_days_per_year", 0))
        annualised = peak * lac / 365.0
        out["milk_price"] = price_fact
        out["yield_per_animal_per_day"] = yield_fact
        out["yield_annualised"] = derive(
            round(annualised, 3), "litres per animal per day (annual average)",
            f"lactation yield {peak} L/day x {lac} lactation days / 365",
            yield_fact,
            note=f"Flat monthly model, so the lactation figure is annualised: "
                 f"{peak} L/day over {lac} lactation days and {dry} dry days. "
                 f"Note {lac}+{dry}={lac + dry} days against a 365-day year — "
                 "the source model's own discrepancy, carried forward and not "
                 "silently reconciled. " + (yield_fact.note or ""))
        out["animals"] = Fact(
            units, "animals", sector["capex"]["source"], sector["capex"]["year"],
            "district", "high",
            note=f"NABARD '{sector['capex']['nabard_unit']}' unit size.")

        days = 30
        out["monthly_revenue"] = derive(
            round(units * annualised * days * float(price_fact.value), 2),
            "INR per month",
            f"{units} animals x {annualised:.2f} L/day (annualised) x {days} "
            f"days x INR {price_fact.value}/L",
            out["yield_annualised"], price_fact, out["animals"])
        return

    if model == "fixed_margin":
        rev = m["gross_revenue_inr_per_month"]
        out["monthly_revenue"] = Fact(
            float(rev["value"]), "INR per month", rev["source"],
            rev.get("year"), rev.get("geo_level", "national"),
            rev.get("confidence", "low"),
            note=rev.get("note", "Benchmark gross monthly revenue for this "
                                 "sector; not a measurement at this village."))
        return

    raise ValueError(f"unknown revenue_model {model!r}")


def analyse(shrid: str, sector: dict, scheme: dict, eligible_loan: float,
            eng=None) -> dict[str, Fact]:
    """Cash-flow model for this sector at this village, and the loan it supports."""
    eng = eng or engine()
    m = sector["monthly"]
    out: dict[str, Fact] = {}

    _revenue(m, sector, out)
    revenue = float(out["monthly_revenue"].value)

    # ---- opex ----
    units = int(m.get("units_per_unit", m.get("animals_per_unit", 1)))
    if "monthly_opex_per_animal" in m:
        # Sourced single figure with its own provenance.
        per_animal = fact_from_yaml(m["monthly_opex_per_animal"])
        out["opex_per_animal"] = per_animal
        opex_fact = derive(
            round(float(per_animal.value) * units, 2), "INR per month",
            f"INR {per_animal.value}/animal/month x {units} animals",
            per_animal)
    else:
        opex_items = m.get("opex_per_animal_inr") or m.get("opex_per_unit_inr", {})
        per_unit = m.get("opex_per_animal_inr") is not None or \
            m.get("opex_scales_with_units", True)
        opex = sum(float(v) for v in opex_items.values()) * (units if per_unit else 1)
        opex_fact = Fact(
            round(opex, 2), "INR per month", m["opex_source"], None, "national",
            m.get("opex_confidence", "low"),
            note="Sector benchmark cost structure, not measured locally. "
                 f"Components: {', '.join(f'{k} {v}' for k, v in opex_items.items())}."
                 + (f" Scaled by {units} units." if per_unit and units != 1 else ""),
        )
    out["monthly_opex"] = opex_fact
    opex = float(opex_fact.value)

    # ---- household drawings ----
    draw = household_drawings(shrid, eng)
    out["household_drawings"] = draw

    # ---- what is left to service a loan ----
    draw_val = float(draw.value) if draw.value is not None else 0.0
    net = revenue - opex - draw_val
    out["net_available_for_emi"] = derive(
        round(net, 2), "INR per month",
        "revenue - opex - household drawings",
        out["monthly_revenue"], opex_fact, draw,
    )

    # ---- working capital floor ----
    wc_months = int(sector["working_capital_months"])
    out["working_capital_floor"] = derive(
        round(opex * wc_months, 2), "INR",
        f"{wc_months} months of operating cost, reserved from the loan BEFORE "
        "capex is approved",
        opex_fact,
    )

    # ---- the recommended loan ----
    safe_capacity = max(net, 0.0) * SAFETY_FACTOR
    out["safe_emi_capacity"] = derive(
        round(safe_capacity, 2), "INR per month",
        f"net available x safety factor {SAFETY_FACTOR}",
        out["net_available_for_emi"],
    )

    rec = _max_principal(scheme, safe_capacity, ceiling=eligible_loan)
    out["recommended_loan"] = derive(
        round(rec, 2), "INR",
        f"largest principal under {scheme['scheme_id']} whose monthly-equivalent "
        f"EMI stays within the safe capacity",
        out["net_available_for_emi"], out["monthly_revenue"], opex_fact, draw,
    )
    out["emi_at_recommended"] = derive(
        round(emi_for_principal(scheme, rec), 2), "INR per month",
        "EMI on the recommended loan", out["recommended_loan"],
    )
    out["emi_at_eligible"] = derive(
        round(emi_for_principal(scheme, eligible_loan), 2), "INR per month",
        "EMI on the full eligible loan, for contrast",
        out["recommended_loan"],
    )
    shortfall = net - emi_for_principal(scheme, eligible_loan)
    out["monthly_gap_at_eligible"] = derive(
        round(shortfall, 2), "INR per month",
        "net available minus EMI at the full eligible loan; negative means the "
        "eligible loan cannot be serviced from this business",
        out["net_available_for_emi"],
    )
    return out


def _max_principal(scheme: dict, capacity: float, ceiling: float,
                   tol: float = 1.0) -> float:
    """Largest principal whose EMI fits `capacity`. Bisection — EMI is monotone."""
    if capacity <= 0:
        return 0.0
    if emi_for_principal(scheme, ceiling) <= capacity:
        return ceiling
    lo, hi = 0.0, ceiling
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if emi_for_principal(scheme, mid) <= capacity:
            lo = mid
        else:
            hi = mid
    return lo
