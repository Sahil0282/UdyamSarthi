"""M5 — Risk Engine.

Every flag is COMPUTED from a named column, never generated. Each flag carries
the Fact it was computed from, so the UI can show the evidence behind the
warning rather than the warning alone.

The Monte Carlo returns a survival PROBABILITY at two borrowing levels. The
contrast between them is the point: it is what turns "you are eligible for
nine lakh" into "nine lakh fails four times in five".
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import text

from core.db import engine
from core.facts import Fact, derive
from core.finance import emi_for_principal

VD_SOURCE = "Village Directory, Population Census 2011 (via SHRUG v2.2)"
MC_RUNS = 1000
MC_SEED = 20260904          # fixed: PART 7 requires bit-identical reruns

# From NABARD's model project, which charges insurance at 5% of asset value per
# year. That premium IS the source model's own pricing of mortality risk, so it
# is used directly rather than a figure chosen to make the curve look right.
ANIMAL_MORTALITY_ANNUAL = 0.05
REPLACE_MONTHS = 3          # months to arrange and buy a replacement
ANIMAL_REPLACEMENT_INR = 50_000   # NABARD model: cost of animal, per head

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}


def _flag(code: str, severity: str, message: str, evidence: Fact) -> dict:
    return {"code": code, "severity": severity, "message": message,
            "evidence": evidence}


def flags(shrid: str, sector: dict, market: dict[str, Fact],
          eng=None) -> list[dict]:
    eng = eng or engine()
    a = pd.read_sql(text("""
        SELECT a.*, n.place_name
          FROM amenities a JOIN shrid_names n USING (shrid2)
         WHERE a.shrid2 = :s
    """), eng, params={"s": shrid})

    out: list[dict] = []
    rf = sector.get("risk_flags", {})

    if a.empty:
        out.append(_flag(
            "NO_AMENITY_DATA", "medium",
            "No Village Directory record for this place, so road, power, "
            "banking and market access could not be checked.",
            Fact(None, None, VD_SOURCE, 2011, "district", "low",
                 note="Village Directory covers rural places only; this is "
                      "likely a town.")))
    else:
        r = a.iloc[0]

        def vd(col, unit=None, note_extra="") -> Fact:
            v = r[col]
            return Fact(
                None if pd.isna(v) else (int(v) if float(v).is_integer()
                                         else float(v)),
                unit, VD_SOURCE, 2011, "village", "high",
                note=f"Village Directory column `{col}`. {note_extra}".strip())

        if rf.get("requires_all_weather_road") and r["rd_all_wthr"] == 0:
            out.append(_flag(
                "NO_ALL_WEATHER_ROAD", "high",
                "No all-weather road. This sector needs daily collection — "
                "without a road there is no buyer in the monsoon.",
                vd("rd_all_wthr", "0/1")))

        if r["power_all"] == 0:
            out.append(_flag(
                "NO_POWER", "medium",
                "No power supply recorded in the village.",
                vd("power_all", "0/1")))

        if r["comm_bank"] == 0 and r["coop_bank"] == 0:
            out.append(_flag(
                "NO_BANK_IN_VILLAGE", "low",
                "No commercial or cooperative bank branch in the village; "
                "loan servicing and deposits mean travelling.",
                vd("comm_bank", "0/1",
                   "Cooperative bank column `coop_bank` also 0.")))

        if float(r["town_dist"]) >= 20:
            out.append(_flag(
                "FAR_FROM_TOWN", "medium",
                f"Nearest town is {float(r['town_dist']):.0f} km away, which "
                "raises input and transport cost.",
                vd("town_dist", "km")))

        if rf.get("requires_veterinary_access") and r["vet_hosp"] == 0:
            out.append(_flag(
                "NO_VET_IN_VILLAGE", "medium",
                "No veterinary hospital in the village. Animal illness is the "
                "single largest cash-flow shock in this sector.",
                vd("vet_hosp", "0/1")))

    # ---- market-derived ----
    role = sector["market_mapping"].get("role")
    if role == "procurement_capacity":
        cap = market.get("procurement_capacity")
        if cap is not None and (cap.value or 0) == 0:
            out.append(_flag(
                "NO_BUYER_IN_CATCHMENT", "high",
                "No dairy processing employment anywhere in the 8 km "
                "catchment — there is no recorded buyer for the milk.",
                cap))
        elif cap is not None and (cap.value or 0) < 20:
            out.append(_flag(
                "SINGLE_BUYER_DEPENDENCY", "medium",
                f"Only {cap.value} people are employed in milk processing "
                "within 8 km, suggesting one small buyer and little "
                "bargaining power.",
                cap))
    else:
        pct = market.get("saturation_percentile")
        if pct is not None and (pct.value or 0) >= 75:
            out.append(_flag(
                "MARKET_SATURATION", "high",
                f"More crowded than {pct.value}% of villages in the district.",
                pct))

    g = market.get("growth_signal")
    if g is not None and g.value is not None and float(g.value) <= 0:
        out.append(_flag(
            "STAGNANT_LOCAL_ECONOMY", "medium",
            "Night-light radiance is flat or falling since 2012 — the local "
            "economy is not growing.",
            g))

    # ---- seasonality: absent by design, not by omission ----
    seas = sector.get("seasonality", {})
    if seas.get("source") == "none":
        out.append(_flag(
            "SEASONALITY_UNKNOWN", "low",
            "Seasonal price risk could NOT be assessed for this sector.",
            Fact(None, None, "Agmarknet / data.gov.in", 2026, "national", "low",
                 note=seas.get("reason", "No price history available."))))

    out.sort(key=lambda f: -SEVERITY_ORDER[f["severity"]])
    return out


def monte_carlo(afford: dict[str, Fact], scheme: dict, principal: float,
                runs: int = MC_RUNS, seed: int = MC_SEED,
                use_working_capital: bool = True) -> Fact:
    """Survival probability over the loan tenure under shocked cash flow.

    Shocks, all applied to the monthly cash flow:
      * milk price drawn lognormally around the published rate
      * yield drawn around the benchmark
      * a one-month animal illness (opex up, revenue near zero) at ~12%/yr
      * delayed buyer payment pushing one month's revenue into the next
      * ANIMAL MORTALITY at 5%/animal/year. This is the shock that actually
        ends a two-animal household unit: losing one animal halves income
        until it is replaced, and the replacement is a capital outlay the
        cash flow has to absorb. The 5% rate is not tuned — it is the
        insurance premium NABARD's own model project charges (5% of asset
        value per year), which is that model's own pricing of this risk.

    'Survival' = the household never runs a cumulative cash deficit while
    servicing the EMI. It is not a credit score; it is a cash-flow stress test.

    The run STARTS with the working-capital floor as an opening balance, because
    that reserve is carved out of the loan before capex precisely so the first
    bad month does not end the business. Modelling it as starting from zero made
    survival a step function — every scenario died on an early shock regardless
    of how much was borrowed, which destroyed the contrast between borrowing
    levels that this figure exists to show.
    """
    rng = np.random.default_rng(seed)
    rev = float(afford["monthly_revenue"].value)
    opex = float(afford["monthly_opex"].value)
    draw = float(afford["household_drawings"].value or 0.0)
    months = int(scheme["repayment_years"]) * 12
    mor = int(scheme.get("moratorium_months", 0))
    emi = emi_for_principal(scheme, principal)

    price_mult = rng.lognormal(0.0, 0.12, size=(runs, months))
    yield_mult = rng.lognormal(0.0, 0.10, size=(runs, months))
    illness = rng.random((runs, months)) < (0.12 / 12.0)
    delayed = rng.random((runs, months)) < 0.08

    # Animal mortality. n_animals matters: losing one of two is a 50% income
    # cut, losing one of ten is 10%. Replacement takes REPLACE_MONTHS to
    # arrange and costs the per-animal capex.
    n_animals = max(int(afford["animals"].value)
                    if afford.get("animals") is not None else 1, 1)
    death = rng.random((runs, months)) < (ANIMAL_MORTALITY_ANNUAL / 12.0)
    alive = np.ones((runs, months))
    replace_cost = np.zeros((runs, months))
    for t in range(months):
        if t:
            alive[:, t] = np.minimum(alive[:, t - 1] + (
                1.0 / n_animals if t >= REPLACE_MONTHS else 0.0), 1.0)
        hit = death[:, t]
        alive[:, t] = np.where(hit, np.maximum(
            alive[:, t] - 1.0 / n_animals, 0.0), alive[:, t])
        replace_cost[:, t] = np.where(hit, ANIMAL_REPLACEMENT_INR, 0.0)

    revenue = rev * price_mult * yield_mult * alive
    revenue = np.where(illness, revenue * 0.15, revenue)
    costs = np.where(illness, opex * 1.35, opex) + replace_cost

    # A delayed payment moves this month's revenue into next month.
    shifted = np.zeros_like(revenue)
    carried = np.zeros(runs)
    for t in range(months):
        got = np.where(delayed[:, t], 0.0, revenue[:, t]) + carried
        carried = np.where(delayed[:, t], revenue[:, t], 0.0)
        shifted[:, t] = got

    due = np.full(months, emi)
    due[:mor] = 0.0                       # moratorium: nothing payable yet
    net = shifted - costs - draw - due

    opening = 0.0
    if use_working_capital:
        wc = afford.get("working_capital_floor")
        opening = float(wc.value) if wc is not None and wc.value else 0.0

    cumulative = np.cumsum(net, axis=1) + opening
    survived = (cumulative.min(axis=1) >= 0).mean()

    return derive(
        round(float(survived), 3), "probability",
        f"Monte Carlo, {runs} runs, seed {seed}: price sd 12%, yield sd 10%, "
        f"12%/yr illness, 8% delayed payment, over {months} months at a "
        f"principal of INR {principal:,.0f}, opening working-capital balance "
        f"INR {opening:,.0f}",
        afford["monthly_revenue"], afford["monthly_opex"],
        afford["household_drawings"],
    )
