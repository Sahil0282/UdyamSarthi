#!/usr/bin/env python3
"""Phase 1 — materialise the catchment neighbour graph.

The 8 km catchment is a polygon-to-polygon spatial self-join over the whole
district. Computed on demand it costs ~45 s per query; computed once it costs
nothing, and every sector reuses the same pairs because the geometry does not
depend on which sector is being asked about.

Stores edge distance in km, so a village touching the subject is 0.0.

Usage:  python etl/35_build_catchments.py [--km 8]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import engine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--km", type=float, default=8.0)
    args = ap.parse_args()
    eng = engine()

    t0 = time.time()
    with eng.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS village_neighbours"))
        c.execute(text("""
            CREATE TABLE village_neighbours AS
            SELECT a.shrid2                                        AS shrid2,
                   b.shrid2                                        AS neighbour,
                   ST_Distance(a.geom_m, b.geom_m) / 1000.0        AS dist_km
              FROM shrid_geom a
              JOIN shrid_geom b
                ON ST_DWithin(a.geom_m, b.geom_m, :r)
        """), {"r": args.km * 1000})
        c.execute(text("ALTER TABLE village_neighbours "
                       "ADD PRIMARY KEY (shrid2, neighbour)"))
        c.execute(text("CREATE INDEX village_neighbours_nb "
                       "ON village_neighbours (neighbour)"))
        c.execute(text("COMMENT ON TABLE village_neighbours IS "
                       f"'{args.km} km polygon-edge catchment graph, EPSG:32643'"))

        # Population side of the catchment never changes with sector either.
        c.execute(text("DROP MATERIALIZED VIEW IF EXISTS catchment_population"))
        c.execute(text("""
            CREATE MATERIALIZED VIEW catchment_population AS
            SELECT n.shrid2,
                   COUNT(*)                                          AS n_villages,
                   SUM(p.tot_p)                                      AS raw_pop,
                   SUM(p.tot_p / (1 + POWER(n.dist_km, 2)))          AS decay_pop
              FROM village_neighbours n
              JOIN pca_village p ON p.shrid2 = n.neighbour
             GROUP BY n.shrid2
        """))
        c.execute(text("CREATE UNIQUE INDEX catchment_population_pk "
                       "ON catchment_population (shrid2)"))
        c.execute(text("ANALYZE village_neighbours"))

    with eng.connect() as c:
        edges = c.execute(text("SELECT count(*) FROM village_neighbours")).scalar()
        rows = c.execute(text("SELECT count(*) FROM catchment_population")).scalar()
        avg = c.execute(text("SELECT round(avg(n_villages),1) "
                             "FROM catchment_population")).scalar()
    print(f"[catch] {edges:,} neighbour pairs, {rows:,} villages, "
          f"avg {avg} villages per {args.km:g} km catchment "
          f"({time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
