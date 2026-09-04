#!/usr/bin/env python3
"""Phase 1 — load the target district's non-geometric SHRUG tables into Postgres.

Column names come from what Phase 0 recon actually found (see RECON.md and
data/derived/column_contract.json), never from IMPLEMENTATION_PLAN.md.

Only one district is loaded. Full-India is a scaling exercise, not a prototype
requirement, and the subset is a plain prefix scan on shrid2.

Usage:  python etl/10_load_shrug.py [--raw data/raw] [--drop]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import DISTRICT_NAME, SHRID_PREFIX, engine  # noqa: E402

R = "shrug/"


def log(msg: str) -> None:
    print(f"[load] {msg}", flush=True)


def target_shrids(raw: Path) -> set[str]:
    nm = pd.read_csv(
        raw / R / "shrug-shrid-keys-csv" / "shrid_loc_names.csv",
        usecols=["shrid2", "district_name"], dtype=str,
    )
    return set(nm.loc[nm["district_name"] == DISTRICT_NAME, "shrid2"])


def subset(path: Path, cols: list[str] | None, tgt: set[str]) -> pd.DataFrame:
    """Read a SHRUG csv and keep only the target district's rows."""
    use = None
    if cols:
        have = set(pd.read_csv(path, nrows=0).columns)
        missing = [c for c in cols if c not in have]
        if missing:
            raise SystemExit(
                f"FATAL: {path.name} is missing {missing}. Re-run etl/00_recon.py "
                "— the upstream schema changed and the column contract is stale."
            )
        use = cols
    df = pd.read_csv(path, usecols=use, dtype={"shrid2": str})
    if use:
        # pandas returns usecols in FILE order, not the order asked for.
        # Reorder explicitly — positional renaming downstream would silently
        # mislabel every column otherwise.
        df = df[use]
    return df[df["shrid2"].isin(tgt)].copy()


def write(df: pd.DataFrame, table: str, eng, pk: str | list[str] | None = "shrid2"):
    df.to_sql(table, eng, if_exists="replace", index=False, chunksize=5000,
              method="multi")
    with eng.begin() as c:
        if pk:
            cols = pk if isinstance(pk, str) else ", ".join(pk)
            c.execute(text(f'ALTER TABLE {table} ADD PRIMARY KEY ({cols})'))
    log(f"{table:<22} {len(df):>7,} rows, {df.shape[1]:>3} cols")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    args = ap.parse_args()
    raw = Path(args.raw).resolve()
    eng = engine()

    tgt = target_shrids(raw)
    log(f"district '{DISTRICT_NAME}' -> {len(tgt):,} shrids (prefix {SHRID_PREFIX})")

    # ---- names: the spine for fuzzy resolution (M1) ----
    df = subset(raw / R / "shrug-shrid-keys-csv" / "shrid_loc_names.csv", None, tgt)
    write(df, "shrid_names", eng)

    # ---- population (M2 catchment) ----
    df = subset(raw / R / "shrug-pca11-csv" / "pc11_pca_clean_shrid.csv",
                ["shrid2", "pc11_pca_tot_p", "pc11_pca_no_hh"], tgt)
    df = df.rename(columns={"pc11_pca_tot_p": "tot_p",
                            "pc11_pca_no_hh": "no_hh"})
    write(df, "pca_village", eng)

    # ---- economic census: headline + sector employment ----
    ec_path = raw / R / "shrug-ec13-csv" / "ec13_shrid.csv"
    head = set(pd.read_csv(ec_path, nrows=0).columns)
    shric_cols = sorted(
        (c for c in head if c.startswith("ec13_emp_shric_")),
        key=lambda c: int(c.rsplit("_", 1)[1]),
    )
    df = subset(ec_path, ["shrid2", "ec13_count_all", "ec13_emp_all"] + shric_cols,
                tgt)
    write(df[["shrid2", "ec13_count_all", "ec13_emp_all"]]
          .rename(columns={"ec13_count_all": "count_all",
                           "ec13_emp_all": "emp_all"}),
          "ec_village", eng)

    # Long format: one row per (village, sector). Makes "employment in sector X"
    # an indexed lookup instead of a 90-column pivot.
    long = df.melt(id_vars="shrid2", value_vars=shric_cols,
                   var_name="shric", value_name="emp")
    long["shric"] = long["shric"].str.rsplit("_", n=1).str[1].astype(int)
    long = long[long["emp"].notna()]
    write(long, "ec_village_sector", eng, pk=["shrid2", "shric"])

    # ---- SECC (M4 household drawings) ----
    df = subset(raw / R / "shrug-secc-mord-rural-csv" / "secc_rural_shrid.csv",
                ["shrid2", "secc_hh", "inc_5k_plus_share", "inc_10k_plus_share",
                 "ag_inc_hh", "inc_source_enterpr_share",
                 "inc_source_cultiv_share"], tgt)
    write(df, "secc_village", eng)

    # ---- Village Directory (M5 risk flags) ----
    vd = ["pc11_vd_rd_all_wthr", "pc11_vd_rd_p_btr", "pc11_vd_rd_k_grav",
          "pc11_vd_power_all", "pc11_vd_power_dom",
          "pc11_vd_comm_bank", "pc11_vd_coop_bank", "pc11_vd_acs",
          "pc11_vd_shg", "pc11_vd_atm_dist",
          "pc11_vd_mrkt", "pc11_vd_wkl_haat", "pc11_vd_ams",
          "pc11_vd_vet_hosp",
          "pc11_vd_town_dist", "pc11_vd_subdistrict_hq_dist",
          "pc11_vd_land_pst_grz", "pc11_vd_land_nt_swn", "pc11_vd_land_src_irr"]
    df = subset(raw / R / "shrug-vd11-csv" / "pc11_vd_clean_shrid.csv",
                ["shrid2"] + vd, tgt)
    df = df.rename(columns={c: c.replace("pc11_vd_", "") for c in vd})
    write(df, "amenities", eng)

    # ---- night lights (M2 growth signal), long format 2012-2023 ----
    df = subset(raw / R / "shrug-viirs-annual-csv" / "viirs_annual_shrid.csv",
                ["shrid2", "year", "category", "viirs_annual_mean",
                 "viirs_annual_sum"], tgt)
    df = df.rename(columns={"viirs_annual_mean": "mean",
                            "viirs_annual_sum": "sum"})
    df["year"] = df["year"].astype(int)
    write(df, "nightlights", eng, pk=["shrid2", "year", "category"])

    # ---- SHRIC crosswalk: the sector filter M2 needs ----
    d = pd.read_csv(raw / R / "shrug-shric-desc-csv" / "shric_descriptions.csv")
    d["shric"] = d["shric"].astype(int)
    write(d, "shric_desc", eng, pk="shric")

    n8 = pd.read_csv(raw / R / "shrug-shric-nic08-3d-csv" / "shric_NIC08_3d_key.csv")
    n8.columns = ["nic08_3d", "shric"]
    n8 = n8.astype(int)
    write(n8, "shric_nic08", eng, pk="nic08_3d")

    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
