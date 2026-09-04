"""Database connections.

Two stores, deliberately:

* **PostGIS** holds geometry and anything joined to it. The 8 km catchment is a
  real spatial operation (reproject, buffer, intersect) and is the core of the
  Market Engine.
* **MongoDB** holds everything document-shaped and non-geospatial: run logs,
  provenance records, scheme rules, sector templates, cached API responses.

Neither substitutes for the other.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# override=True: the .env file is the source of truth. A stale key left
# exported in the shell must not silently beat the one in the file.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

# Target districts. Names and prefixes discovered in Phase 0 recon, not assumed:
# every shrid2 in a district shares a prefix, so subsetting is a prefix scan and
# needs no join.
#
# Catchments deliberately cross these boundaries. An 8 km ring is a geographic
# fact, not an administrative one — a village 3 km away is a real neighbour even
# if it sits in the next district. Percentile ranking, by contrast, stays inside
# the village's OWN district, because that is the comparison the Fact claims to
# make ("more crowded than X% of villages in this district").
DISTRICTS: dict[str, str] = {
    "ahmadnagar": "11-27-522-",
    "pune":       "11-27-521-",
    "nashik":     "11-27-516-",
    "thane":      "11-27-517-",
    "satara":     "11-27-527-",
}

# Kept for the single-district code paths and for backwards compatibility.
DISTRICT_NAME = "ahmadnagar"
SHRID_PREFIX = DISTRICTS[DISTRICT_NAME]


def district_names() -> list[str]:
    return sorted(DISTRICTS)


def shrid_prefixes() -> list[str]:
    return [DISTRICTS[d] for d in sorted(DISTRICTS)]

# Buffer in a metric CRS. PART 10 forbids buffering in EPSG:4326 degrees.
SRID_WGS84 = 4326
SRID_METRIC = 32643          # UTM 43N — covers this district's 73.6-75.6E


def pg_url() -> str:
    return (
        f"postgresql+psycopg://{os.getenv('PGUSER', 'udyam')}:"
        f"{os.getenv('PGPASSWORD', 'udyam')}@"
        f"{os.getenv('PGHOST', 'localhost')}:{os.getenv('PGPORT', '5433')}/"
        f"{os.getenv('PGDATABASE', 'udyam')}"
    )


def engine():
    from sqlalchemy import create_engine

    # pool_pre_ping: Postgres restarts once during first-boot restore of the
    # district bundle, and the healthcheck goes green before that finishes. Any
    # connection pooled in that window is dead. Pre-ping validates and
    # reconnects instead of serving a 500.
    return create_engine(pg_url(), future=True, pool_pre_ping=True)


def mongo():
    from pymongo import MongoClient

    url = os.getenv("MONGO_DB_URL")
    if not url:
        raise RuntimeError("MONGO_DB_URL not set")
    return MongoClient(url, serverSelectionTimeoutMS=15000)


# Atlas users are often scoped to one database. Keep the name configurable so a
# permission grant does not require a code change.
def mongo_db(name: str | None = None):
    return mongo()[name or os.getenv("MONGO_DB_NAME", "udyam")]
