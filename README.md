# Udyam Saarthi

**A viability check for rural enterprise loans.** The bank verifies *eligibility*.
Nothing verifies *viability*. This computes the second one from real
village-level data, for one district, and is able to say **no**.

SIH 2026 · PS 26091 · Team Protocol 6 · Ahmadnagar (Ahilyanagar), Maharashtra

**Status: all phases 0–7 built.** 69 tests pass, 7 skip for a stated external
reason. Every number in the output carries its source, year, geographic level
and confidence, and the confidence is genuinely low where the inputs are weak.

---

## The gap this fills

A borrower qualifies for a subsidised loan. The bank checks the income ceiling,
the caste certificate, the documents — and disburses. Nobody asks whether there
are already eleven dairies within 8 km, whether the village has an all-weather
road for daily milk collection, or whether anything is left for fodder before
the first income arrives.

So the asset is bought and by month two the borrower is at a moneylender for
working capital. **The gap is not credit access. It is the missing viability
check between "you are eligible" and "here is the money."**

## Architecture

```
L1  DATA LAKE      SHRUG v2.2 · Village Directory · NABARD PLP · scheme rules
L2  DATA ACCESS    PostGIS (geospatial)  +  MongoDB (documents)
L3  GEO-RESOLUTION village name → shrid2 → polygon → 8 km buffer
L4  ENGINES        Market · Finance · Affordability · Risk    ← deterministic
L5  DECISION       verdict · sector ranking · confidence      ← deterministic
──────────────────────────────────────────────────────────────────────────
L6  NARRATION      Gemini. Translates only. Computes nothing.
```

**The unplug guarantee is structural, not behavioural.** `advise()` accepts no
model client and `core/pipeline.py` imports no LLM SDK — both asserted in
`tests/test_unplug.py`. The LLM cannot change a number because it is not in the
call graph that produces them. `--no-llm` is the default everywhere.

| Store | Holds | Why |
|---|---|---|
| **PostgreSQL + PostGIS** | village polygons, catchment graph, spatial joins | the 8 km catchment is a real geometric operation and the Market Engine's core |
| **MongoDB** | run logs, provenance, scheme rules, sector templates | document-shaped, non-geospatial; lets `/provenance/{run_id}` reproduce any verdict |

## Quick start

```bash
git clone https://github.com/Sahil0282/UdyamSarthi.git
cd UdyamSarthi
cp .env.example .env         # fill in the three keys (see below)
docker compose up            # postgis + api, district bundle auto-restored
open http://localhost:8000/  # map + verdict + tappable provenance
```

**No 8.8 GB download and no ETL run are needed to demo.** The repository ships
`data/bundle/ahmadnagar.dump` (3.8 MB) — the entire Ahmadnagar district already
loaded: 1,597 village polygons, the pre-computed 8 km catchment graph, census,
Economic Census, Village Directory, SECC and night-lights tables. PostGIS
restores it automatically on first start.

Verified from a fresh clone with Docker volumes destroyed: the containerised
stack returns the *same* `run_id` and the same numbers as a local venv.

### Keys

Only `.env.example` is committed; `.env` is gitignored and must never be pushed.

| Variable | Needed for | Without it |
|---|---|---|
| `GEMINI_API_KEY` | narration, voice | falls back to the template renderer — **all numbers identical** |
| `MONGO_DB_URL` | run logs, `/provenance` | falls back to an in-process store, labelled as degraded |
| `DATA_GOV_IN_API_KEY` | Agmarknet probe in recon | recon skips the live probe |

The system runs without any of them. Nothing in the advisory path depends on a
network call.

## What is in this repository, and what is not

The raw SHRUG corpus is **8.8 GB across 117 CSVs and 5 shapefiles**, plus 2.2 GB
of source archives. That is not in git — it is redistributed under CC BY-NC-SA,
it changes rarely, and nobody needs it to run or review this project.

