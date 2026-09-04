#!/bin/bash
# Runs once, on first container start, after 00_extensions.sql.
# Restores the pre-built five-district bundle so a clean machine can demo
# without the 8.9 GB raw SHRUG download or an ETL run.
set -e
DUMP=/bundle/mh_5districts.dump
if [ -f "$DUMP" ]; then
  echo "[bundle] restoring $DUMP into $POSTGRES_DB"
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl "$DUMP" \
    || echo "[bundle] pg_restore reported non-fatal issues (continuing)"
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
    "SELECT count(*) AS villages FROM shrid_names;"
else
  echo "[bundle] no dump at $DUMP — run the ETL scripts to populate."
fi
