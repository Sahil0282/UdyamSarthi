"""M1 — Geo-resolution.

India has heavy duplicate village names across subdistricts, so ``resolve()``
returns EVERY candidate above threshold and never picks one. PART 10: do not
auto-resolve an ambiguous village name.

All metric work happens in ``geom_m`` (EPSG:32643, metres). Nothing here
buffers in degrees.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd
from sqlalchemy import text

from core.db import SRID_METRIC, engine

NAME_THRESHOLD = 0.30


@dataclass(frozen=True)
class Candidate:
    shrid2: str
    place_name: str
    village_name: str | None
    town_name: str | None
    subdistrict_name: str
    district_name: str
    population: int | None
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


def resolve(name: str, district_hint: str | None = None,
            threshold: float = NAME_THRESHOLD, limit: int = 10,
            eng=None) -> list[Candidate]:
    """Fuzzy-match a spoken village name. Returns ALL plausible candidates."""
    eng = eng or engine()
    sql = """
        SELECT n.shrid2, n.place_name, n.village_name, n.town_name,
               n.subdistrict_name, n.district_name,
               p.tot_p AS population,
               similarity(n.place_name, :n) AS score
          FROM shrid_names n
          LEFT JOIN pca_village p USING (shrid2)
         WHERE similarity(n.place_name, :n) >= :thr
    """
    params: dict = {"n": name.strip().lower(), "thr": threshold, "lim": limit}
    if district_hint:
        sql += " AND n.district_name = :dist"
        params["dist"] = district_hint.strip().lower()
    sql += " ORDER BY score DESC, n.place_name LIMIT :lim"

    df = pd.read_sql(text(sql), eng, params=params)
    return [
        Candidate(
            shrid2=r.shrid2, place_name=r.place_name,
            village_name=r.village_name, town_name=r.town_name,
            subdistrict_name=r.subdistrict_name, district_name=r.district_name,
            population=int(r.population) if pd.notna(r.population) else None,
            score=round(float(r.score), 4),
        )
        for r in df.itertuples()
    ]


def is_ambiguous(cands: list[Candidate], margin: float = 0.15) -> bool:
    """True when the top match is not clearly ahead — M1 must ask the user."""
    if len(cands) < 2:
        return False
    return (cands[0].score - cands[1].score) < margin


def geometry(shrid: str, eng=None) -> dict:
    """Village polygon plus its metric area. GeoJSON is in 4326 for the map."""
    eng = eng or engine()
    with (eng or engine()).connect() as c:
        row = c.execute(text("""
            SELECT ST_AsGeoJSON(geometry) AS geojson,
                   area_km2,
                   ST_X(ST_Centroid(geometry)) AS lon,
                   ST_Y(ST_Centroid(geometry)) AS lat
              FROM shrid_geom WHERE shrid2 = :s
        """), {"s": shrid}).mappings().first()
    if not row:
        raise KeyError(f"no geometry for {shrid}")
    return dict(row)


def ring_geojson(shrid: str, km: float, eng=None) -> str:
    """The catchment ring, buffered in metres then returned in 4326 for display."""
    eng = eng or engine()
    with eng.connect() as c:
        return c.execute(text(f"""
            SELECT ST_AsGeoJSON(
                     ST_Transform(ST_Buffer(geom_m, :r), 4326))
              FROM shrid_geom WHERE shrid2 = :s
        """), {"s": shrid, "r": km * 1000}).scalar()


def neighbours(shrid: str, km: float, eng=None) -> pd.DataFrame:
    """Every village whose polygon intersects the km-buffer around `shrid`.

    Distance is polygon-to-polygon edge distance in metres (SRID 32643), so a
    village touching the subject returns 0.0 rather than a centroid artefact.
    """
    eng = eng or engine()
    return pd.read_sql(text(f"""
        WITH me AS (SELECT geom_m FROM shrid_geom WHERE shrid2 = :s),
        ring AS (SELECT ST_Buffer(geom_m, :r) AS g FROM me)
        SELECT g.shrid2,
               ST_Distance(g.geom_m, me.geom_m) / 1000.0 AS dist_km,
               p.tot_p AS population,
               n.place_name
          FROM shrid_geom g
          JOIN pca_village p USING (shrid2)
          JOIN shrid_names n ON n.shrid2 = g.shrid2
          CROSS JOIN me
          CROSS JOIN ring
         WHERE ST_Intersects(g.geom_m, ring.g)
         ORDER BY dist_km
    """), eng, params={"s": shrid, "r": km * 1000})


def catchment_points(shrid: str, shric: int, km: float, eng=None) -> list[dict]:
    """Villages in the ring that carry employment in this sector.

    These are the dots on the map. For a procurement sector they are BUYERS;
    for a competitive sector they are rivals. The caller supplies the label so
    the map never asserts the wrong meaning.
    """
    eng = eng or engine()
    df = pd.read_sql(text("""
        SELECT n.place_name, s.emp, vn.dist_km,
               ST_X(ST_Centroid(g.geometry)) AS lon,
               ST_Y(ST_Centroid(g.geometry)) AS lat
          FROM village_neighbours vn
          JOIN ec_village_sector s
            ON s.shrid2 = vn.neighbour AND s.shric = :shric AND s.emp > 0
          JOIN shrid_names n ON n.shrid2 = vn.neighbour
          JOIN shrid_geom  g ON g.shrid2 = vn.neighbour
         WHERE vn.shrid2 = :s
         ORDER BY s.emp DESC
    """), eng, params={"s": shrid, "shric": shric})
    return [
        {"place_name": r.place_name, "employment": float(r.emp),
         "dist_km": round(float(r.dist_km), 2),
         "lon": float(r.lon), "lat": float(r.lat)}
        for r in df.itertuples()
    ]
