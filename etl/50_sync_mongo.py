#!/usr/bin/env python3
"""Phase 1 — push the non-geospatial layer into MongoDB.

The storage split:
  PostGIS  — geometry and anything joined to it (catchment, spatial joins)
  MongoDB  — documents: scheme rules, sector templates, run logs, provenance,
             cached API responses

Scheme rules and sector templates stay committed as YAML in git (PART 10 — the
versioned rules file *is* the feature). Mongo holds a served copy keyed by
content hash, so a run log can point at exactly the rule version it used.

Usage:  python etl/50_sync_mongo.py
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.db import DISTRICT_NAME, SHRID_PREFIX, engine, mongo_db  # noqa: E402


def bsonify(o):
    """YAML gives datetime.date; BSON only encodes datetime. Keep dates as ISO
    strings so the stored rule reads the same as the committed YAML."""
    import datetime as _dt
    if isinstance(o, _dt.datetime):
        return o
    if isinstance(o, _dt.date):
        return o.isoformat()
    if isinstance(o, dict):
        return {k: bsonify(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [bsonify(v) for v in o]
    return o


def digest(obj) -> str:
    return hashlib.sha256(
        yaml.safe_dump(obj, sort_keys=True).encode()).hexdigest()[:16]


def sync_dir(db, src: Path, coll: str, id_field: str) -> int:
    n = 0
    for f in sorted(src.glob("*.yaml")):
        doc = bsonify(yaml.safe_load(f.read_text()))
        key = doc.get(id_field) or f.stem
        db[coll].replace_one(
            {"_id": key},
            {**doc, "_id": key, "_source_file": str(f.relative_to(ROOT)),
             "_content_hash": digest(doc),
             "_synced_at": datetime.now(timezone.utc)},
            upsert=True)
        print(f"[mongo] {coll}/{key}  hash={digest(doc)}")
        n += 1
    return n


def main() -> int:
    db = mongo_db()

    ns = sync_dir(db, ROOT / "data" / "rules" / "schemes", "scheme_rules",
                  "scheme_id")
    nt = sync_dir(db, ROOT / "data" / "sectors", "sector_templates", "sector_id")

    # Load manifest — what Phase 1 actually put in Postgres, so any later run
    # can be reproduced against the same data vintage.
    eng = engine()
    tables = {}
    with eng.connect() as c:
        for t in ["shrid_names", "shrid_geom", "pca_village", "ec_village",
                  "ec_village_sector", "secc_village", "amenities",
                  "nightlights", "shric_desc", "shric_nic08"]:
            tables[t] = c.execute(text(f"SELECT count(*) FROM {t}")).scalar()
        area = c.execute(text("SELECT round(sum(area_km2)::numeric,1) "
                              "FROM shrid_geom")).scalar()
        pop = c.execute(text("SELECT sum(tot_p) FROM pca_village")).scalar()

    manifest = {
        "_id": "phase1_load",
        "phase": 1,
        "district": DISTRICT_NAME,
        "shrid_prefix": SHRID_PREFIX,
        "shrug_version": "v2.2 pakora",
        "tables": tables,
        "district_area_km2": float(area),
        "district_population_2011": int(pop),
        "scheme_rules_synced": ns,
        "sector_templates_synced": nt,
        "loaded_at": datetime.now(timezone.utc),
    }
    db["load_manifest"].replace_one({"_id": "phase1_load"}, manifest, upsert=True)
    print(f"[mongo] load_manifest/phase1_load  "
          f"{sum(tables.values()):,} rows across {len(tables)} tables")

    print("\n[mongo] collections now present:")
    for c in sorted(db.list_collection_names()):
        print(f"        {c:<20} {db[c].count_documents({}):>4} docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
