#!/usr/bin/env python3
"""
Phase 0 - Data reconnaissance.

Discovers every file under data/raw/ and reports what is ACTUALLY in it:
filename, shape, dtypes, first rows, null counts, candidate join keys, CRS.

Nothing here assumes a filename or a column name. Every later module must read
its column names from the RECON.md this produces, not from the plan document.

Usage:
    python etl/00_recon.py [--raw data/raw] [--out data/derived/RECON.md]
                           [--full-scan-mb 200] [--sample-rows 20000]
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
except Exception:
    pass

try:
    import pyogrio
except ImportError:  # pragma: no cover
    pyogrio = None

# --------------------------------------------------------------------------
# Key detection. These are PATTERNS to look for, not an assertion that they
# exist. Whatever is actually found is what gets reported.
# --------------------------------------------------------------------------
KEY_PATTERNS = [
    r"^shrid\d*$",
    r"^shrid[12]$",
    r"^pc\d+_(state|district|subdistrict|village|town)_id$",
    r"^(state|district|subdistrict|village|town)_id$",
    r"^ec\d+_.*id$",
    r"^census_.*code$",
    r".*_code$",
    r".*_id$",
]
NAME_PATTERNS = [r".*name.*", r"^place_name$"]

# District we care about for the prototype (PART 3.7). Spelling varies across
# vintages: Ahmednagar (census) vs Ahilyanagar (renamed 2024).
DISTRICT_PROBES = ["ahmadnagar", "ahmednagar", "ahilyanagar", "ahilya"]
STATE_PROBES = ["maharashtra"]

MAX_HEAD_ROWS = 5
MAX_COLS_WIDE = 25  # above this, print columns as a vertical list not a table


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} PB"


def fast_line_count(path: Path) -> int | None:
    """wc -l is orders of magnitude faster than pandas for a row count."""
    try:
        out = subprocess.run(
            ["wc", "-l", str(path)], capture_output=True, text=True, timeout=600
        )
        if out.returncode == 0:
            return int(out.stdout.strip().split()[0])
    except Exception:
        pass
    return None


def sniff_sep(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
    except Exception:
        return ","
    counts = {c: first.count(c) for c in [",", "\t", ";", "|"]}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def candidate_keys(df: pd.DataFrame, n_sample: int) -> list[tuple[str, str]]:
    """Return (column, reason) for columns that look like join keys."""
    found: list[tuple[str, str]] = []
    for col in df.columns:
        lc = str(col).strip().lower()
        matched = any(re.match(p, lc) for p in KEY_PATTERNS)
        if not matched:
            continue
        try:
            nunique = df[col].nunique(dropna=True)
            nn = int(df[col].notna().sum())
        except Exception:
            continue
        if nn == 0:
            reason = "all-null in sample"
        elif nunique == nn:
            reason = f"UNIQUE over {nn:,} sampled rows -> primary key candidate"
        else:
            reason = f"{nunique:,} distinct / {nn:,} non-null -> foreign key candidate"
        found.append((str(col), reason))
    return found


def name_columns(df: pd.DataFrame) -> list[str]:
    return [
        str(c)
        for c in df.columns
        if any(re.match(p, str(c).strip().lower()) for p in NAME_PATTERNS)
    ]


def md_table(rows: list[list[str]], header: list[str]) -> str:
    if not rows:
        return "_(none)_\n"
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join(["---"] * len(header)) + "|"]
    for r in rows:
        cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in r]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def profile_csv(path: Path, full_scan_bytes: int, sample_rows: int) -> dict:
    size = path.stat().st_size
    sep = sniff_sep(path)
    full = size <= full_scan_bytes
    info: dict = {
        "path": path,
        "size": size,
        "sep": sep,
        "full_scan": full,
        "error": None,
    }
    try:
        if full:
            df = pd.read_csv(path, sep=sep, dtype_backend="numpy_nullable")
            info["n_rows"] = len(df)
            info["n_rows_exact"] = True
            sample = df
        else:
            sample = pd.read_csv(
                path, sep=sep, nrows=sample_rows, dtype_backend="numpy_nullable"
            )
            lc = fast_line_count(path)
            info["n_rows"] = (lc - 1) if lc else None
            info["n_rows_exact"] = False
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return info

    info["n_cols"] = sample.shape[1]
    info["sample_rows"] = len(sample)
    info["columns"] = [str(c) for c in sample.columns]
    info["dtypes"] = {str(c): str(t) for c, t in sample.dtypes.items()}
    try:
        nulls = sample.isna().sum()
        info["nulls"] = {str(c): int(v) for c, v in nulls.items()}
    except Exception:
        info["nulls"] = {}
    info["keys"] = candidate_keys(sample, len(sample))
    info["name_cols"] = name_columns(sample)
    info["head"] = sample.head(MAX_HEAD_ROWS)
    return info


def profile_shapefile(path: Path) -> dict:
    info: dict = {"path": path, "size": path.stat().st_size, "error": None}
    if pyogrio is None:
        info["error"] = "pyogrio not installed"
        return info
    try:
        meta = pyogrio.read_info(str(path))
        info["n_rows"] = int(meta.get("features", -1))
        info["crs"] = meta.get("crs")
        info["geometry_type"] = meta.get("geometry_type")
        info["columns"] = list(meta.get("fields", []))
        info["dtypes"] = {
            str(f): str(d)
            for f, d in zip(meta.get("fields", []), meta.get("dtypes", []))
        }
        bounds = meta.get("total_bounds")
        info["bounds"] = list(bounds) if bounds is not None else None
        gdf = pyogrio.read_dataframe(str(path), max_features=MAX_HEAD_ROWS)
        attrs = gdf.drop(columns=[gdf.geometry.name], errors="ignore")
        info["head"] = attrs
        info["keys"] = candidate_keys(attrs, len(attrs))
        info["name_cols"] = name_columns(attrs)
        info["nulls"] = {}
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def render_file_section(info: dict, root: Path) -> str:
    p: Path = info["path"]
    rel = p.relative_to(root)
    buf = io.StringIO()
    buf.write(f"\n### `{rel.name}`\n\n")
    buf.write(f"- **Path:** `{rel}`\n")
    buf.write(f"- **Size:** {human(info['size'])}\n")

    if info.get("error"):
        buf.write(f"- **STATUS: FAILED TO READ** — `{info['error']}`\n")
        return buf.getvalue()

    nr = info.get("n_rows")
    exact = info.get("n_rows_exact", True)
    if nr is None:
        buf.write("- **Rows:** unknown\n")
    else:
        buf.write(
            f"- **Rows:** {nr:,}"
            + ("" if exact else " _(line-count approximation; not fully parsed)_")
            + "\n"
        )
    buf.write(f"- **Columns:** {info.get('n_cols', len(info.get('columns', [])))}\n")
    if "crs" in info:
        buf.write(f"- **CRS:** `{info.get('crs')}`\n")
        buf.write(f"- **Geometry:** `{info.get('geometry_type')}`\n")
        b = info.get("bounds")
        if b:
            buf.write(
                f"- **Bounds (minx, miny, maxx, maxy):** "
                f"`{b[0]:.4f}, {b[1]:.4f}, {b[2]:.4f}, {b[3]:.4f}`\n"
            )
    if not info.get("full_scan", True) and "crs" not in info:
        buf.write(
            f"- **Profiling basis:** first {info.get('sample_rows', 0):,} rows "
            "(file too large for a full scan; null counts below are sample-only)\n"
        )

    # candidate keys
    buf.write("\n**Candidate join keys**\n\n")
    keys = info.get("keys") or []
    buf.write(md_table([[f"`{k}`", r] for k, r in keys], ["column", "evidence"]))

    if info.get("name_cols"):
        buf.write(
            "\n**Name columns (for fuzzy village resolution):** "
            + ", ".join(f"`{c}`" for c in info["name_cols"])
            + "\n"
        )

    # schema
    buf.write("\n**Schema**\n\n")
    dtypes = info.get("dtypes", {})
    nulls = info.get("nulls", {})
    denom = info.get("sample_rows") or info.get("n_rows") or 0
    rows = []
    for c in info.get("columns", []):
        nl = nulls.get(c)
        if nl is None:
            nullstr = "—"
        elif denom:
            nullstr = f"{nl:,} ({100.0 * nl / denom:.1f}%)"
        else:
            nullstr = f"{nl:,}"
        rows.append([f"`{c}`", dtypes.get(c, "?"), nullstr])
    buf.write(md_table(rows, ["column", "dtype", "nulls in profiled rows"]))

    # head
    head = info.get("head")
    if head is not None and len(head):
        buf.write(f"\n**First {min(MAX_HEAD_ROWS, len(head))} rows**\n\n```\n")
        with pd.option_context(
            "display.max_columns", None, "display.width", 200,
            "display.max_colwidth", 28,
        ):
            if head.shape[1] > MAX_COLS_WIDE:
                buf.write(head.T.to_string())
                buf.write("\n\n(transposed: this file is wide)")
            else:
                buf.write(head.to_string())
        buf.write("\n```\n")
    return buf.getvalue()


def probe_district(csv_infos: list[dict], root: Path) -> str:
    """Find how the target district and state actually appear in the data."""
    buf = io.StringIO()
    buf.write(
        "\nPhase 1 loads a single district (PART 3.7). The district was renamed\n"
        "Ahmednagar -> Ahilyanagar in 2024, and 1991-2011 census vintages predate\n"
        "that, so the spelling in the data is an empirical question, not a guess.\n"
        "Below is every match found in files that carry name columns.\n\n"
    )
    hits: list[list[str]] = []
    for info in csv_infos:
        if info.get("error") or not info.get("name_cols"):
            continue
        p: Path = info["path"]
        if p.stat().st_size > 600 * 1024 * 1024:
            continue
        try:
            cols = info["name_cols"]
            df = pd.read_csv(p, sep=info.get("sep", ","), usecols=cols, dtype=str)
        except Exception:
            continue
        for c in cols:
            s = df[c].dropna().astype(str).str.lower()
            for probe in DISTRICT_PROBES:
                m = s[s.str.contains(probe, na=False, regex=False)]
                if len(m):
                    vals = sorted(m.unique())[:4]
                    hits.append([
                        f"`{p.relative_to(root)}`",
                        f"`{c}`",
                        probe,
                        f"{len(m):,}",
                        ", ".join(f"`{v}`" for v in vals),
                    ])
                    break
    buf.write(
        md_table(
            hits,
            ["file", "column", "probe", "matching rows", "actual values seen"],
        )
    )
    return buf.getvalue()


# --------------------------------------------------------------------------
# TARGET DISTRICT (PART 3.7). Discovered empirically in section 4 below:
# the district is spelled "ahmadnagar" in SHRUG (not Ahmednagar/Ahilyanagar),
# and every one of its shrid2 values shares this prefix, so the Phase 1
# subset is a string prefix and needs no join.
# --------------------------------------------------------------------------
TARGET_DISTRICT_NAME = "ahmadnagar"
TARGET_SHRID_PREFIX = "11-27-522-"   # census 2011 · state 27 MH · district 522
TARGET_METRIC_CRS = "EPSG:32643"     # UTM 43N — covers 73.6-75.6E. Buffer in THIS.

# --------------------------------------------------------------------------
# COLUMN CONTRACT — what each engine will actually read.
# Written from what recon found, NOT from IMPLEMENTATION_PLAN.md. Verified
# live on every run: if SHRUG ships a new version and renames a column, this
# fails loudly here instead of silently in an engine.
# --------------------------------------------------------------------------
CONTRACT: dict[str, dict] = {
    "M1 geo — resolution + geometry": {
        "shrug/shrug-shrid-keys-csv/shrid_loc_names.csv": [
            "shrid2", "state_name", "district_name", "subdistrict_name",
            "village_name", "town_name", "place_name",
        ],
        "shrug/shrug-shrid-poly-shp/shrid2_open.shp": [
            "shrid2", "pc11_id", "polysource",
        ],
    },
    "M2 market — catchment + saturation": {
        "shrug/shrug-pca11-csv/pc11_pca_clean_shrid.csv": [
            "shrid2", "pc11_pca_tot_p", "pc11_pca_no_hh",
        ],
        "shrug/shrug-ec13-csv/ec13_shrid.csv": [
            "shrid2", "ec13_count_all", "ec13_emp_all",
            "ec13_emp_shric_1", "ec13_emp_shric_45", "ec13_emp_shric_90",
        ],
        "shrug/shrug-viirs-annual-csv/viirs_annual_shrid.csv": [
            "shrid2", "year", "category", "viirs_annual_mean", "viirs_annual_sum",
        ],
    },
    "M4 affordability — household drawings": {
        "shrug/shrug-secc-mord-rural-csv/secc_rural_shrid.csv": [
            "shrid2", "secc_hh", "inc_5k_plus_share", "inc_10k_plus_share",
            "ag_inc_hh", "inc_source_enterpr_share", "inc_source_cultiv_share",
        ],
    },
    "M5 risk — amenities": {
        "shrug/shrug-vd11-csv/pc11_vd_clean_shrid.csv": [
            "shrid2",
            "pc11_vd_rd_all_wthr", "pc11_vd_rd_p_btr", "pc11_vd_rd_k_grav",
            "pc11_vd_power_all", "pc11_vd_power_dom",
            "pc11_vd_comm_bank", "pc11_vd_coop_bank", "pc11_vd_acs",
            "pc11_vd_shg", "pc11_vd_atm_dist",
            "pc11_vd_mrkt", "pc11_vd_wkl_haat", "pc11_vd_ams",
            "pc11_vd_vet_hosp",
            "pc11_vd_town_dist", "pc11_vd_subdistrict_hq_dist",
            "pc11_vd_land_pst_grz", "pc11_vd_land_nt_swn", "pc11_vd_land_src_irr",
        ],
    },
}

# Interpretive conclusions. These are judgements, not measurements — the
# measurements that support them are computed live in sections 1 and 4.
FINDINGS = [
    (
        "BLOCKER",
        "The Economic Census carries NO establishment count by sector.",
        "`ec13_*` exposes 90 `ec13_emp_shric_N` columns (EMPLOYMENT by sector) and "
        "`ec13_count_*` columns broken down only by gender / public-private / firm "
        "size / caste. There is no `count_shric`. Verified across all four vintages "
        "(ec90, ec98, ec05, ec13) — 90 emp_shric columns each, 0 count_shric.\n\n"
        "IMPLEMENTATION_PLAN PART 6 M2 step 5 says `competitors = Sigma EC "
        "establishments filtered to sector NIC codes`. That number cannot be "
        "computed from this data.\n\n"
        "Resolution for Phase 2: M2's primary saturation metric becomes sector "
        "EMPLOYMENT within the catchment, percentile-ranked against the district "
        "— which needs no invented assumption. An implied establishment count may "
        "additionally be derived as `sector_emp / workers_per_unit`, but ONLY if "
        "`workers_per_unit` is itself a sourced field in the sector YAML and the "
        "resulting Fact is labelled confidence=low with the divisor in its note. "
        "It must never be presented as an observed count.",
    ),
    (
        "RESOLVED",
        "SHRIC codebook obtained. Dairy is SHRIC 7.",
        "The four `shrug-shric-*` modules supply the crosswalk that was missing at "
        "first recon: `shric_descriptions.csv` (90 labelled buckets) plus keys to "
        "NIC-2008 3-digit, NIC-2004 and NIC-1987. `shric_desc == \"Dairy\"` is "
        "bucket **7**, and it maps to exactly one NIC-2008 code, **105**, across "
        "every vintage (NIC04 1520, NIC87 201).\n\n"
        "M2's sector filter is unblocked. See section 3 for the full 90-bucket "
        "table and the live sanity check.",
    ),
    (
        "BLOCKER",
        "SHRIC 7 is dairy PROCESSING. Dairy FARMING is not in the Economic Census.",
        "NIC-2008 105 is `Manufacture of dairy products` — milk chilling, "
        "pasteurising, ghee and paneer plants. It is not `Raising of cattle and "
        "buffaloes` (NIC 0141), which is what the borrower in PART 1 actually "
        "wants to do.\n\n"
        "This is structural, not a gap in the download: the lowest NIC-2008 code "
        "appearing anywhere in SHRIC is 021 (forestry). NIC division 01 — crop and "
        "animal production — is absent from all 224 crosswalk rows, because the "
        "Economic Census excludes agricultural production. IMPLEMENTATION_PLAN "
        "PART 5.3 proposes `nic_codes: [\"01410\", \"01440\"]` for dairy; neither "
        "code exists in this data and neither ever will.\n\n"
        "CONSEQUENCE — the sign of the metric flips. A count of dairy activity in "
        "the catchment is NOT a count of competing dairy farmers. It is a count of "
        "BUYERS: milk collection and chilling capacity, the thing PART 1 says the "
        "borrower fails without (`Dairy needs daily collection - no road, no "
        "buyer`). More SHRIC 7 nearby is GOOD, not crowded.\n\n"
        "Resolution for Phase 2: M2 must expose SHRIC 7 as `procurement_capacity` "
        "with a positive sign, and must NOT report it as `competitors`. Wiring it "
        "in as a saturation numerator would invert the verdict. Farmer-level "
        "saturation for dairy is genuinely unmeasurable from the Economic Census "
        "and the envelope must say so via a Fact note rather than substitute a "
        "proxy. This also resolves the `single-buyer dependency` risk flag that "
        "first recon reported as uncomputable.",
    ),
    (
        "PLAN DEVIATION",
        "The join key is `shrid2`, not `shrid`.",
        "`shrid2` appears in 43 files and is unique in every shrid-level table "
        "(596,389 unique values in shrid_loc_names.csv). No column named `shrid` "
        "exists. All later code and SQL must use `shrid2`.",
    ),
    (
        "PLAN DEVIATION",
        "SECC has no household consumption figure.",
        "PART 6 M4 says `household_drawings = f(SECC village avg consumption)`. "
        "`secc_rural_shrid.csv` carries no consumption column. It carries income "
        "STRUCTURE instead: `inc_5k_plus_share`, `inc_10k_plus_share` (share of "
        "households above monthly income thresholds), `ag_inc_hh`, and "
        "`inc_source_*_share`.\n\n"
        "Resolution for Phase 2: derive household drawings from the income-bracket "
        "shares, and label the resulting Fact with a note stating it is inferred "
        "from bracket shares rather than measured consumption. Do not silently "
        "call it consumption.",
    ),
    (
        "RESOLVED",
        "Village Directory DOES carry all-weather road and market amenities.",
        "PART 3.1 warned the SHRUG amenities subset may be too small for M5. It "
        "is not. `pc11_vd_clean_shrid.csv` has 284 columns including "
        "`rd_all_wthr`, `rd_p_btr`, `rd_k_grav` (road type), `power_all`, "
        "`comm_bank` / `coop_bank` / `acs` / `atm_dist` (banking), `mrkt` / "
        "`wkl_haat` / `ams` (market access), `vet_hosp` (dairy-specific), "
        "`town_dist` (distance to town) and the `land_*` land-use block "
        "(fodder capacity). Every M5 risk flag in PART 6 is computable except "
        "single-buyer dependency, which needs procurement-point data SHRUG "
        "does not have. The full Census Village Directory download is NOT needed.",
    ),
    (
        "RESOLVED",
        "Night lights: use VIIRS (2012-2023), not DMSP.",
        "`viirs_annual_shrid.csv` is long-format with `year` 2012-2023 and two "
        "`category` values (average-masked, median-masked) — a 12-year series, "
        "enough for the M2 growth-signal trend slope. DMSP ends around 2013 and "
        "adds nothing. Pick ONE category and state which; do not mix them.",
    ),
    (
        "RESOLVED",
        "District subsetting needs no join, and the metric CRS is EPSG:32643.",
        "Every Ahmadnagar shrid2 starts `11-27-522-`, so Phase 1 subsets with a "
        "string prefix. pyogrio reads the district's polygons straight out of the "
        "615 MB shapefile via `where=\"shrid2 LIKE \'11-27-522-%\'\"` in ~3s. "
        "District bounds are 73.62-75.59E, so UTM 43N (EPSG:32643) is the correct "
        "metric CRS for the 8 km buffer. PART 10 forbids buffering in EPSG:4326.",
    ),
    (
        "BLOCKER",
        "Agmarknet does not carry Milk. The flagship sector has no API price.",
        "`filters[commodity]=Milk` returns 0 records; so does Egg. Agmarknet is an "
        "APMC *mandi* feed — it prices agricultural produce sold at auction. Milk "
        "is procured by dairy cooperatives at an administered rate and never "
        "reaches a mandi, so it is structurally absent, not merely missing today.\n\n"
        "IMPLEMENTATION_PLAN PART 5.3 sets `agmarknet_commodity: \"Milk\"` and "
        "`price_source: agmarknet` for dairy, and PART 6 M4 computes "
        "`monthly_revenue` from an Agmarknet price. For dairy that pipeline has no "
        "input.\n\n"
        "Resolution for Phase 2: dairy's sector YAML must use a fixed procurement "
        "price carried as a Fact with an explicit `source`, `year` and "
        "`geo_level=state`, transcribed from a published cooperative procurement "
        "rate the same way scheme rules are transcribed (PART 3.5). Sectors whose "
        "output IS mandi-traded (goat/live animals, poultry feed grains, kirana "
        "staples) can still use the live feed. Do not silently substitute a "
        "mandi price for a procurement price.",
    ),
    (
        "BLOCKER",
        "The Agmarknet endpoint is a one-day snapshot, not a price history.",
        "An unfiltered call returns 170 records for ALL of India on a single "
        "`arrival_date`, across 12 states and 63 commodities. Maharashtra had 12 "
        "records, from one district (Ratnagiri) — Ahmadnagar did not report at "
        "all. The resource is overwritten daily; there is no historical depth "
        "behind it.\n\n"
        "PART 6 M5 wants a 12-month seasonality index and PART 3.2 wants 3-5 years. "
        "Neither is obtainable from this endpoint today. PART 3.2 option (a) — a "
        "daily cron appending to `mandi_history.parquet` — is the only way to "
        "accumulate history, and it accrues one day per day starting now.\n\n"
        "Resolution for Phase 2: build `etl/40_agmarknet_sync.py` as an appending "
        "daily job immediately so history starts accumulating, and implement PART "
        "3.2 option (b) honestly — the seasonality Fact carries its ACTUAL window "
        "length and confidence=low. With a window under ~12 months the risk engine "
        "must omit the seasonal-collapse flag rather than compute one from noise. "
        "PART 10: do not fabricate a seasonal curve.",
    ),
]


def verify_contract(root: Path) -> tuple[str, dict]:
    """Check every contracted column exists, and measure district coverage."""
    import json

    buf = io.StringIO()
    result: dict = {
        "target_district": TARGET_DISTRICT_NAME,
        "shrid_prefix": TARGET_SHRID_PREFIX,
        "metric_crs": TARGET_METRIC_CRS,
        "engines": {},
    }

    # Resolve the district's shrid set from the names file.
    target: set[str] = set()
    names_rel = "shrug/shrug-shrid-keys-csv/shrid_loc_names.csv"
    names_path = root / names_rel
    if names_path.exists():
        try:
            nm = pd.read_csv(names_path, usecols=["shrid2", "district_name"],
                             dtype=str)
            target = set(
                nm.loc[nm["district_name"] == TARGET_DISTRICT_NAME, "shrid2"]
            )
        except Exception as exc:
            buf.write(f"\n> Could not resolve target district: `{exc}`\n")
    n_target = len(target)
    buf.write(
        f"\nTarget district **`{TARGET_DISTRICT_NAME}`** resolves to "
        f"**{n_target:,} shrids** (prefix `{TARGET_SHRID_PREFIX}`). "
        f"Metric CRS for buffering: **`{TARGET_METRIC_CRS}`**.\n\n"
        "`columns` = every contracted column present. `district rows` = how many "
        "of those shrids the file actually covers.\n"
    )

    rows = []
    for engine, files in CONTRACT.items():
        result["engines"][engine] = {}
        for rel, cols in files.items():
            path = root / rel
            entry: dict = {"path": rel, "columns": cols}
            if not path.exists():
                rows.append([engine, f"`{Path(rel).name}`", "FILE MISSING",
                             "—", "—"])
                entry["status"] = "FILE MISSING"
                result["engines"][engine][rel] = entry
                continue
            try:
                if path.suffix.lower() == ".shp":
                    meta = pyogrio.read_info(str(path))
                    have = set(map(str, meta.get("fields", [])))
                    missing = [c for c in cols if c not in have]
                    if target:
                        g = pyogrio.read_dataframe(
                            str(path),
                            where=f"shrid2 LIKE '{TARGET_SHRID_PREFIX}%'",
                            read_geometry=False,
                        )
                        ncov = int(g["shrid2"].nunique())
                        nrows_cov = len(g)
                    else:
                        ncov = nrows_cov = None
                else:
                    head = pd.read_csv(path, nrows=0)
                    have = set(map(str, head.columns))
                    missing = [c for c in cols if c not in have]
                    usable = [c for c in cols if c in have] or ["shrid2"]
                    df = pd.read_csv(path, usecols=usable,
                                     dtype={"shrid2": str})
                    if target:
                        sel = df.loc[df["shrid2"].isin(target), "shrid2"]
                        ncov = int(sel.nunique())
                        nrows_cov = int(len(sel))
                    else:
                        ncov = nrows_cov = None
            except Exception as exc:
                rows.append([engine, f"`{Path(rel).name}`",
                             f"ERROR: {type(exc).__name__}", "—", "—"])
                entry["status"] = f"ERROR: {exc}"
                result["engines"][engine][rel] = entry
                continue

            status = "OK" if not missing else f"MISSING: {', '.join(missing)}"
            if ncov is not None and n_target:
                covs = f"{ncov:,} / {n_target:,} ({100.0 * ncov / n_target:.1f}%)"
                if nrows_cov and nrows_cov != ncov:
                    covs += f" — {nrows_cov:,} rows (long format)"
            else:
                covs = "—"
            rows.append([engine, f"`{Path(rel).name}`", status,
                         f"{len(cols) - len(missing)}/{len(cols)}", covs])
            entry["status"] = status
            entry["district_shrids"] = ncov
            entry["district_rows"] = nrows_cov
            result["engines"][engine][rel] = entry

    buf.write("\n")
    buf.write(md_table(rows, ["engine", "file", "status", "columns",
                              "district rows"]))
    return buf.getvalue(), result



def probe_agmarknet(timeout: int = 120) -> str:
    """Live check of the data.gov.in mandi resource (PART 3.2 says verify it)."""
    import json as _json
    import os
    import urllib.parse
    import urllib.request

    rid = os.environ.get(
        "AGMARKNET_RESOURCE_ID", "9ef84268-d588-465a-a308-a864a43d0070"
    )
    key = os.environ.get("DATA_GOV_IN_API_KEY")
    buf = io.StringIO()
    buf.write(f"\nResource ID checked: `{rid}`\n\n")
    if not key:
        buf.write("> `DATA_GOV_IN_API_KEY` not set — live probe skipped.\n")
        return buf.getvalue()

    def call(limit: str = "500", **extra):
        q = {"api-key": key, "format": "json", "limit": limit}
        q.update(extra)
        url = f"https://api.data.gov.in/resource/{rid}?" + urllib.parse.urlencode(q)
        # data.gov.in's gateway 502s on the default Python-urllib UA.
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.7.1"})
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            return _json.load(fh)

    j = None
    last_exc = None
    for attempt in range(3):
        try:
            j = call()
            break
        except Exception as exc:  # the endpoint is slow and intermittently drops
            last_exc = exc
    if j is None:
        buf.write(
            f"> Live probe FAILED after 3 attempts: "
            f"`{type(last_exc).__name__}: {last_exc}`\n>\n"
            "> This does not invalidate the two Agmarknet findings in section 0 — "
            "they were established from successful calls and the endpoint's "
            "flakiness is itself a reason not to put it on the critical path.\n"
        )
        return buf.getvalue()

    recs = j.get("records", [])
    dates = sorted({r.get("arrival_date") for r in recs if r.get("arrival_date")})
    states = sorted({r.get("state") for r in recs if r.get("state")})
    commodities = sorted({r.get("commodity") for r in recs if r.get("commodity")})
    rows = [
        ["endpoint reachable", "yes"],
        ["title", str(j.get("title", ""))[:70]],
        ["records in resource", f"{j.get('total')}"],
        ["distinct arrival_date values", f"{len(dates)} — {', '.join(dates[:5])}"],
        ["states reporting", f"{len(states)}"],
        ["distinct commodities", f"{len(commodities)}"],
        ["milk / dairy commodity present",
         "YES" if any("ilk" in c for c in commodities) else "NO"],
    ]
    buf.write(md_table(rows, ["check", "result"]))
    buf.write(
        "\nA single `arrival_date` confirms this is a live daily snapshot with no "
        "historical depth. See the two Agmarknet findings in section 0.\n"
    )
    return buf.getvalue()



def probe_shric(root: Path) -> str:
    """Load the SHRIC crosswalks, resolve the dairy bucket, and sanity-check it.

    The mapping is never taken on trust: the resolved bucket is measured against
    national and state baselines and broken out by subdistrict, so a wrong
    bucket shows up as a nonsense geography instead of a plausible number.
    """
    buf = io.StringIO()
    base = root / "shrug"
    paths = {
        "desc": base / "shrug-shric-desc-csv" / "shric_descriptions.csv",
        "nic08": base / "shrug-shric-nic08-3d-csv" / "shric_NIC08_3d_key.csv",
        "nic04": base / "shrug-shric-nic04-csv" / "shric_NIC04_key.csv",
        "nic87": base / "shrug-shric-nic87-csv" / "shric_NIC87_key.csv",
    }
    missing = [k for k, v in paths.items() if not v.exists()]
    if missing:
        buf.write(f"\n> SHRIC crosswalk not present ({', '.join(missing)}) — "
                  "section skipped.\n")
        return buf.getvalue()

    desc = pd.read_csv(paths["desc"])
    n08 = pd.read_csv(paths["nic08"])
    n04 = pd.read_csv(paths["nic04"])
    n87 = pd.read_csv(paths["nic87"])
    n08["d3"] = n08["NIC08_3d"].astype(int)

    buf.write(
        f"\nThe crosswalk that first recon reported as missing. "
        f"{len(desc)} labelled buckets; keys to NIC-2008 3-digit "
        f"({len(n08)} rows), NIC-2004 ({len(n04)}) and NIC-1987 ({len(n87)}).\n"
    )

    # --- coverage boundary: what the Economic Census simply does not see ---
    lowest = sorted(n08["d3"].unique())[:4]
    div01 = n08[n08["d3"] < 20]
    buf.write(
        f"\n**Coverage boundary.** Lowest NIC-2008 codes present: "
        f"`{'`, `'.join(str(x) for x in lowest)}` (forestry). Rows mapping to "
        f"NIC division 01 (crop and animal production): **{len(div01)}**. "
        "The Economic Census excludes agricultural production, so no bucket "
        "represents raising livestock.\n"
    )

    # --- resolve dairy by description, not by guessing a number ---
    hits = desc[desc["shric_desc"].str.contains("dairy", case=False, na=False)]
    buf.write("\n**Dairy resolution** (matched on description text):\n\n")
    rows = []
    for _, r in hits.iterrows():
        sc = int(r["shric"])
        rows.append([
            str(sc), r["shric_desc"],
            ", ".join(str(int(x)) for x in sorted(n08[n08.shric == sc]["d3"])),
            ", ".join(str(int(x)) for x in sorted(n04[n04.shric == sc]["NIC04"])),
            ", ".join(str(x) for x in sorted(n87[n87.shric == sc]["NIC87"].astype(str))),
        ])
    buf.write(md_table(rows, ["shric", "description", "NIC-2008 3d",
                              "NIC-2004", "NIC-1987"]))

    if len(hits) != 1:
        buf.write(f"\n> Expected exactly one dairy bucket, found {len(hits)}. "
                  "Do not wire a sector filter until this is resolved.\n")
        return buf.getvalue()
    dairy = int(hits.iloc[0]["shric"])

    # --- sanity check against real geography ---
    names_p = base / "shrug-shrid-keys-csv" / "shrid_loc_names.csv"
    ec_p = base / "shrug-ec13-csv" / "ec13_shrid.csv"
    if not (names_p.exists() and ec_p.exists()):
        return buf.getvalue()

    col = f"ec13_emp_shric_{dairy}"
    ec = pd.read_csv(ec_p, dtype={"shrid2": str})
    shcols = [c for c in ec.columns if c.startswith("ec13_emp_shric_")]
    nm = pd.read_csv(names_p, dtype=str)

    nat_tot = float(ec[shcols].sum().sum())
    nat_d = float(ec[col].sum())
    nat_share = nat_d / nat_tot if nat_tot else 0.0

    def stat(shrids):
        e = ec[ec["shrid2"].isin(shrids)]
        t = float(e[shcols].sum().sum())
        d = float(e[col].sum())
        sh = d / t if t else 0.0
        return d, t, sh, (sh / nat_share if nat_share else 0.0)

    state = nm.loc[nm["state_name"] == "maharashtra", "shrid2"]
    dist = nm.loc[nm["district_name"] == TARGET_DISTRICT_NAME, "shrid2"]
    rows = [["national", f"{nat_d:,.0f}", f"{nat_tot:,.0f}",
             f"{nat_share * 100:.4f}%", "1.00 (baseline)"]]
    for lab, ids in [("maharashtra", set(state)),
                     (TARGET_DISTRICT_NAME, set(dist))]:
        d, t, sh, lq = stat(ids)
        rows.append([lab, f"{d:,.0f}", f"{t:,.0f}", f"{sh * 100:.4f}%",
                     f"{lq:.2f}"])
    buf.write(f"\n**Sanity check — is SHRIC {dairy} concentrated where dairy "
              "actually is?**\n\n")
    buf.write(md_table(rows, ["geography", f"shric {dairy} emp", "total emp",
                              "share", "location quotient"]))

    e = ec[ec["shrid2"].isin(set(dist))].merge(
        nm[["shrid2", "subdistrict_name"]], on="shrid2", how="left")
    g = (e.groupby("subdistrict_name")[col].sum()
         .sort_values(ascending=False).head(8))
    buf.write(f"\nTop subdistricts in `{TARGET_DISTRICT_NAME}` by SHRIC "
              f"{dairy} employment:\n\n")
    buf.write(md_table([[k, f"{v:,.0f}"] for k, v in g.items()],
                       ["subdistrict", f"shric {dairy} emp"]))
    nz = int((e[col] > 0).sum())
    buf.write(
        f"\n{nz} of {len(e):,} places carry any — dairy processing is "
        "concentrated in a few towns, which is what a plant-based industry "
        "should look like. A location quotient near or below 1.0 is EXPECTED "
        "here and is not a failed check: the Economic Census counts milk "
        "PLANTS, and this district's dairy economy is mostly milk PRODUCTION, "
        "which the census does not observe at all. The check that matters is "
        "the geography — see the finding in section 0.\n"
    )
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/derived/RECON.md")
    ap.add_argument("--full-scan-mb", type=float, default=200.0)
    ap.add_argument("--sample-rows", type=int, default=20000)
    ap.add_argument("--no-network", action="store_true",
                    help="skip the live data.gov.in probe")
    args = ap.parse_args()

    root = Path(args.raw).resolve()
    if not root.exists():
        print(f"ERROR: {root} does not exist", file=sys.stderr)
        return 1

    full_scan_bytes = int(args.full_scan_mb * 1024 * 1024)

    csv_paths = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in {".csv", ".tsv"}
    )
    shp_paths = sorted(
        p for p in root.rglob("*.shp") if p.is_file()
    )
    other_paths = sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() not in {".csv", ".tsv", ".shp", ".shx", ".dbf",
                                     ".prj", ".cpg", ".sbn", ".sbx"}
    )

    print(f"[recon] root={root}")
    print(f"[recon] {len(csv_paths)} csv, {len(shp_paths)} shapefiles, "
          f"{len(other_paths)} other")

    csv_infos: list[dict] = []
    for i, p in enumerate(csv_paths, 1):
        print(f"[recon] csv {i}/{len(csv_paths)}: {p.name} "
              f"({human(p.stat().st_size)})", flush=True)
        csv_infos.append(profile_csv(p, full_scan_bytes, args.sample_rows))

    shp_infos: list[dict] = []
    for i, p in enumerate(shp_paths, 1):
        print(f"[recon] shp {i}/{len(shp_paths)}: {p.name}", flush=True)
        shp_infos.append(profile_shapefile(p))

    # ---------------- render ----------------
    out = io.StringIO()
    now = datetime.now(timezone.utc).astimezone()
    out.write("# RECON.md — What is actually in the data\n\n")
    out.write(
        "> Generated by `etl/00_recon.py` (Phase 0). This file is the source of\n"
        "> truth for column names. Every later module reads its column names from\n"
        "> here, not from IMPLEMENTATION_PLAN.md.\n\n"
    )
    out.write(f"- **Generated:** {now.isoformat(timespec='seconds')}\n")
    out.write(f"- **Raw root:** `{root}`\n")
    out.write(f"- **Files profiled:** {len(csv_paths)} CSV, {len(shp_paths)} shapefile, "
              f"{len(other_paths)} other\n")
    out.write(f"- **Full-parse threshold:** {args.full_scan_mb:.0f} MB "
              f"(larger files profiled on first {args.sample_rows:,} rows)\n")
    out.write(f"- **pandas:** {pd.__version__}"
              + (f" · **pyogrio:** {pyogrio.__version__}" if pyogrio else "")
              + "\n")

    # -------- executive findings --------
    out.write("\n---\n\n## 0. Findings that change the build\n\n")
    out.write(
        "Read this section before writing any engine. Each item is a place where\n"
        "the data differs from what IMPLEMENTATION_PLAN.md assumes. The supporting\n"
        "measurements are in sections 1-4.\n"
    )
    for kind, title, body in FINDINGS:
        out.write(f"\n### [{kind}] {title}\n\n{body}\n")

    # -------- column contract --------
    out.write("\n---\n\n## 1. Column contract (verified this run)\n")
    contract_md, contract_obj = verify_contract(root)
    out.write(contract_md)

    # -------- agmarknet live probe --------
    out.write("\n---\n\n## 2. Agmarknet / data.gov.in — live probe\n")
    if args.no_network:
        out.write("\n> Skipped (`--no-network`).\n")
    else:
        out.write(probe_agmarknet())

    # -------- shric crosswalk --------
    out.write("\n---\n\n## 3. SHRIC crosswalk — sector code resolution\n")
    out.write(probe_shric(root))

    # -------- inventory --------
    out.write("\n---\n\n## 4. Inventory\n\n")
    inv = []
    for info in csv_infos + shp_infos:
        p: Path = info["path"]
        rel = p.relative_to(root)
        module = rel.parts[1] if len(rel.parts) > 1 else rel.parts[0]
        if info.get("error"):
            inv.append([module, f"`{rel.name}`", "ERROR", "—", "—",
                        human(info["size"])])
            continue
        nr = info.get("n_rows")
        nrs = f"{nr:,}" if isinstance(nr, int) and nr >= 0 else "?"
        if not info.get("n_rows_exact", True):
            nrs += "*"
        inv.append([
            module, f"`{rel.name}`",
            "shapefile" if "crs" in info else "csv",
            nrs,
            str(info.get("n_cols", len(info.get("columns", [])))),
            human(info["size"]),
        ])
    out.write(md_table(inv, ["module", "file", "type", "rows", "cols", "size"]))
    out.write("\n`*` = row count from line count, not a full parse.\n")

    # -------- join spine --------
    out.write("\n---\n\n## 5. The join spine — which key appears where\n\n")
    out.write(
        "The plan says `shrid` is the spine. This section reports which files\n"
        "actually carry which identifier column, so joins can be planned against\n"
        "reality.\n\n"
    )
    key_index: dict[str, list[str]] = {}
    for info in csv_infos + shp_infos:
        if info.get("error"):
            continue
        rel = info["path"].relative_to(root)
        for col in info.get("columns", []):
            lc = str(col).strip().lower()
            if any(re.match(p, lc) for p in KEY_PATTERNS[:5]):
                key_index.setdefault(str(col), []).append(str(rel))
    rows = []
    for col in sorted(key_index, key=lambda c: -len(key_index[c])):
        files = key_index[col]
        shown = ", ".join(f"`{Path(f).name}`" for f in files[:6])
        if len(files) > 6:
            shown += f" … (+{len(files) - 6} more)"
        rows.append([f"`{col}`", str(len(files)), shown])
    out.write(md_table(rows, ["key column", "# files", "files"]))

    # -------- district probe --------
    out.write("\n---\n\n## 6. Target district — how it is actually spelled\n")
    out.write(probe_district(csv_infos, root))

    # -------- per-module detail --------
    out.write("\n---\n\n## 7. Per-file detail\n")
    by_module: dict[str, list[dict]] = {}
    for info in csv_infos + shp_infos:
        rel = info["path"].relative_to(root)
        module = rel.parts[1] if len(rel.parts) > 1 else rel.parts[0]
        by_module.setdefault(module, []).append(info)

    readme_by_module: dict[str, Path] = {}
    for p in other_paths:
        if p.name.lower() in {"readme.md", "readme.txt"}:
            rel = p.relative_to(root)
            module = rel.parts[1] if len(rel.parts) > 1 else rel.parts[0]
            readme_by_module[module] = p

    for module in sorted(by_module):
        out.write(f"\n## Module: `{module}`\n")
        rp = readme_by_module.get(module)
        if rp:
            try:
                txt = rp.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                txt = ""
            if txt:
                trunc = txt if len(txt) <= 4000 else txt[:4000] + "\n… (truncated)"
                out.write(
                    "\n<details><summary>Shipped README "
                    f"(`{rp.name}`) — upstream column documentation</summary>\n\n"
                    "```\n" + trunc + "\n```\n\n</details>\n"
                )
        for info in sorted(by_module[module], key=lambda i: i["path"].name):
            out.write(render_file_section(info, root))

    # -------- failures --------
    fails = [i for i in csv_infos + shp_infos if i.get("error")]
    out.write("\n---\n\n## 8. Files that failed to profile\n\n")
    out.write(
        md_table(
            [[f"`{i['path'].relative_to(root)}`", i["error"]] for i in fails],
            ["file", "error"],
        )
    )

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(out.getvalue(), encoding="utf-8")

    import json
    cpath = outp.parent / "column_contract.json"
    cpath.write_text(json.dumps(contract_obj, indent=2), encoding="utf-8")
    print(f"[recon] wrote {cpath}")
    print(f"[recon] wrote {outp} ({human(outp.stat().st_size)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
