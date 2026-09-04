#!/usr/bin/env python3
"""Phase 1 — spatial and fuzzy-name indexes.

GIST on both geometry columns (the catchment join), and pg_trgm on the name
columns (M1's fuzzy village resolution). India has heavy duplicate village
names, so M1 must be able to return every candidate cheaply and let the user
pick — never auto-resolve.

Usage:  python etl/30_build_indexes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import engine  # noqa: E402

DDL = [
    # --- spatial ---
    "CREATE INDEX IF NOT EXISTS shrid_geom_gist   ON shrid_geom USING GIST (geometry)",
    "CREATE INDEX IF NOT EXISTS shrid_geom_m_gist ON shrid_geom USING GIST (geom_m)",

    # --- fuzzy name resolution (M1) ---
    "CREATE INDEX IF NOT EXISTS shrid_names_village_trgm ON shrid_names "
    "USING GIN (village_name gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS shrid_names_place_trgm ON shrid_names "
    "USING GIN (place_name gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS shrid_names_subdist_trgm ON shrid_names "
    "USING GIN (subdistrict_name gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS shrid_names_district_trgm ON shrid_names "
    "USING GIN (district_name gin_trgm_ops)",

    # --- lookup paths the engines hit repeatedly ---
    "CREATE INDEX IF NOT EXISTS ec_sector_shric ON ec_village_sector (shric)",
    "CREATE INDEX IF NOT EXISTS ec_sector_emp ON ec_village_sector (shric, emp) "
    "WHERE emp > 0",
    "CREATE INDEX IF NOT EXISTS nightlights_year ON nightlights (category, year)",
]

VIEWS = [
    # One row per village with everything the engines need, so an engine reads
    # a view rather than re-deriving joins. Geometry stays in shrid_geom.
    """
    CREATE OR REPLACE VIEW village AS
    SELECT n.shrid2,
           n.village_name, n.town_name, n.subdistrict_name, n.district_name,
           n.place_name,
           p.tot_p, p.no_hh,
           e.count_all AS ec_establishments, e.emp_all AS ec_employment,
           s.secc_hh, s.inc_5k_plus_share, s.inc_10k_plus_share, s.ag_inc_hh,
           a.rd_all_wthr, a.rd_p_btr, a.power_all, a.comm_bank, a.coop_bank,
           a.mrkt, a.wkl_haat, a.ams, a.vet_hosp, a.town_dist,
           g.area_km2
      FROM shrid_names n
      LEFT JOIN pca_village  p USING (shrid2)
      LEFT JOIN ec_village   e USING (shrid2)
      LEFT JOIN secc_village s USING (shrid2)
      LEFT JOIN amenities    a USING (shrid2)
      LEFT JOIN shrid_geom   g USING (shrid2)
    """,
]


def main() -> int:
    eng = engine()
    with eng.begin() as c:
        for stmt in DDL:
            c.execute(text(stmt))
            print(f"[idx] {stmt.split()[5] if 'INDEX' in stmt else stmt[:40]}",
                  flush=True)
        for v in VIEWS:
            c.execute(text(v))
            print("[idx] view village", flush=True)
        c.execute(text("ANALYZE"))
    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT tablename, indexname FROM pg_indexes "
            "WHERE schemaname='public' ORDER BY tablename, indexname")).all()
    print(f"[idx] {len(rows)} indexes present")
    for t, i in rows:
        print(f"      {t:<20} {i}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
