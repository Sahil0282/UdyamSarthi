# NABARD Buffalo Dairy — Yield & Opex Source Document
### For `data/sectors/dairy.yaml` — replaces the plan's placeholder illustrative figures

Same discipline as MILK_PRICE_SOURCE.md: a real published benchmark, cited, not invented.
This does NOT replace the milk price (already sourced separately) — it supplies the physical
input side: how much milk an animal gives, and what it costs to feed and run the unit.

---

## Source

**NABARD Model Bankable Project Report — Dairy Farming with Buffaloes (10-animal unit)**
Reproduced in full table form at:
https://www.pashudhanpraharee.com/nabard-model-dairy-farming-project-report/
(Pashudhan Praharee — livestock industry trade publication; the article reproduces NABARD's
own model project template verbatim, including its per-unit technical and financial parameters.
This is the standard reference model circulated by banks and NABARD field offices for dairy
loan appraisal — the same category of document as the PLP already in use for the district.)

**Type of animal:** Graded Murrah Buffalo — matches the sector template's existing
"Buffalo Farming (1+1)" framing.

**Caveat to carry into the note field:** this is a **generic national model**, not
Ahmadnagar-specific, and it is undated in the source article (originally published 2019,
content is NABARD's standard reusable template). Treat exactly like the milk price proxy —
real, citable, but one level coarser than ideal. `geo_level: national`, `confidence: low`.

---

## Figures to use

### Milk yield

| Parameter | Value | Note |
|---|---|---|
| Average milk yield | **10 litres/animal/day** | during lactation |
| Lactation days | 270 (Year 1: 240) | per lactation cycle |
| Dry days | 150 (Year 1: 30) | non-yielding period |

The plan's placeholder used 6 L/day. NABARD's model uses **10 L/day** for a graded Murrah
buffalo. Use 10, and use the lactation/dry split rather than a flat daily figure across the
whole year — a buffalo does not yield milk 365 days a year, and the sector YAML should reflect
that if `working_capital_months` and monthly revenue are meant to interact with seasonality.

**Simplification for the M4 formula as currently structured:** if the affordability engine
computes a flat monthly average rather than a lactation-cycle model, use the annualised average:
`(270 × 10) / 365 ≈ 7.4 litres/animal/day` averaged across a full year. Flag which approach was
taken in the resulting Fact's note.

### Capex (per-animal, scalable down from the model's 10-animal unit)

| Item | NABARD model (10 animals) | Per animal |
|---|---|---|
| Cost of animal | ₹5,00,000 | ₹50,000 |
| Transportation | ₹10,000 | ₹1,000 |
| Shed construction | ₹60,000 | ₹6,000 |
| Calf shed | ₹24,000 | ₹2,400 |
| Chaff cutter + equipment | ₹60,000 | ₹6,000 (shared capex, not strictly per-animal) |
| **Total capital cost** | **₹6,54,000** | **₹65,400/animal** (incl. shared equipment share) |

Note: your existing dairy.yaml already has `bank_loan_factor: 0.85` from the PLP. This capex
table is independent of that — it's the underlying asset cost the loan is sized against.

### Monthly opex (derived from NABARD's daily feeding schedule)

| Feed type | Lactation (₹/day) | Dry period (₹/day) |
|---|---|---|
| Concentrate feed (5kg @ ₹12/kg lactation, 2kg dry) | ₹60 | ₹24 |
| Green fodder (25kg @ ₹1/kg lactation, 20kg dry) | ₹25 | ₹20 |
| Dry fodder (4kg @ ₹2/kg lactation, 5kg dry) | ₹8 | ₹10 |
| **Total feed cost/animal/day** | **₹93** | **₹54** |

Weighted annual average (270 lactation + 150 dry = 420 days does not equal 365 — the model's
own table has this mismatch, most likely because Year 1 has a different lactation/dry split
than steady-state years 2–5. **Use the steady-state split for a working unit, not Year 1**,
and flag the 420≠365 discrepancy in the Fact's note rather than silently reconciling it):

`(270 × 93 + 150 × 54) / 365 ≈ ₹90.98/animal/day ≈ ₹2,729/animal/month` (feed only)

Plus, annualised to monthly, per animal:

| Item | Annual (10 animals) | Per animal/month |
|---|---|---|
| Veterinary aid + breeding | ₹10,000 | ₹83 |
| Labour | ₹54,000 | ₹450 |
| Electricity + misc | ₹1,500 | ₹13 |
| Insurance (5% of asset value/yr) | ₹25,000 | ₹208 |

**Total opex per animal per month ≈ ₹2,729 (feed) + ₹83 + ₹450 + ₹13 + ₹208 ≈ ₹3,483/animal/month**

The plan's placeholder used ₹5,800/animal — this NABARD-derived figure comes out lower, mainly
because labour and vet costs are shared across a 10-animal unit in the source model and don't
scale linearly down to a 1–2 animal household unit. **Flag this scaling assumption explicitly**:
a 2-animal household unit will likely carry proportionally higher per-animal labour/vet cost
than a 10-animal commercial unit, because labour isn't usually hired part-time in practice —
it's the farmer's own time. Recommend keeping ₹450/month labour as a lower bound and noting in
the Fact that real household-scale opex may run higher, rather than presenting the 10-animal
unit's cost structure as directly applicable to a 1-2 animal borrower without comment.

---

## Exact Fact objects for `dairy.yaml`

```yaml
yield:
  value: 10.0
  unit: "litres_per_animal_per_day"
  source: "NABARD Model Bankable Project — Dairy Farming with Buffaloes (10-animal unit),
           graded Murrah buffalo, via Pashudhan Praharee reproduction"
  source_url: "https://www.pashudhanpraharee.com/nabard-model-dairy-farming-project-report/"
  year: null
  geo_level: "national"
  confidence: "low"
  note: "NABARD's generic model project figure, undated, not Ahmadnagar-specific. Applies
         during lactation only (270 days/yr); annualised average is ~7.4 L/day if a flat
         year-round figure is needed. Original source scaled for a 10-animal commercial unit;
         may not transfer exactly to a 1-2 animal household unit."

monthly_opex_per_animal:
  value: 3483
  unit: "INR_per_animal_per_month"
  source: "Derived from NABARD Model Bankable Project feeding schedule and annual cost table
           (feed, vet, labour, electricity, insurance), via Pashudhan Praharee reproduction"
  source_url: "https://www.pashudhanpraharee.com/nabard-model-dairy-farming-project-report/"
  year: null
  geo_level: "national"
  confidence: "low"
  note: "Derived, not a single published line item — see MILK_YIELD_OPEX_SOURCE.md for the
         calculation. Scaled down from a 10-animal commercial unit; labour and vet costs are
         shared across the unit in the source model and may understate true per-animal cost
         for a 1-2 animal household unit where labour is the farmer's own unpaid time."

capex_per_animal:
  value: 65400
  unit: "INR_per_animal"
  source: "NABARD Model Bankable Project — Dairy Farming with Buffaloes, capital cost table
           (animal + transport + shed + calf shed + equipment share), via Pashudhan Praharee"
  source_url: "https://www.pashudhanpraharee.com/nabard-model-dairy-farming-project-report/"
  year: null
  geo_level: "national"
  confidence: "low"
  note: "Includes a pro-rated share of shared equipment (chaff cutter) costed across the
         10-animal model unit; a genuinely standalone 1-2 animal purchase may not need the
         full equipment share."
verified: true
```

---

## What this does and doesn't fix

**Fixes:** dairy's revenue and opex lines now trace to a real, named, citable source instead of
the plan's own illustrative placeholder numbers. The Affordability Model's arithmetic is
unchanged — only the inputs feeding it are now sourced.

**Doesn't fix, and shouldn't claim to:** this is still `confidence: low` and `geo_level:
national`, same as the milk price is `medium`/`state`. That's correct and should stay visible
in the final envelope — it is a genuine, real limitation (no Ahmadnagar-specific or even
Maharashtra-specific unit economics benchmark was found), not a data-completeness failure to
paper over. If asked "how confident are you in the dairy numbers," the honest answer is:
"the geospatial and financial-rules machinery is fully sourced and village-specific; the
underlying unit economics — yield and opex — are a national benchmark, which is why the
system reports this verdict as low confidence rather than high."

## Action item, same pattern as the milk price

A phone call to Sangamner Taluka Sahakari Dudh Utpadak Sangh (or a local veterinary officer,
per the plan's own PART 8 "one non-code conversation") asking "what does a 2-buffalo household
unit actually cost to run per month, and what yield is typical" would upgrade both Facts above
from `national/low` to `district/high` with a single conversation, and is exactly the kind of
field-grounding your implementation plan calls out as the single strongest thing a team can do
in a weekend.
