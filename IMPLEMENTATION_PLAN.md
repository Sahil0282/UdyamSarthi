# UDYAM SAARTHI — Implementation Plan
### SIH 2026 · PS 26091 · Team Protocol 6 (Team ID 0069)
**Target: working prototype. Read this whole file before writing any code.**

---

# PART 0 — HOW TO USE THIS DOCUMENT

You are building a working prototype, not a demo mock. Follow the phase order in PART 8 exactly — it is ordered by risk, not by visibility. **Phase 0 (data reconnaissance) is mandatory and must not be skipped**; every later module depends on knowing the real column names in the SHRUG data, which nobody can know without looking.

Three rules that override anything else in this document:

1. **The LLM never computes.** It never produces a number, never makes a decision, never ranks anything. It receives a finished JSON object and turns it into a sentence in Marathi or Hindi. If you find yourself asking an LLM to "analyse" or "estimate" or "decide", you have broken the architecture.
2. **Every number carries provenance.** No bare floats anywhere in the output path. See the `Fact` type in PART 5.
3. **If data is missing, degrade and say so.** Never silently substitute district data for village data. Drop a level, lower the confidence, and label it.

---

# PART 1 — THE PROBLEM

### 1.1 What actually goes wrong

A person in a rural village qualifies for a subsidised loan under one of the Ministry of Social Justice & Empowerment's lending corporations (NBCFDC, NSFDC, NSKFDC, NHFDC). The bank verifies **eligibility** — income ceiling, caste certificate, documents — and sanctions the loan.

Nobody verifies **viability**. Nobody asks:

- Are there already 11 dairies within 8 km of this village?
- Does the village have an all-weather road? (Dairy needs *daily* collection — no road, no buyer.)
- Milk procurement price falls ~18% in flush season. The EMI does not fall. Can they survive those months?
- After buying the animals, is there money left for fodder before the first income arrives?

So the loan is disbursed, the asset is bought, and by month two the borrower is at a moneylender for working capital. Published field research (Guérin et al., rural South India) finds **under 10% of rural microloans are actually invested in the enterprise** — the rest go to daily expenses, health, past debt, ceremonies.

**The gap is not credit access. The gap is the missing viability check between "you are eligible" and "here is the money."**

### 1.2 Why software can close it

The advice needed is *hyper-local* — not "dairy is viable in Maharashtra" but "dairy in **your** village, with **your** ₹1 lakh, given **these** competitors and **no** road."

The universal assumption is that village-level economic data for India does not exist. **That assumption is wrong.** It exists, it is free, and it is clean. See PART 3.

### 1.3 What we are NOT building

- Not a chatbot with a government-scheme knowledge base.
- Not a loan eligibility calculator (those exist and are not the problem).
- Not a credit-scoring or approval system. We do not assess the *person* — skill, health, family support are outside our boundary and we say so.
- Not a replacement for a bank officer. We produce a sourced feasibility document the applicant brings **to** the officer.

---

# PART 2 — THE SOLUTION

### 2.1 One-paragraph description

A voice-first advisory system. A rural entrepreneur speaks in Marathi: *"I have one lakh rupees, I want to start a dairy in my village."* The system resolves the village to a census identifier, computes market saturation from real Economic Census counts over a real 8 km geographic catchment, routes to the correct loan scheme, models the business's actual cash flow, compares it to the real EMI, stress-tests it, produces a verdict — **which may be "don't do this, here are three better options"** — and speaks the whole thing back in Marathi with every number's source attached.

### 2.2 The architectural rule that defines the project

```
L1  DATA LAKE          SHRUG · Village Directory · NABARD PLP · Agmarknet · scheme rules
L2  DATA ACCESS        PostGIS + vector store
L3  GEO-RESOLUTION     village name → shrid → polygon → buffer
L4  ENGINES            Market · Finance · Affordability · Risk        ← deterministic
L5  DECISION ENGINE    verdict · sector ranking · confidence          ← deterministic
────────────────────────────────────────────────────────────────────────────────
L6  NARRATION          LLM. Translate only. Computes nothing.         ← the ONLY LLM
```

