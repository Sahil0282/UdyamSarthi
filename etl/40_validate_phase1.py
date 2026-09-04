#!/usr/bin/env python3
"""Phase 1 gate — the three queries PART 8 requires before Phase 2 starts.

  1. sector activity in village Y
  2. catchment population within 8 km of Y
  3. household economics in Y

Two of the three had to change shape because of what Phase 0 found, and the
changes are printed alongside the results rather than hidden:

  * Query 1 asks for "establishments in sector X". The Economic Census has no
    establishment count by sector — only employment across 90 SHRIC buckets.
    It reports employment, and says so.
  * Query 3 asks for "avg household consumption". SECC carries no consumption
    column, only income-bracket shares. It reports those, and says so.

Usage:  python etl/40_validate_phase1.py [--village NAME] [--sector-shric 7]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import SRID_METRIC, engine  # noqa: E402

CATCHMENT_KM = 8.0


def hr(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def resolve(eng, name: str) -> pd.DataFrame:
    """M1's job in miniature: fuzzy match, return ALL candidates, never pick."""
    # similarity() rather than the % operator: SQLAlchemy's text() and psycopg's
    # pyformat paramstyle both want to escape '%', and they fight over it. The
    # GIN trgm indexes still serve M1's production path; at 1,597 rows in one
    # district the scan cost here is irrelevant.
    q = text("""
        SELECT shrid2, place_name, village_name, town_name, subdistrict_name,
               similarity(place_name, :n) AS score
          FROM shrid_names
         WHERE similarity(place_name, :n) >= :thr
         ORDER BY score DESC, place_name
         LIMIT 10
    """)
    return pd.read_sql(q, eng, params={"n": name, "thr": 0.3})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--village", default="sangamner")
    ap.add_argument("--sector-shric", type=int, default=7)
    args = ap.parse_args()
    eng = engine()

    # ---------------- resolution ----------------
    hr(f"RESOLUTION — fuzzy match on '{args.village}' (pg_trgm)")
    cand = resolve(eng, args.village)
    print(cand.to_string(index=False))
    if cand.empty:
        print("no candidates"); return 1
    if len(cand) > 1 and cand.iloc[0]["score"] < 0.999:
        print(f"\n{len(cand)} candidates above threshold — M1 must ask the user. "
              "Taking the top match for validation only.")
    shrid = cand.iloc[0]["shrid2"]
    label = cand.iloc[0]["place_name"]
    print(f"\nusing shrid2={shrid}  ({label}, {cand.iloc[0]['subdistrict_name']})")

    with eng.connect() as c:
        sector = c.execute(text("SELECT shric_desc FROM shric_desc WHERE shric=:s"),
                           {"s": args.sector_shric}).scalar()

    # ---------------- Q1 ----------------
    hr(f"QUERY 1 — sector activity in village Y  [SHRIC {args.sector_shric} "
       f"= {sector}]")
    print("PLAN ASKED FOR: establishments in sector X in village Y")
    print("DATA SUPPORTS : employment in sector X (no per-sector establishment")
    print("                count exists in the Economic Census). See RECON.md s0.\n")
    q1 = text("""
        SELECT n.place_name, n.subdistrict_name,
               s.emp        AS sector_employment_2013,
               e.emp_all    AS all_sector_employment_2013,
               e.count_all  AS all_sector_establishments_2013,
               round((100.0 * s.emp / NULLIF(e.emp_all,0))::numeric, 2)
                            AS pct_of_village_employment
          FROM ec_village_sector s
          JOIN ec_village  e USING (shrid2)
          JOIN shrid_names n USING (shrid2)
         WHERE s.shrid2 = :shrid AND s.shric = :shric
    """)
    print(pd.read_sql(q1, eng, params={"shrid": shrid,
                                       "shric": args.sector_shric})
          .to_string(index=False))

    # ---------------- Q2 ----------------
    hr(f"QUERY 2 — catchment population within {CATCHMENT_KM:g} km of Y")
    print(f"Buffer computed in EPSG:{SRID_METRIC} (metres), NOT in 4326 degrees.")
    print("Distance decay w = 1/(1+d^2) per PART 6 M2 step 4.\n")
    q2 = text(f"""
        WITH me AS (
            SELECT geom_m FROM shrid_geom WHERE shrid2 = :shrid
        ), ring AS (
            SELECT ST_Buffer(geom_m, :radius) AS g FROM me
        ), nb AS (
            SELECT g.shrid2,
                   ST_Distance(g.geom_m, me.geom_m) / 1000.0 AS dist_km,
                   p.tot_p
              FROM shrid_geom g
              JOIN pca_village p USING (shrid2)
              CROSS JOIN me
              CROSS JOIN ring
             WHERE ST_Intersects(g.geom_m, ring.g)
        )
        SELECT count(*)                                   AS villages_in_ring,
               sum(tot_p)                                 AS raw_population,
               round(sum(tot_p / (1 + dist_km * dist_km))::numeric, 0)
                                                          AS decay_weighted_population,
               round(max(dist_km)::numeric, 2)            AS furthest_km
          FROM nb
    """)
    print(pd.read_sql(q2, eng, params={"shrid": shrid,
                                       "radius": CATCHMENT_KM * 1000})
          .to_string(index=False))

    print(f"\nSector activity across the same catchment "
          f"(SHRIC {args.sector_shric} = {sector}):")
    q2b = text(f"""
        WITH me AS (SELECT geom_m FROM shrid_geom WHERE shrid2 = :shrid),
        ring AS (SELECT ST_Buffer(geom_m, :radius) AS g FROM me)
        SELECT count(*) FILTER (WHERE s.emp > 0) AS places_with_activity,
               sum(s.emp)                        AS catchment_sector_employment
          FROM shrid_geom g
          JOIN ec_village_sector s
            ON s.shrid2 = g.shrid2 AND s.shric = :shric
          CROSS JOIN ring
         WHERE ST_Intersects(g.geom_m, ring.g)
    """)
    print(pd.read_sql(q2b, eng, params={"shrid": shrid, "shric": args.sector_shric,
                                        "radius": CATCHMENT_KM * 1000})
          .to_string(index=False))

    # ---------------- Q3 ----------------
    hr("QUERY 3 — household economics in Y")
    print("PLAN ASKED FOR: avg household consumption (SECC)")
    print("DATA SUPPORTS : income-bracket shares — SECC-MORD has no consumption")
    print("                column. See RECON.md s0.\n")
    q3 = text("""
        SELECT n.place_name,
               s.secc_hh                       AS secc_households,
               p.no_hh                          AS census_households,
               round((100*s.inc_5k_plus_share)::numeric,1)  AS pct_hh_income_over_5k,
               round((100*s.inc_10k_plus_share)::numeric,1) AS pct_hh_income_over_10k,
               round(s.ag_inc_hh::numeric,1)    AS ag_income_hh,
               round((100*s.inc_source_cultiv_share)::numeric,1) AS pct_income_cultivation
          FROM secc_village s
          JOIN shrid_names n USING (shrid2)
          LEFT JOIN pca_village p USING (shrid2)
         WHERE s.shrid2 = :shrid
    """)
    r3 = pd.read_sql(q3, eng, params={"shrid": shrid})
    print(r3.to_string(index=False) if len(r3) else
          "no SECC row — this is a town; SECC-MORD is rural only. "
          "M4 must degrade to subdistrict and label geo_level.")

    hr("SANITY — district totals")
    print(pd.read_sql(text("""
        SELECT (SELECT count(*) FROM shrid_names)                       AS shrids,
               (SELECT count(*) FROM shrid_geom)                        AS polygons,
               (SELECT round(sum(area_km2)::numeric,0) FROM shrid_geom) AS area_km2,
               (SELECT sum(tot_p) FROM pca_village)                     AS population,
               (SELECT sum(emp) FROM ec_village_sector WHERE shric=:s)  AS sector_emp
    """), eng, params={"s": args.sector_shric}).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
