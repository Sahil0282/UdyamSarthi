# Milk Procurement Price — Source Document
### For `data/sectors/dairy.yaml` — resolves the Phase 1 blocker on M4 (Affordability Model)

Hand-transcribed, same discipline as the scheme YAMLs. No API carries this figure —
Agmarknet is a mandi/auction feed and milk is never mandi-traded (Phase 0 finding).
This is a real published cooperative procurement rate, cited to its source.

---

## Primary source (use this)

**Gokul Dairy — Kolhapur Zilla Sahakari Dudh Utpadak Sangh Ltd.**
Official procurement page: https://www.gokulmilk.coop/procurement
Retrieved: this session (page reflects "During the year 2025-2026" average, so live/current)
Official current rate card (PDF, effective 11-08-2026): https://www.gokulmilk.coop/uploads/milk_prices/milk_rates_english_wef_11_08_2026.pdf

| Metric | Buffalo milk | Cow milk |
|---|---|---|
| **Average purchase price** (incl. rate difference + extra rate) | **₹62.18 / litre** | **₹37.73 / litre** |
| Fat % | 7.0% | 4.0% |
| SNF % | 9.4% | 8.6% |
| Reporting period | FY 2025-26 average | FY 2025-26 average |

This is a **district cooperative average price actually paid to farmers**, not a retail/consumer
price — the correct figure for the revenue side of the Affordability Model. It already reflects
quality-based rate differences, so it should be used as-is rather than further adjusted for fat/SNF
unless the sector template wants a more granular price-per-fat-point model later.

## Why Gokul and not a nearer union

The team's target district is Ahmadnagar (Sangamner). The nearest actual cooperative is:

**Sangamner Taluka Sahakari Dudh Utpadak & Prakriya Sangh Ltd. ("Rajhans Milk")**
At. Ghulewadi, Tal. Sangamner, Dist. Ahmednagar — founded 1977, collects ~2.76 lakh litres/day,
handles 55% of the district's cooperative milk (source: rajhansmilk.com, ncdfiemarket.com listing).

**This is the geographically correct source and should be preferred if a specific per-litre rate
can be obtained from them directly** (their public site does not publish one at the time of this
search). If the team can get a rate by phone/visit to the Sangamner union office, replace the
figure below and mark `geo_level: village` / `district` instead of the note below.

**Until then, Gokul's rate is used as a same-state proxy** — it is the only Maharashtra cooperative
with a currently published, dated, per-litre procurement rate found via search. Both are
Operation Flood-model cooperatives with broadly similar cost structures (fodder, labour, transport
inputs are regional, not union-specific), so this is a defensible stand-in, but it is **not**
an Ahmadnagar-specific number and must be labelled honestly.

## Exact Fact object to use in `dairy.yaml`

```yaml
milk_price:
  buffalo:
    value: 62.18
    unit: "INR_per_litre"
    source: "Gokul Dairy (Kolhapur Zilla Sahakari Dudh Utpadak Sangh Ltd.) — official procurement page"
    source_url: "https://www.gokulmilk.coop/procurement"
    year: 2026
    geo_level: "state"          # NOT district — this is a Kolhapur union rate, used as a MH proxy
    confidence: "medium"
    note: "Cooperative average purchase price incl. rate difference, FY2025-26. Sourced from
           Kolhapur district (Gokul), not Ahmadnagar, because no Ahmadnagar-specific published
           rate was found. Nearest actual union is Sangamner Taluka Sahakari Dudh Utpadak
           Sangh Ltd. (Ghulewadi, Tal. Sangamner) — replace this figure if their rate can be
           obtained directly. Do not present as an Ahmadnagar-specific price without updating
           geo_level and source."
  cow:
    value: 37.73
    unit: "INR_per_litre"
    source: "Gokul Dairy (Kolhapur Zilla Sahakari Dudh Utpadak Sangh Ltd.) — official procurement page"
    source_url: "https://www.gokulmilk.coop/procurement"
    year: 2026
    geo_level: "state"
    confidence: "medium"
    note: "Same as buffalo entry above — Kolhapur-sourced proxy, not Ahmadnagar-specific."
verified: true
```

Note the `confidence: medium` and `geo_level: state` — this is the honest labelling the plan
requires (PART 5.1: derived Fact inherits the coarsest geo_level of its inputs; PART 10: never
present district/state data as village-level without saying so). This is **not** the same kind
of gap as "we made up a number" — it's a real, dated, cited rate, one administrative level
coarser than ideal, labelled as such.

## Action item for the team (do in parallel, not blocking)

Call or visit the Sangamner Taluka Sahakari Dudh Utpadak Sangh Ltd. office (Ghulewadi, Tal.
Sangamner) and ask for their current buffalo/cow procurement rate per litre. If obtained:
replace the `value`, `source`, `source_url` (or note "verbal, confirmed [date]" if no URL
exists), set `geo_level: district`, `confidence: high`. This also strengthens the "we spoke to
a real field contact" point that already exists elsewhere in the project (PART 8, non-code work).