| | In the repo | Why |
|---|---|---|
| `data/bundle/ahmadnagar.dump` | ✅ 3.8 MB | the loaded district — makes `docker compose up` work with zero downloads |
| `data/derived/plp_index/` | ✅ 780 KB | pre-built PLP index so citations work without re-embedding |
| `data/raw/plp/ahilyanagar.pdf` | ✅ 7.2 MB | NABARD's district credit plan — a public document, and the source for every PLP citation |
| `data/derived/RECON.md` | ✅ 1.5 MB | the Phase 0 audit trail; the source of truth for column names |
| `data/rules/`, `data/sectors/` | ✅ | versioned scheme rules and unit-economics templates — these *are* the feature |
| `data/raw/shrug/` | ❌ 8.8 GB | download from [devdatalab.org/shrug](https://www.devdatalab.org/shrug) (v2.2, free registration) |
| `Dataset/` | ❌ 2.2 GB | the source `.zip` archives |
| `.env` | ❌ | live credentials |

**To rebuild everything from raw source**, download SHRUG v2.2 into
`data/raw/shrug/` and run the ETL chain under *Local development* below. The
committed bundle is simply the output of that chain, so the two paths converge.

<details><summary>Local development, and rebuilding from raw SHRUG</summary>

```bash
uv venv --python 3.11 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements.txt
cp .env.example .env                      # fill in the keys

python etl/00_recon.py                    # → data/derived/RECON.md
python etl/10_load_shrug.py               # district CSV subsets → Postgres
python etl/20_load_polygons.py            # polygons → PostGIS (4326 + 32643)
python etl/30_build_indexes.py            # GIST + pg_trgm + the `village` view
python etl/35_build_catchments.py         # materialise the 8 km neighbour graph
python etl/50_sync_mongo.py               # rules, templates, load manifest
python etl/60_plp_embed.py                # PLP index for cited ranking

python cli.py advise --village "nimgaon jali" --capital 100000 \
                     --sector dairy --summary
python -m pytest tests/ -q
python tests/verify_by_hand.py            # 27/27 figures traced to source
python tests/demo_scenarios.py            # both demo stories end to end
python tests/ui_check.py                  # drives the real UI in Chromium
```
</details>

---

## Phase history

Each phase surfaced something that changed the build. This is the short version;
`data/derived/RECON.md` §0 has the full reconnaissance record.

| Phase | Built | What it changed |
|---|---|---|
| **0 · Recon** | `etl/00_recon.py`, RECON.md, machine-checked column contract | Four plan assumptions turned out to be wrong — see below |
| **1 · Data** | PostGIS load, catchment graph, three validation queries | District area, population and household counts matched published figures |
| **2 · Core** | `facts.py` first, then M1–M5, CLI | Eligibility ≠ affordability reproduced with real numbers |
| **3 · Decision** | M6, `thresholds.py`, refusal + override | A weighted score alone could not refuse; hard gates were required |
| **4 · Narration** | template renderer, then Gemini, then the numeric validator | Live Gemini caught inventing ₹85,000 / 120% / ₹1,200,000 and discarded |
| **5 · API + UI** | FastAPI, React + MapLibre, tappable provenance | Verified in a real browser against the live map instance |
| **6 · Voice** | Marathi ASR → pipeline → TTS | Round-trip verified; kept strictly additive |
| **7 · Polish** | PLP RAG, offline bundle, one-command Docker | Cold start exposed three real bugs |

### What Phase 0 found, and why it mattered

1. **The Economic Census has no establishment count by sector.** All four
   vintages expose 90 `emp_shric_N` columns (employment) and zero `count_shric`.
   The plan's `competitors = Σ EC establishments` is not computable. Saturation
   is measured in sector *employment* instead.
2. **Dairy is SHRIC 7 = NIC-2008 105 = "Manufacture of dairy products"** —
   milk *plants*, not herds. NIC division 01 (crop and animal production) is
   absent from all 224 crosswalk rows because the census excludes agriculture.
   **So the sign flips**: SHRIC 7 in the catchment counts the borrower's
   **buyers**, not their competitors. `market_mapping.role` encodes this, and
   getting it backwards would invert the verdict.
3. **Agmarknet carries no milk and holds one day of data** — 170 records for
   all of India on a single `arrival_date`. Milk is procured by cooperatives at
   an administered rate and never reaches a mandi. No seasonality index is
   computable, so the risk engine omits that flag and says why.
4. **The join key is `shrid2`, not `shrid`**, and SECC has no consumption
   column — only income-bracket shares.

Two plan worries proved unfounded: the Village Directory *does* carry
`rd_all_wthr`, `mrkt`, `vet_hosp`, banking and land use across 284 columns, and
VIIRS gives a real 2012–2023 series.

---

## Data sourcing and confidence

Every Fact carries `source`, `year`, `geo_level` and `confidence`. Derived Facts
inherit the **coarsest** geo_level and **lowest** confidence of their inputs —
enforced in `core/facts.py`, not by convention. `Fact.__post_init__` refuses to
construct a non-village Fact without a note explaining the degradation.

### The geospatial layer — real, village-specific, high confidence

| Input | Source | Level |
|---|---|---|
| village polygons, 8 km catchment | SHRUG v2.2 open polygons | village |
| catchment population | Population Census 2011 PCA | village |
| sector employment | Economic Census 2013 | village |
| road / power / bank / market / vet | Village Directory 2011 | village |
| household income structure | SECC-MORD 2012 | village |
| growth signal | VIIRS night lights 2012–2023 | village |

Cross-checked against published figures: district area **17,062 km²** vs 17,048
published (0.1%); population **4,543,159** — exact; SECC households 1,228 vs
census 1,230 for the demo village (0.2%).

### Dairy unit economics — real, cited, but **national / low**

| Fact | Value | Source | Level / confidence |
|---|---|---|---|
| Milk price (buffalo) | ₹62.18/litre | Gokul Dairy, Kolhapur cooperative | **state / medium** |
| Yield | 10 L/animal/day (lactation) | NABARD Model Bankable Project | **national / low** |
| Opex | ₹3,483/animal/month | derived from the same NABARD model | **national / low** |
| Capex (per animal) | ₹65,400 | same NABARD model | **national / low** |
| Capex (1+1 unit) | ₹1,80,800 | NABARD PLP Ahilyanagar, Annexure 4 | district / high |

**Why the milk price is `state`, not `district`:** it is a *Kolhapur* union rate
used as a Maharashtra proxy. No Ahmadnagar-specific published rate was found.
The nearest actual union is Sangamner Taluka Sahakari Dudh Utpadak Sangh at
Ghulewadi. The Fact's note says all of this, and the note survives verbatim into
the JSON, the provenance panel and the UI.

**Why yield/opex/capex are `national/low`:** they come from NABARD's generic
model project for a **10-animal commercial unit**, not from Ahmadnagar and not
from a 1–2 animal household. Labour and vet costs are shared across ten animals
in the source model, so per-animal cost is probably *understated* for a
household where labour is the farmer's own unpaid time. The source model's own
table also uses 270 lactation + 150 dry = **420 days against a 365-day year**;
that discrepancy is carried forward and flagged rather than silently reconciled.

**This is why every dairy verdict reports `confidence: low`**, and why the
narration says so out loud in both languages rather than burying it in JSON:

> "Confidence in this assessment is LOW. The map, the population and the loan
> rules are specific to your village, but the cost and yield figures behind the
> cash flow are national benchmarks, not measured in Ahmadnagar."

### The other three sectors — weaker, and flagged as such

| Sector | Capex | Revenue / opex |
|---|---|---|
| Goat rearing | ₹1,24,863 — PLP Annexure 4 ✓ | **uncited benchmark** |
| Backyard poultry | ₹32,000 — PLP Annexure 4 ✓ | **uncited benchmark** |
| Kirana retail | ₹1,50,000 — **no source at all** | **uncited benchmark** |

Their revenue and opex are illustrative figures, not published benchmarks and
not locally surveyed. Each carries `confidence: low` and a note saying so.
**Kirana is the weakest template in the set** and its own YAML says that. They
exist so the refusal engine has a pool to rank; treat their absolute numbers as
placeholders, not advice.

### Scheme rules

`data/rules/schemes/*.yaml` approximate published NBCFDC terms as of 2024 and
carry `verified: false` — they have **not** been re-checked against the live
scheme documents. The versioned rules file is deliberately the feature: PART 10
forbids hardcoding the problem statement's parameters, which do not match the
corporations' published terms.

### PLP citations

Each sector declares its PLP section (`plp_sections`), transcribed from the
document's own table of contents, so citations are exact and auditable rather
than whatever cosine similarity returns. Semantic search over a local
sentence-transformers index is the fallback. Front matter is penalised — citing
*"every effort has been made"* as NABARD backing for goat rearing would be worse
than citing nothing.

---

## The five differentiators

1. **Refusal engine.** `murmi` (Shevgaon) → RECONSIDER with three ranked
   alternatives. A tool that validates every idea cannot reduce enterprise
   failure. **The weighted score alone was not enough**: at murmi it reads 0.60,
   which would have been PROCEED_WITH_CHANGES. Two hard gates — no all-weather
   road, no milk buyer within 8 km — override it. A weighted average will
   otherwise average away a fatal condition.
2. **Eligibility ≠ affordability.** Eligible ₹9,00,000 (EMI ₹13,303) against
   ₹15,978/month available → recommended ₹7,56,665, with the cash-flow table.
3. **Working-capital floor.** ₹20,898 reserved from the loan *before* capex.
4. **Real catchment analysis.** PostGIS buffer in EPSG:32643 over real polygons.
   An 8 km disc measures 199.8 km² against π·8² = 201.1.
5. **Provenance on every number.** 61 Facts per envelope, every one tappable in
   the UI, every one retrievable via `/provenance/{run_id}`.

## Voice

Marathi speech in, structured query out, Marathi speech back. **Model choice
deviates from the plan deliberately**: Gemini `gemini-3.6-flash` for ASR and
`gemini-2.5-flash-preview-tts` for TTS, not AI4Bharat IndicConformer /
Indic-Parler-TTS. Those need NVIDIA NeMo, an AI4Bharat fork and a multi-GB
PyTorch install on a machine the plan says must not require a GPU.
`core/voice.py` is the seam to swap them back in for on-device or offline use.

Voice is **never a required path**: every function returns `ok: False` with a
reason instead of raising, the parsed query always returns for confirmation
before it can drive a verdict, and `core/pipeline.py` does not import the voice
module at all.

## Offline

`tests/test_offline.py` blocks every non-loopback socket and runs the full
pipeline: advice, refusal, both-language narration and PLP retrieval all pass.
**Only the LLM needs the network**, and it falls back to the template renderer.

---

## Environment status

| Service | State | Effect |
|---|---|---|
| PostgreSQL + PostGIS | up | — |
| MongoDB Atlas | up (`readWriteAnyDatabase`) | run logs and provenance persist; `/provenance` serves `store: mongodb` |
| Gemini TTS | up | Marathi audio output works |
| Gemini text | key valid, **daily free-tier quota (20 req/model) exhausted** | narration falls back to templates; 7 live tests skip printing that exact reason |

The quota is the one live constraint worth planning around: **20 requests per
day per model** means the demo can narrate ~20 times before falling back. Set
`GEMINI_MODEL` to another model, or move off the free tier, before demo day.

---

## Validation — the honest accounting

### What is real

The **geospatial and financial-rules machinery is fully sourced and
village-specific**, and independently cross-checks against published figures to
within 0.2%. The catchment, the risk flags, the scheme arithmetic, the cap
collision, the EMI with slabbed interest and capitalised moratorium interest —
all real, all traceable. `tests/verify_by_hand.py` traces **27/27** headline
figures back to SQL, YAML or arithmetic, with nothing checked against itself.

Determinism holds across entry points: the same query yields `run_id
b93fd7ac95d79c15` from the CLI, the local API, and a cold-started container
built from a fresh copy with no raw data.

### What is labelled low-confidence, and why

Dairy's unit economics are a **national NABARD benchmark** and the milk price is
a **Kolhapur proxy**. That is a real limitation, not a data-completeness failure
to paper over. Asked "how confident are you in the dairy numbers", the honest
answer is: *the geospatial and financial-rules machinery is fully sourced and
village-specific; the underlying unit economics are a national benchmark, which
is why the system reports this verdict as low confidence rather than high.*

### Known limitations

1. **Economic Census village data is 2013.** Relative density and percentile
   rank stay meaningful; absolute counts are dated. Cross-checked against VIIRS.
2. **No per-sector establishment count exists**, so saturation is measured in
   employment. For dairy, farmer-level competition is **not measurable at all**
   and the envelope says so rather than substituting a proxy.
3. **Three of four sectors have uncited revenue and opex**, and kirana's capex
   has no source. Worse than dairy, which at least has NABARD behind it.
4. **Scheme YAMLs are `verified: false`** — approximate NBCFDC terms, not
   re-checked against the live published documents.
5. **The survival stress test is near-flat between borrowing levels** for
   healthy villages. Two genuine modelling errors were fixed (the run now starts
   from the working-capital reserve, and animal mortality uses NABARD's own 5%
   insurance premium). It still does not discriminate much where margin exceeds
   EMI. Shock parameters were **not** tuned to manufacture a curve; a better
   answer is a grounded drought/fodder-price model, which the PLP itself names.
6. **The numeric validator's percentage handling is imperfect.** It expands
   probability-like Facts into percentage forms, which is necessary for
   legitimate phrasings but widens the allowed set. A fabricated percentage that
   coincides with a real ratio can pass.
7. **Village-name disambiguation is genuinely hard.** `sangvi` returns two
   villages scoring 1.00 in different subdistricts. Handled by explicit user
   confirmation, never silent guessing.
8. **Voice depends on a hosted API.** No on-device fallback yet.
9. **One district only.** Full-India is a scaling exercise, not a prototype
   requirement.
10. **The system assesses the place and the plan, not the person.** Skill,
    health and family support are outside the boundary and we say so.

### The single highest-value next step

Unchanged since Phase 4: **one phone call to the Sangamner Taluka Sahakari Dudh
Utpadak Sangh** (Ghulewadi) asking what a two-buffalo household unit actually
costs to run per month and what yield is typical would move the dairy figures
from `national/low` to `district/high` — and with them the confidence of every
dairy verdict the system issues. That is a weekend's work with more impact than
any code change in this repository.

---

## Repository

```
core/       facts · geo · market · finance · affordability · risk
            decision · thresholds · narrate · voice · plp · pipeline · db
etl/        00_recon · 10_load_shrug · 20_load_polygons · 30_build_indexes
            35_build_catchments · 40_validate_phase1 · 50_sync_mongo · 60_plp_embed
api/main.py FastAPI — /resolve /advise /sectors /provenance/{run_id} /voice/*
web/        React + MapLibre, single file, no build step
tests/      unplug · determinism · provenance · refusal · milk-price provenance
            confidence-is-spoken · voice · offline · plp
            + verify_by_hand · demo_scenarios · ui_check
data/
  rules/schemes/*.yaml   versioned scheme rules   (committed)
  sectors/*.yaml         unit-economics templates (committed)
  bundle/*.dump          3.8 MB offline district   (committed)
  derived/               RECON.md, column contract, PLP index
  raw/                   human-placed downloads   (gitignored)
```

**Explicitly not used:** no GPU, no model training, no fine-tuning.
