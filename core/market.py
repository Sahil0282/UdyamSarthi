"""M2 — Market Engine.

PART 6 M2, adapted to what the data actually contains (RECON.md section 0):

* The Economic Census has NO establishment count by sector. It has employment
  across 90 SHRIC buckets. Every sector metric here is employment-based, and
  says so in its Fact.
* For dairy the sector bucket is *dairy processing* (NIC 105), which is the
  borrower's BUYER, not their competitor. The sector template declares
  ``market_mapping.role``; this module reads it and refuses to report
  procurement capacity as saturation.

EC13 is 2013 data. Every EC-derived Fact carries year=2013 and a note, and is
used for relative rank, never as a current absolute count.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from sqlalchemy import text

from core.db import engine
from core.facts import Fact, derive

CATCHMENT_KM = 8.0
EC_SOURCE = "Economic Census 2013 (via SHRUG v2.2)"
EC_NOTE = ("Economic Census 2013 — used for relative density and percentile "
           "rank, not as a current absolute count.")
PCA_SOURCE = "Population Census 2011 (via SHRUG v2.2)"
VIIRS_SOURCE = "VIIRS annual night lights 2012-2023 (via SHRUG v2.2)"


def _district_table(shric: int, km: float, eng=None) -> pd.DataFrame:
    """Catchment population and sector employment for EVERY village at once.

    Reads the neighbour graph materialised by etl/35_build_catchments.py. The
    spatial join does not depend on the sector, so it is computed once at load
    time and every sector reuses it; doing it per query cost ~45s.

    `km` is accepted for signature stability but the materialised graph fixes
    the radius — a different radius needs a rebuild, and this asserts that.
    """
    eng = eng or engine()
    return pd.read_sql(text("""
        SELECT cp.shrid2,
               nm.district_name,
               cp.raw_pop,
               cp.decay_pop,
               cp.n_villages,
               COALESCE(SUM(s.emp), 0) AS sector_emp
          FROM catchment_population cp
          JOIN shrid_names nm ON nm.shrid2 = cp.shrid2
          JOIN village_neighbours n ON n.shrid2 = cp.shrid2
          LEFT JOIN ec_village_sector s
                 ON s.shrid2 = n.neighbour AND s.shric = :shric
         GROUP BY cp.shrid2, nm.district_name, cp.raw_pop, cp.decay_pop,
                  cp.n_villages
    """), eng, params={"shric": shric})


@lru_cache(maxsize=8)
def _district_table_cached(shric: int, km: float) -> pd.DataFrame:
    return _district_table(shric, km)


def analyse(shrid: str, sector: dict, km: float = CATCHMENT_KM,
            eng=None) -> dict[str, Fact]:
    """Run the catchment analysis for one village and one sector template."""
    eng = eng or engine()
    mm = sector["market_mapping"]
    shric = int(mm["shric_bucket"])
    role = mm.get("role", "competition")
    sector_label = mm.get("shric_desc", f"SHRIC {shric}")

    if km != CATCHMENT_KM:
        raise ValueError(
            f"catchment graph was materialised at {CATCHMENT_KM:g} km; "
            f"rerun etl/35_build_catchments.py --km {km:g} to change it"
        )
    tbl = _district_table_cached(shric, km)
    if shrid not in set(tbl["shrid2"]):
        raise KeyError(f"{shrid} not in district catchment table")
    me = tbl.set_index("shrid2").loc[shrid]

    out: dict[str, Fact] = {}

    # ---- 4. catchment population, distance-decay weighted ----
    out["catchment_population_raw"] = Fact(
        int(me["raw_pop"]), "persons", PCA_SOURCE, 2011, "village", "high",
        note=f"Sum of population of all {int(me['n_villages'])} villages whose "
             f"polygon lies within {km:g} km.",
    )
    out["catchment_population"] = Fact(
        int(round(me["decay_pop"])), "persons", PCA_SOURCE, 2011, "village",
        "high",
        note=f"Distance-decay weighted, w = 1/(1+d^2), over {km:g} km "
             f"({int(me['n_villages'])} villages).",
    )
    out["villages_in_catchment"] = Fact(
        int(me["n_villages"]), "count", PCA_SOURCE, 2011, "village", "high",
        note=f"Polygons intersecting the {km:g} km ring, buffered in EPSG:32643.",
    )

    # ---- 5. sector activity in the catchment ----
    sector_emp = Fact(
        int(me["sector_emp"]), "persons employed", EC_SOURCE, 2013, "village",
        "medium",
        note=f"Employment in '{sector_label}' (SHRIC {shric} = NIC-2008 "
             f"{','.join(mm['nic_codes']['nic08_3d'])}) summed over the "
             f"{km:g} km catchment. {EC_NOTE}",
    )

    if role == "procurement_capacity":
        # The sign is positive: this is the buyer, not the competition.
        out["procurement_capacity"] = sector_emp
        out["competitors"] = Fact(
            None, "count", EC_SOURCE, 2013, "village", "low",
            note=mm.get("competitor_count", {}).get("reason")
                 or "Not measurable from the Economic Census.",
        )
        out["customers_per_unit"] = Fact(
            None, "persons per unit", EC_SOURCE, 2013, "village", "low",
            note="Not computable: the denominator would be a count of competing "
                 "producers, which the Economic Census does not observe for "
                 "this sector.",
        )
    else:
        out["competitors"] = sector_emp
        cpu = (me["decay_pop"] / max(me["sector_emp"], 1)) if me["sector_emp"] \
            else me["decay_pop"]
        out["customers_per_unit"] = derive(
            round(float(cpu), 1), "persons per employed person",
            "catchment population / sector employment",
            out["catchment_population"], sector_emp,
            note="Denominator is sector EMPLOYMENT, not establishment count — "
                 "the Economic Census has no per-sector establishment count.",
        )

    # ---- 7. percentile rank against every village in the SAME district ----
    #
    # Ranked on sector employment per 1,000 catchment people. Higher = more of
    # this sector per head nearby. What "high" MEANS depends on role, so the
    # note spells it out rather than assuming crowding.
    #
    # The comparison set is the village's own district, even though the
    # catchment itself crosses district lines. Those are different questions:
    # the catchment asks "who is actually near me", which is geography; the
    # percentile asks "how do I compare to my district", which is what the Fact
    # claims. Ranking a Pune village against Satara ones would quietly change
    # the claim being made.
    my_district = str(tbl.loc[tbl["shrid2"] == shrid, "district_name"].iloc[0])
    peers = tbl[tbl["district_name"] == my_district]
    dens = (peers["sector_emp"] / peers["decay_pop"].clip(lower=1)) * 1000.0
    my_dens = float(
        (tbl.loc[tbl["shrid2"] == shrid, "sector_emp"].iloc[0]
         / max(tbl.loc[tbl["shrid2"] == shrid, "decay_pop"].iloc[0], 1)) * 1000.0)
    pct = float((dens < my_dens).mean() * 100.0)
    reading = ("Higher percentile = MORE buyer capacity nearby, which is "
               "favourable for this sector."
               if role == "procurement_capacity" else
               "Higher percentile = MORE crowded.")
    out["sector_density_per_1000"] = derive(
        round(my_dens, 3), "employed per 1,000 catchment persons",
        "sector employment / catchment population",
        sector_emp, out["catchment_population"],
    )
    out["saturation_percentile"] = Fact(
        round(pct, 1), "percentile", EC_SOURCE, 2013, "village", "medium",
        note=f"Rank of this village's catchment '{sector_label}' employment per "
             f"1,000 people against all {len(peers):,} villages in "
             f"{my_district} district. {reading} The 8 km catchment itself "
             f"crosses district boundaries; this comparison does not. {EC_NOTE}",
    )
    out["district_median_density"] = Fact(
        round(float(dens.median()), 3), "employed per 1,000 catchment persons",
        EC_SOURCE, 2013, "district", "medium",
        note=f"Median across {len(peers):,} villages in {my_district} district, "
             "for comparison; district-level by definition.",
    )

    # ---- 8. growth signal: night-lights trend ----
    out["growth_signal"] = _growth(shrid, eng)
    return out


def _growth(shrid: str, eng=None) -> Fact:
    """OLS slope of annual night-lights, 2012-2023. One category only."""
    df = pd.read_sql(text("""
        SELECT year, mean FROM nightlights
         WHERE shrid2 = :s AND category = 'average-masked'
         ORDER BY year
    """), eng or engine(), params={"s": shrid})
    if len(df) < 3:
        return Fact(None, "slope/yr", VIIRS_SOURCE, None, "village", "low",
                    note="Too few night-light observations to fit a trend.")
    slope = float(np.polyfit(df["year"], df["mean"], 1)[0])
    direction = "rising" if slope > 0 else ("flat" if slope == 0 else "falling")
    return Fact(
        round(slope, 4), "radiance/yr", VIIRS_SOURCE,
        int(df["year"].max()), "village", "medium",
        note=f"OLS slope of annual mean radiance {int(df.year.min())}-"
             f"{int(df.year.max())} (average-masked). Local economy {direction}. "
             "Used as a direction cross-check on 2013 Economic Census data.",
    )
