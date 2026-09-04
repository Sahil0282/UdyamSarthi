#!/usr/bin/env python3
"""Phase 1 — load the district's village polygons into PostGIS.

Two geometry columns are stored on purpose:

  geom    EPSG:4326  — for the map (MapLibre wants lon/lat)
  geom_m  EPSG:32643 — UTM 43N, for buffering and distance

PART 10 forbids buffering in EPSG:4326 degrees, so every metric operation runs
against geom_m. Reprojecting once at load time keeps that mistake impossible
later rather than merely discouraged.

Usage:  python etl/20_load_polygons.py [--raw data/raw]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import (SRID_METRIC, SRID_WGS84, district_names,  # noqa: E402
                     engine, shrid_prefixes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    args = ap.parse_args()
    raw = Path(args.raw).resolve()
    shp = raw / "shrug" / "shrug-shrid-poly-shp" / "shrid2_open.shp"

    # Push the district filter into the driver — reads ~1,600 features out of
    # 595,438 without materialising the 615 MB file.
    where = " OR ".join(f"shrid2 LIKE '{p}%'" for p in shrid_prefixes())
    print(f"[geo] reading {shp.name} for {len(shrid_prefixes())} districts: "
          f"{', '.join(district_names())}", flush=True)
    g = gpd.read_file(shp, where=where)
    print(f"[geo] {len(g):,} polygons, crs={g.crs}", flush=True)

    invalid = int((~g.geometry.is_valid).sum())
    if invalid:
        print(f"[geo] repairing {invalid} invalid geometries with buffer(0)")
        g.loc[~g.geometry.is_valid, "geometry"] = g.loc[
            ~g.geometry.is_valid, "geometry"].buffer(0)

    g = g[["shrid2", "polysource", "geometry"]].set_crs(SRID_WGS84, allow_override=True)
    gm = g.to_crs(SRID_METRIC)
    g["area_km2"] = gm.geometry.area / 1e6

    eng = engine()
    g.to_postgis("shrid_geom", eng, if_exists="replace", index=False)

    with eng.begin() as c:
        # Add the metric geometry alongside, computed in-database.
        c.execute(text(
            f"ALTER TABLE shrid_geom ADD COLUMN geom_m "
            f"geometry(MultiPolygon, {SRID_METRIC})"))
        c.execute(text(
            f"UPDATE shrid_geom SET geom_m = "
            f"ST_Multi(ST_Transform(geometry, {SRID_METRIC}))"))
        c.execute(text("ALTER TABLE shrid_geom ADD PRIMARY KEY (shrid2)"))
        n = c.execute(text("SELECT count(*) FROM shrid_geom "
                           "WHERE geom_m IS NOT NULL")).scalar()
    print(f"[geo] loaded {len(g):,} polygons, {n:,} reprojected to "
          f"EPSG:{SRID_METRIC}")
    print(f"[geo] total area {g['area_km2'].sum():,.0f} km2 "
          f"(median village {g['area_km2'].median():.1f} km2)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