**L1–L5 are pure Python + SQL. L6 is the only place an LLM appears.**

**The unplug test — build this as an actual CLI flag and an actual test:**
`--no-llm` must produce the same verdict, the same numbers, the same ranking, rendered as plain templated English. If disabling the LLM changes any number, the architecture is broken and must be fixed before proceeding.

### 2.3 The five differentiators (build these, in this order of importance)

1. **Refusal Engine** — the system must be able to say *no* and rank alternatives. A tool that validates every idea cannot reduce enterprise failure, which is the PS's stated goal.
2. **Eligibility ≠ Affordability** — eligible ₹9,00,000, advised ₹4,50,000, with the cash-flow table shown.
3. **Working-capital floor** — reserve N months of opex before approving any capex.
4. **Real catchment analysis** — PostGIS buffer over real village polygons, not an LLM estimate.
5. **Provenance on every number** — tap any figure, see source + year + geo level.

---

# PART 3 — PREREQUISITES (what the human must provide)

**Nothing below can be obtained by the coding agent. The human must do these before Phase 1.**

### 3.1 SHRUG dataset — the backbone (REQUIRED, free)

- **Where:** https://www.devdatalab.org/shrug → "Download SHRUG"
- **Cost:** free. Requires a short registration form (name, email, affiliation). Instant access.
- **Version:** SHRUG **v2.x or newer** (do not use v1.5 "Samosa" — the shrid IDs do not match v2 "Pakora").
- **Download these modules:**

| Module | Why we need it |
|---|---|
| **Core keys** (`shrid` identifiers) | the spine that joins everything |
| **Economic Census 1990–2013** | establishment + employment counts by sector, at village level → **competitor counts** |
| **Population Census 1991–2011 (PCA)** | population, literacy, workforce → **catchment population** |
| **SECC 2012** | avg household consumption → **purchasing power / household drawings** |
| **Night lights** | economic growth proxy → cross-check for stale EC data |
| **Village Directory / amenities** | road type, power, distance to town, bank presence → **risk engine** |
| **Open polygons (shapefile or GeoPackage)** | actual village geometries → **catchment buffer** |

- **Note:** the SHRUG amenities subset is small. The **full** Village Directory tables come from the Census of India separately; SHRUG keys let you join them. Start with SHRUG's subset; extend only if needed.
- **Place downloads in:** `data/raw/shrug/`

### 3.2 data.gov.in API key — Agmarknet mandi prices (REQUIRED, free)

- **Where:** https://www.data.gov.in → Sign Up → confirm email → **My Account → API Key**
- **Cost:** free, instant.
- **Dataset:** "Current Daily Price of Various Commodities from Various Markets (Mandi)" — sourced from the AGMARKNET portal, gives wholesale **min / max / modal** price daily.
- **Resource ID (verify before use — IDs occasionally change):** `9ef84268-d588-465a-a308-a864a43d0070`
- **Endpoint shape:** `https://api.data.gov.in/resource/{resource_id}?api-key={KEY}&format=json&limit=...&filters[state]=Maharashtra`
- **Put in `.env` as:** `DATA_GOV_IN_API_KEY=...`
- **Important limitation:** this endpoint serves *current/recent* prices, not deep history. For the **seasonality index** we need 3–5 years. Two options — implement (a), keep (b) as fallback:
  - (a) Start a daily cron now that appends to `data/derived/mandi_history.parquet`, and **seed** it with any historical CSV export available from the same catalogue page.
  - (b) If history is unavailable for the demo, compute the seasonal index from whatever window exists and **label the confidence as LOW with the actual window length shown**. Do not fabricate a seasonal curve.

### 3.3 LLM API key — narration only (REQUIRED)

- **Anthropic Claude API:** https://console.anthropic.com → API Keys.
- **Put in `.env` as:** `ANTHROPIC_API_KEY=...`
- **Model:** any current Claude model; narration is a light task.
- **This key is only used in L6.** If it is absent, the system must still run in `--no-llm` mode. Make that the default in tests.

### 3.4 NABARD Potential Linked Credit Plan (PLP) — RECOMMENDED

- **Where:** https://www.nabard.org → District-wise PLP PDFs.
- **Get:** the PLP for **one district only** for the prototype.
- **Why:** it is the sponsor ecosystem's own official answer to "is dairy viable in this district", written by NABARD's District Development Manager. Used for RAG-cited sector ranking.
- **Place in:** `data/raw/plp/{district}.pdf`
- **If unavailable:** the sector ranker must degrade gracefully to market+risk scoring only, and the UI must not claim PLP backing.

### 3.5 Scheme rules — MANUAL TRANSCRIPTION REQUIRED

- **Source:** the published loan-scheme pages of **NBCFDC** (https://nbcfdc.gov.in), and optionally NSFDC / NSKFDC / NHFDC.
- **Action:** a human reads the current published terms and transcribes them into `data/rules/schemes/*.yaml` (schema in PART 5.4).
- **Critical finding to preserve:** the parameters in the problem statement text **do not match** the currently published scheme documents, and they differ across the four corporations, with State Channelizing Agencies adding state-level variation. **Do not hardcode the PS numbers.** The versioned rules file *is* the feature.
- Each YAML entry **must** carry `source_url` and `effective_from`.

### 3.6 Local environment

| Thing | Notes |
|---|---|
| **PostgreSQL 15+ with PostGIS 3.3+** | easiest via Docker: `postgis/postgis:15-3.4` |
| **Python 3.11+** | |
| **Node 18+** | frontend only |
| **Docker + docker-compose** | recommended |
| **~10–20 GB free disk** | SHRUG full download is large; a single-state subset is much smaller |
| **HuggingFace account** | only if you enable real ASR/TTS. Models used are open. |

### 3.7 Target district — pick ONE

**Recommendation: Ahmednagar / Ahilyanagar district, Maharashtra** (the team is based in Sangamner, so findings can be verified in person, and Marathi is the demo language).

Load only this district in Phase 1. Full-India load is a scaling exercise, not a prototype requirement.

### 3.8 Optional — voice stack

Voice can be stubbed for the prototype (text input + templated text output) and still demo well. If you enable it:

- **ASR (Marathi):** `ai4bharat/indicconformer_stt_mr_hybrid_ctc_rnnt_large` (NeMo-based; needs AI4Bharat's NeMo fork). Fallback: any Whisper variant.
- **Translation:** `ai4bharat/indictrans2-en-indic-dist-200M` (distilled, small) or the 1B variant.
- **TTS:** `ai4bharat/indic-parler-tts`.
- **Do this last.** It is the highest effort-to-credibility-ratio item and is not on the critical path.

---

# PART 4 — TECH STACK & REPO LAYOUT

```
udyam-saarthi/
├── docker-compose.yml          # postgis + api + web
├── .env.example
├── data/
│   ├── raw/                    # human-placed downloads (gitignored)
│   │   ├── shrug/
│   │   └── plp/
│   ├── rules/schemes/*.yaml    # versioned scheme rules (COMMITTED)
│   ├── sectors/*.yaml          # unit-economics templates (COMMITTED)
│   └── derived/                # generated artefacts
├── etl/
│   ├── 00_recon.py             # Phase 0 — prints real schemas
│   ├── 10_load_shrug.py
│   ├── 20_load_polygons.py
│   ├── 30_build_indexes.py
│   ├── 40_agmarknet_sync.py
│   └── 50_plp_embed.py
├── core/
│   ├── facts.py                # Fact type + provenance (build FIRST)
│   ├── geo.py                  # M1
│   ├── market.py               # M2
│   ├── finance.py              # M3
│   ├── affordability.py        # M4
│   ├── risk.py                 # M5
│   ├── decision.py             # M6
│   └── narrate.py              # M7 — the ONLY module importing an LLM SDK
├── api/main.py                 # FastAPI
├── web/                        # React + MapLibre
├── tests/
│   ├── test_unplug.py          # THE test
│   ├── test_determinism.py
│   └── test_provenance.py
└── cli.py                      # `python cli.py advise --village ... --capital ... --sector ... [--no-llm]`
```

**Stack:** PostgreSQL + PostGIS · Python (pandas, numpy, scipy, geopandas, shapely) · FastAPI · FAISS + sentence-transformers (PLP RAG) · React + MapLibre GL · Docker.

**Explicitly not used:** no GPU, no model training, no fine-tuning. State this in the README.

---

# PART 5 — DATA CONTRACTS (build these before any engine)

### 5.1 The `Fact` type — nothing leaves an engine without it

```python
@dataclass(frozen=True)
class Fact:
    value: float | int | str
    unit: str | None            # "persons", "INR", "count", "percentile", "km"
    source: str                 # "Economic Census 2013 (via SHRUG v2)"
    year: int | None
    geo_level: Literal["village", "subdistrict", "district", "state", "national"]
    confidence: Literal["high", "medium", "low"]
    note: str | None = None     # e.g. "district-level estimate; village data unavailable"
```

Rules:
- Engines return `dict[str, Fact]`, never bare numbers.
- Any derived Fact inherits the **lowest** confidence and the **coarsest** geo_level of its inputs.
- `geo_level != "village"` for a village-level question ⇒ `note` **must** be populated and shown in the UI.

### 5.2 The result envelope (L5 → L6 contract — freeze this early)

```jsonc
{
  "query": { "village": "...", "shrid": "...", "capital_inr": 100000, "sector": "dairy" },
  "resolution": { "candidates": [...], "chosen": "...", "confirmed_by_user": true },
  "market":        { "catchment_population": Fact, "competitors": Fact,
                     "customers_per_unit": Fact, "saturation_percentile": Fact,
                     "growth_signal": Fact },
  "finance":       { "scheme_id": "...", "eligible_loan": Fact, "cap_applied": Fact|null,
                     "interest_rate": Fact, "tenure_years": Fact,
                     "moratorium_months": Fact, "emi": Fact },
  "affordability": { "monthly_revenue": Fact, "monthly_opex": Fact,
                     "household_drawings": Fact, "net_available_for_emi": Fact,
                     "working_capital_floor": Fact, "recommended_loan": Fact },
  "risk":          { "flags": [ { "code": "...", "severity": "...", "evidence": Fact } ],
                     "seasonality_index": [12 × Fact],
                     "survival_probability": Fact },
  "decision":      { "verdict": "PROCEED" | "PROCEED_WITH_CHANGES" | "RECONSIDER",
                     "reasons": ["..."],
                     "alternatives": [ { "sector": "...", "score": Fact, "why": "..." } ],
                     "confidence": "high" | "medium" | "low" },
  "provenance":    [ ...every Fact used, flattened, for the "show me your sources" panel ]
}
```

**L6 receives exactly this object and returns only prose. Nothing else.**

### 5.3 Sector template (`data/sectors/dairy.yaml`)

```yaml
sector_id: dairy_buffalo
display_name: { en: "Dairy (buffalo)", mr: "दुग्ध व्यवसाय (म्हैस)" }
nic_codes: ["01410", "01440"]        # for matching Economic Census sector counts
agmarknet_commodity: "Milk"
unit: "animal"
capex_per_unit_inr: 80000
other_capex: { shed: 60000, chaff_cutter: 25000, milk_cans: 8000 }
monthly:
  yield_litres_per_unit_per_day: 6.0
  price_source: agmarknet          # else fixed_inr
  opex_per_unit_inr:
    green_fodder: 1800
    dry_fodder: 900
    concentrate: 2400
    vet: 300
    labour: 0
    transport: 400
working_capital_months: 3          # feeds the working-capital floor
seasonality: { source: agmarknet, commodity: "Milk" }
risk_flags:
  requires_daily_collection: true
  requires_cold_chain_km: 15
  requires_all_weather_road: true
assumptions_source: "NABARD model project profile — dairy"
```

Build **at least 4 sectors**: dairy, kirana/retail shop, goat rearing, poultry. The alternatives ranker needs a pool to rank.

### 5.4 Scheme rules (`data/rules/schemes/nbcfdc_term_loan.yaml`)

```yaml
scheme_id: NBCFDC_TERM_LOAN
corporation: NBCFDC
target_group: OBC
effective_from: 2024-04-01
source_url: https://nbcfdc.gov.in/...
income_ceiling_inr: 300000
loan_to_cost_ratio: 0.90
per_beneficiary_cap_inr: 1500000
interest_slabs:
  - { upto_inr: 500000,  annual_rate: 0.06 }
  - { upto_inr: 1500000, annual_rate: 0.08 }
repayment_years: 8
moratorium_months: 6
installment_frequency: quarterly
state_overrides:
  MH: {}
```

---

# PART 6 — MODULE SPECIFICATIONS

### M0 · ETL

**`etl/00_recon.py` — WRITE AND RUN THIS FIRST.** Do not assume column names. It must print, for every SHRUG file downloaded: filename, shape, dtypes, first 5 rows, null counts, and the candidate join key. Save output to `data/derived/RECON.md`. **Every later module reads column names from what this discovered, not from this plan.**

Then: load the target district into PostGIS (`shrid_geom` with GIST index, `pca_village`, `ec_village`, `secc_village`, `nightlights`, `amenities`), and build a fuzzy name index (`pg_trgm` on village name + subdistrict + district).

### M1 · Geo-Resolution (`core/geo.py`)

`resolve(name, district_hint=None) → list[Candidate]`

Fuzzy-match on village name; **India has heavy duplicate village names across subdistricts, so if >1 candidate scores above threshold, RETURN ALL and require explicit user confirmation. Never auto-pick.** Then `geometry(shrid)` and `buffer(shrid, km)` returning a projected buffer (reproject to a metric CRS before buffering — do **not** buffer in EPSG:4326 degrees).

### M2 · Market Engine (`core/market.py`) — the flagship

```
1. polygon    = geometry(shrid)
2. ring       = buffer(polygon, 8km)                    # metric CRS
3. neighbours = spatial join: all shrid polygons intersecting ring
4. catchment_population = Σ population, distance-decay weighted  w = 1/(1+d²)
5. competitors          = Σ EC establishments in `neighbours` filtered to sector NIC codes
6. customers_per_unit   = catchment_population / max(competitors, 1)
7. saturation_percentile = rank of (6) against all villages in the district
8. growth_signal        = night-lights trend slope for this shrid
```

Output shape: *"Within 8 km there are ~14,200 people and 11 dairy units — about 1,290 potential customers per unit. District median is 2,400. More crowded than 82% of villages in this district."*

**Handle honestly:** Economic Census village data is **2013**. Use it for **relative density and percentile rank**, never as a current absolute count. Every EC-derived Fact gets `year=2013` and a note. Cross-check direction with night-lights.

### M3 · Finance Engine (`core/finance.py`)

Load scheme YAMLs → filter by target group / income / sector → compute:

```
project_cost   = capital / (1 - loan_to_cost_ratio)
loan_requested = project_cost × loan_to_cost_ratio
loan_eligible  = min(loan_requested, per_beneficiary_cap)      # ← the cap collision
```

**The cap-collision case must be detected and explained, not silently truncated.** ₹5,00,000 margin → a naive ₹50L project and ₹45L loan, but the real per-beneficiary cap is ₹10–15L. Output: *"Your ₹5,00,000 would in theory support a ₹50 lakh project, but this scheme caps individual loans at ₹15 lakh. Your workable project size is ₹16.7 lakh, using ₹1.67 lakh of your capital. The remaining ₹3.3 lakh is better held as working capital."*

EMI must respect **slabbed interest**, **moratorium** (interest-only or accrued — state which), and **instalment frequency** (often quarterly, not monthly — normalise to monthly for comparison and say so).

### M4 · Affordability Model (`core/affordability.py`) — the module that makes it an advisor

```
monthly_revenue  = units × yield × 30 × price        # price ← Agmarknet, seasonally adjusted
monthly_opex     = Σ sector opex × units
household_drawings = f(SECC village avg consumption)  # they have to eat
net_available_for_emi = revenue − opex − drawings

recommended_loan = largest loan where EMI ≤ net_available_for_emi × safety_factor   # 0.7
```

Plus the **working-capital floor**: `working_capital_floor = monthly_opex × sector.working_capital_months`. This is **reserved from the loan before capex is approved** and shown as its own line.

Output: *"Eligible ₹9,00,000. This business generates about ₹14,000/month after costs and household needs. EMI on ₹9,00,000 is ₹18,400. We recommend ₹4,50,000."*

### M5 · Risk Engine (`core/risk.py`)

Every flag is **computed**, never generated:

| Flag | Computed from |
|---|---|
| no all-weather road | Village Directory road-type |
| poor/no power | Village Directory power supply |
| far from market | Village Directory distance-to-town |
| no bank in village | Village Directory banking facility |
| seasonal price collapse | Agmarknet monthly seasonal index |
| market saturation | M2 saturation percentile |
| single-buyer dependency | sector flag + count of nearby procurement points |
| stagnant local economy | night-lights trend ≤ 0 |

Plus **Monte Carlo** (1,000 runs) over the cash-flow model with price drop (from real Agmarknet variance), yield drop, one-month animal illness, delayed buyer payment → **survival probability**, not a point estimate. Report at both the eligible and the recommended loan level — the contrast is the point.

### M6 · Decision Engine (`core/decision.py`)

Deterministic, explainable, **no ML**. Weighted score over market fit / affordability / risk. Verdict thresholds must be **constants in one file** so they are auditable.

- `PROCEED` · `PROCEED_WITH_CHANGES` · `RECONSIDER`
- **Alternatives ranking** = score all sector templates for *this* village and *this* capital, return top 3. If PLP RAG is available, attach the citation.
- **User override is respected:** if the user says "I still want dairy", comply and switch to risk-mitigation mode. Never block.
- Confidence = aggregate of input Fact confidences.

### M7 · Narration (`core/narrate.py`) — the only LLM

- Input: the result envelope. Output: prose only.
- **System prompt must forbid introducing any number not present in the input.**
- **Post-generation validator:** regex every numeric token out of the LLM output; assert each appears in the input envelope. If not → discard and fall back to the template renderer. Log the violation.
- **Template renderer must exist and must be the `--no-llm` path.** Build it *before* the LLM path.
- Then translate en→mr with IndicTrans2 (or ask the LLM for Marathi directly; the numeric validator still applies).

### M8 · API + M9 · Frontend

FastAPI: `POST /resolve` · `POST /advise` · `GET /sectors` · `GET /provenance/{run_id}`. Every response includes `run_id` for reproducibility.

React + MapLibre: voice/text input → **map with the village polygon, the 8 km ring, and competitor points** → verdict card → financial roadmap table → **every number tappable, showing source + year + geo level** ("Show me your sources" panel) → alternatives → override button.

---

# PART 7 — TESTS THAT DEFINE CORRECTNESS

```python
def test_unplug():
    """Disabling the LLM must not change a single number."""
    a = advise(**Q, use_llm=True)
    b = advise(**Q, use_llm=False)
    assert a["decision"] == b["decision"]
    assert facts_of(a) == facts_of(b)

def test_determinism():
    """Same input, same output, twice. Non-negotiable for a govt tool."""
    assert advise(**Q) == advise(**Q)

def test_no_bare_numbers():
    """Every numeric leaf in the envelope is a Fact with a source."""

def test_llm_invents_nothing():
    """Every number in the narration exists in the input envelope."""

def test_degradation_is_labelled():
    """A village with missing data returns geo_level != 'village' AND a note."""

def test_refusal_possible():
    """A saturated village + low capital must be able to produce RECONSIDER."""
```

`test_unplug` and `test_refusal_possible` are the two that prove the pitch. Write them in Phase 2, before the LLM exists.

---

# PART 8 — BUILD PHASES (do not reorder)

| Phase | Deliverable | Done when |
|---|---|---|
| **0 · Recon** | `etl/00_recon.py`, `RECON.md` | Real column names known and written down. **Half a day. Skipping this will cost days later.** |
| **1 · Data** | PostGIS loaded, one district, GIST + trigram indexes | These three SQL queries return sane numbers: establishments in sector X in village Y · catchment population within 8 km of Y · avg household consumption in Y |
| **2 · Deterministic core** | `facts.py`, M1–M6, scheme + sector YAMLs, CLI | `python cli.py advise --village X --capital 100000 --sector dairy --no-llm` prints a full envelope. **No LLM, no UI, numbers verified by hand.** |
| **3 · Decision + refusal** | verdict, alternatives ranking, override | A deliberately bad input produces `RECONSIDER` + 3 ranked alternatives |
| **4 · Narration** | template renderer, then LLM, then validator | `test_unplug` and `test_llm_invents_nothing` pass |
| **5 · API + UI** | FastAPI + React + MapLibre + provenance panel | Map renders polygon + ring + competitors; every number is tappable |
| **6 · Voice** | ASR → pipeline → TTS | Marathi in, Marathi out |
| **7 · Polish** | PLP RAG, offline district bundle, Docker one-command up | `docker-compose up` works on a clean machine |

**If time runs out, ship Phases 0–4 plus a plain UI.** That still beats a polished prompt wrapper, because the numbers are real.

---

# PART 9 — DEMO SCENARIO (build the seed data for this)

1. Voice/text in Marathi: *"I have one lakh rupees, I want to start a dairy in [village]."*
2. **Map**: village polygon, 8 km ring, existing dairy establishments as points.
3. **Saturation verdict**: 82nd percentile — crowded. Number is tappable → *Economic Census 2013, village level, via SHRUG*.
4. **The refusal**: recommends against dairy at this scale; ranks three alternatives, citing the district PLP.
5. **Override**: *"I still want dairy"* → complies, switches to risk-mitigation mode.
6. **Financial roadmap**: eligible ₹9,00,000 → recommended ₹4,50,000, cash-flow table shown.
7. **Working-capital warning**: feed money for months 1–3.
8. **Stress test**: survival probability at both borrowing levels.
9. **The unplug moment**: *"Everything you just saw was computed."* Run `--no-llm`, show the raw JSON.

Pick the demo village during Phase 1 by querying for one that is genuinely saturated for dairy — **do not fabricate the scenario, find a real one.**

---

# PART 10 — GUARDRAILS

**Do not:**
- ask an LLM to estimate, rank, decide, or produce any number
- hardcode the problem statement's scheme parameters — they don't match the published documents
- buffer in EPSG:4326 degrees
- silently substitute district data for missing village data
- present 2013 Economic Census counts as current absolute counts
- auto-resolve an ambiguous village name
- block a user who overrides the recommendation
- claim the system assesses the person's skill, health or family support — it assesses the **place** and the **plan**

**Do:**
- print the data vintage next to every derived figure
- make `--no-llm` the default in every test
- commit the scheme and sector YAMLs; gitignore `data/raw/`
- keep verdict thresholds as named constants in one auditable file
- write `RECON.md` before writing an engine

---

# PART 11 — KNOWN LIMITATIONS (state these in the README and the pitch)

1. Economic Census village data is from **2013**. Relative density stays meaningful; absolute counts are dated. Mitigated by percentile ranking + night-lights cross-check.
2. Unit-economics templates come from published sector benchmarks and NABARD model project profiles, **not primary survey data**.
3. Village-name disambiguation in India is genuinely hard. Handled by explicit user confirmation, never silent guessing.
4. Agmarknet history depth may be shallow at first; the seasonality index carries its actual window length and a confidence level.
5. The system assesses the **place and the plan**, not the person. That boundary is deliberate and we do not cross it.

Stating these unprompted is worth more than hiding them and being caught.
