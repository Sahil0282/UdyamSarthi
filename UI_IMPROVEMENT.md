# UI/UX Audit — Udyam Saarthi

Analysis pass only when written. **All three passes have since been executed** —
see the status note at the end of each finding. Screenshots of all 15 original
states in `/tmp/audit/`, with after-shots alongside them.

---

## Diagnosis

The interface was built to prove the engine works, and it succeeds at that: every
number is on screen, every number is tappable, the map draws the real polygon.
Nobody looking at it would doubt the data is real.

But it was never designed. It reads as a government portal for reasons that are
specific and fixable, not vague:

**The whole UI is 65 lines of CSS.** Ten different font sizes between 10px and
17px, chosen ad hoc (10.5px, 11.5px, 12.5px) with no scale. Nine flat colours and
no tints. Zero transitions, zero animations, zero SVG icons, one media query, no
dark mode, and a system font stack. Those aren't stylistic preferences — they are
the absence of a design system, and the eye reads that absence immediately.

**The verdict — the product's entire reason to exist — is 16px, one pixel smaller
than the page header, and sits below the input form.** PROCEED and RECONSIDER are
rendered in the same box, the same size, the same layout, differing only in a word
and a 4px border colour. The single most consequential distinction the system makes
is nearly invisible.

**The map occupies about 70% of the screen and carries almost none of the
product's story.** It is unstyled OpenStreetMap raster tiles: expressway shields,
airport icons, tree symbols, admin boundaries, landuse greens. Our village polygon
is a translucent green sitting on top of OSM's own green landuse, and the buyer
points are 6px dots the same colour as a road casing. The most visually rich
surface is the most under-designed.

And one finding is not cosmetic at all: **while a new request is computing, the
panel keeps showing the previous village's verdict and numbers.** Ask about Murmi
and for several seconds you are looking at PROCEED with Nimgaon Jali's ₹7,56,665.
In a product whose entire pitch is provenance, that is a correctness problem
wearing a UI costume.

What follows is ordered by what changes a first impression fastest, not by effort.

---

## Findings

### 1. Stale results are shown as current during a request
**Severity: critical — this is a trust bug, not a style bug**

**Before.** Submitting a new query leaves the entire panel populated with the
previous result. The only change is the button label going to "Computing…". For
the 4–6 seconds a request takes, the screen shows a confident PROCEED, a full
financial roadmap, and a map of the wrong village — all belonging to a question
the user is no longer asking.

**Why it reads as low quality.** Every other claim the product makes rests on "the
number you see is traceable to a source." Showing last village's ₹7,56,665 next to
this village's name silently breaks that. A judge who notices it will discount
everything else. It also makes the app feel unresponsive, because nothing visibly
acknowledges the click.

**Fix direction.** On submit, clear the result state immediately and render a
skeleton for the verdict card, the roadmap rows and the map overlay. Dim the map's
existing layers rather than leaving them authoritative. The button already
disables — it needs a spinner and the panel needs to stop asserting.

---

### 2. The verdict has no more visual weight than a form label
**Severity: critical — this is the product's core moment**

**Before.** `.vtitle` is `font-size:16px`, inside a white card with a 4px left
border, below four form fields. The masthead `h1` is 17px. Score and confidence
render as two small grey pills that look like disabled buttons.

**Why it reads as low quality.** A judge's eye lands on the largest, highest-contrast
element. Right now that is the map's expressway labels, then the "Get advice"
button, then — eventually — the verdict. The system's whole argument is "we can tell
you no", and the no is smaller than the input that produced it.

**Fix direction.** Make the verdict a hero block at the top of the panel, above the
form, with the input collapsing to a compact summary row once a result exists
("Nimgaon Jali · ₹1,00,000 · Dairy · change"). Set the verdict at 28–34px with a
short plain-language subtitle beneath it ("This plan looks workable" /
"We advise against this in this village"). Give it a distinct surface — not the
same white card as every other section.

---

### 3. PROCEED and RECONSIDER are visually interchangeable
**Severity: critical**

**Before.** Both states use the identical card, type size and layout. The
differences are the word itself and `border-left-color` (green vs red). A
RECONSIDER driven by two *blocking* hard gates looks the same as a comfortable
PROCEED.

**Why it reads as low quality.** The refusal is the differentiator — the README
calls it "the point". Rendering the refusal in the same clothes as the approval
tells the viewer the system does not take its own conclusion seriously. There is
also no visual escalation for a hard gate versus an ordinary reason: both are grey
bullet text.

**Fix direction.** Give each verdict its own treatment. RECONSIDER: a serious,
dense header with the blocking reasons promoted directly under the verdict as
two or three labelled cards ("No all-weather road", "No buyer within 8 km"), each
carrying the evidence figure. PROCEED: calmer, with the recommended loan as the
hero number and the eligible-vs-recommended gap as the supporting story.
PROCEED_WITH_CHANGES needs a third, visibly distinct treatment.

---

### 4. The map is raw OpenStreetMap and fights our own data
**Severity: high — largest surface, most under-designed**

**Before.** A single raster layer from `tile.openstreetmap.org`. Full-colour road
classification (red/orange/yellow), airport glyphs, tree symbols, town labels at
every level, blue watercourses, green landuse. Our layers sit on top: village fill
`#1f7a4d` at 0.28 opacity, catchment fill `#2b5f8f` at 0.08 (which reads as a grey
"disabled" wash), and 5–18px circles for buyers.

**Why it reads as low quality.** Two separate problems. First, visual competition:
the village polygon is a green translucent shape over OSM's green landuse, so the
boundary is mush at any zoom, and the buyer dots are the same weight and hue as a
secondary road. Second, semantic noise: none of OSM's default emphasis (highway
hierarchy, airports, forests) relates to the question being asked, so 70% of the
screen is decoration.

**Fix direction.** Move to a muted vector or greyscale basemap so the product's own
layers are the only saturated things on screen — a desaturated Carto/Stadia style,
or a filtered raster as an interim step. Then design our three layers as a set:
village boundary as a confident stroke with a subtle fill; the catchment ring as a
clear band with an "8 km" label attached to it rather than only in a legend; buyer
points as scaled, outlined markers with a permanent count badge. On RECONSIDER,
the *absence* of buyers is the most eloquent fact available — draw an explicit
empty-state on the map ("No milk buyer within 8 km") instead of just omitting dots.

---

### 5. The narration is a 1,100-character wall of unformatted text
**Severity: high**

**Before.** The advisory renders as one grey block of 13–16 lines at 13px. The key
figures — ₹9,00,000 eligible, ₹7,56,665 recommended, ₹20,898 working capital — are
buried mid-sentence in the same weight as everything around them.

**Why it reads as low quality.** Nobody reads it. The prose is genuinely good and
carefully validated, and the presentation guarantees it gets skimmed. It also
duplicates the roadmap table directly beneath it without acknowledging the overlap.

**Fix direction.** Keep the full narration but give it structure: lead with a
one-sentence summary at larger size, emphasise monetary figures inline, and break
the remainder into two or three short paragraphs. Consider collapsing the full text
behind "read the full assessment" with the summary always visible. The Marathi
version needs the same treatment and a proper Devanagari-capable font.

---

### 6. No type scale
**Severity: high — this is the root cause behind several other findings**

**Before.** Ten distinct sizes: 10, 10.5, 11, 11.5, 12, 12.5, 13, 14, 16, 17px,
three of them at half-pixel values. (The audit first said twelve; the verified
count is nine `font-size` declarations plus 14px in the body shorthand.) `font:14px/1.55 -apple-system…` on body and
nothing else declared. No webfont.

**Why it reads as low quality.** Arbitrary half-pixel sizes are the visual signature
of styling added reactively rather than designed. With no scale there is no
hierarchy, so everything competes and the eye has nowhere to rest — which is why
the verdict, the table rows and the risk flags all read as equally important.

**Fix direction.** Adopt a modular scale (roughly 11 / 13 / 15 / 18 / 24 / 32 / 44)
and map every element onto it. Pair two faces: a display face with some character
for the verdict and headings, and a clean humanist sans for body and data, both
with Devanagari coverage so Marathi does not fall back to a system face mid-sentence.
Use tabular figures everywhere currency appears.

---

### 7. Financial data is presented as a spreadsheet, not a designed component
**Severity: high**

**Before.** Eleven `<tr>` rows, label left, value right, hairline rule between.
"RECOMMENDED loan" — the primary output of the whole affordability engine — has
exactly the same visual weight as "Milk price used". Values show unhelpful
precision: `₹7,56,665.33` (paise on a loan), `0.99` for survival probability,
`10` for yield with no unit.

**Why it reads as low quality.** It looks like a database dump with a stylesheet.
The one number the user should leave remembering is indistinguishable from an input
assumption. Trailing paise on a lakh-scale figure signals nobody considered how the
number would be read.

**Fix direction.** Split the table into a hierarchy: a hero figure for the
recommended loan with the eligible amount shown as a struck-through or secondary
comparison; a compact "how we got there" group for revenue − opex − drawings; and
inputs/assumptions visually demoted. Round currency to whole rupees, render
survival as "99 out of 100 runs", and attach units to every figure. A small
horizontal bar comparing eligible vs recommended vs EMI capacity would carry this
faster than any row of numbers.

---

### 8. The provenance popup breaks the layout and floats free of its number
**Severity: medium — but it is the feature judges will test**

**Before.** Tapping a number inserts a grey block *below* the table row, pushing
everything beneath it down the page. There is no pointer, arrow or highlight
connecting the panel to the number that opened it. Content is small grey text with
a `year · level · confidence` line and a long note.

**Why it reads as low quality.** Layout jump on click is the clearest possible
signal of an undesigned interaction. Because the panel is disconnected, on a long
table it is genuinely ambiguous which number it belongs to. This is the feature that
proves the product's central claim, and it currently feels like a debug affordance.

**Fix direction.** Anchor it as a popover attached to the tapped number, with a
pointer and a persistent highlight on the source value. Structure it: source name,
then a metadata row rendered as chips (year / geo level / confidence), then the
note. Colour-code the confidence chip so `state · medium` and `national · low` are
legible at a glance — that is the honesty argument made visual. Only one open at a
time.

---

### 9. Zero motion or interaction feedback
**Severity: medium**

**Before.** `grep transition|animation|@keyframes` returns nothing. No hover
transitions, no focus animation, no state change easing, no map fly-to easing
beyond MapLibre's default, no skeletons.

**Why it reads as low quality.** Every state change is an instant jump. Modern
interfaces communicate causality through motion — the absence makes the app feel
like a rendered document rather than software responding to you.

**Fix direction.** A small, restrained set: 120–160ms ease on hover/focus for
interactive elements, a fade+rise for the verdict card when a result lands, a
skeleton shimmer during compute, and an eased map transition between villages.
Respect `prefers-reduced-motion`. Nothing decorative — motion only where it
explains a state change.

---

### 10. Iconography is two emoji, and nothing else
**Severity: medium**

**Before.** `🎙 Speak` and `🔊 Listen` are the only icons. Risk severity is a
lowercase word (`high` / `medium` / `low`) in coloured text. Verdicts, sections,
alternatives and provenance have no visual markers.

**Why it reads as low quality.** Emoji render differently per platform and read as
placeholder. Meanwhile severity — genuinely important information — is encoded only
in a small word, so the eye cannot triage risks without reading each one.

**Fix direction.** One consistent inline SVG icon set (a 16/20px stroke set,
inlined — the CSP blocks external icon fonts). Encode severity in shape *and*
colour: a filled triangle for high, a dot for medium, a hollow ring for low, so the
risk list can be scanned in one pass. Replace the emoji on the voice controls with
a proper mic and speaker glyph, and give recording an unmistakable active state.

---

### 11. Mobile is broken, not just cramped
**Severity: medium (high if it will be demoed on a phone)**

**Before.** At 390px the map collapses to zero height. The absolutely-positioned
legend floats up and overlaps the masthead, covering the title. The form fills the
entire first screen; the verdict is below the fold.

**Why it reads as low quality.** It is visibly broken, not merely unoptimised. The
single media query sets `grid-template-columns:1fr` and `#map{height:52vh}`, but the
map container's parent has no height in that context so the canvas never sizes.

**Fix direction.** Fix the container height first (a real bug), then design the
narrow layout deliberately: verdict first, map as a collapsible panel beneath it,
form behind a "change query" control. The legend should be in normal flow on narrow
screens, not absolutely positioned.

---

### 12. The legend makes a claim that is false on RECONSIDER
**Severity: low individually, but it is a credibility detail**

**Before.** The legend always renders "● buyers (milk plants)" — including for
Murmi, where the count is zero and no dots are drawn.

**Why it reads as low quality.** A legend entry for a series with no members. On the
one screen where absence of buyers is the entire finding, the UI still implies they
exist.

**Fix direction.** Make the legend reflect actual state: show the count inline
("buyers within 8 km — 5"), and when zero, replace with an explicit
"no buyers found within 8 km" treated as a finding rather than a missing layer.

---

### 13. No dark mode, and no considered neutral
**Severity: low**

**Before.** `--bg:#faf9f7` with no `prefers-color-scheme` block anywhere. Nine flat
colours, no tints or shades, so every hover and disabled state is improvised.

**Why it reads as low quality.** On a dark-themed laptop the page is a bright slab.
More practically, having no tint ramp is why several components fall back to plain
white cards with the same border.

**Fix direction.** Define a token set with 3–4 steps per hue (surface, raised, hover,
border) and a semantic layer (`--verdict-good`, `--verdict-warn`, `--verdict-stop`)
kept separate from the brand accent. Then add a dark theme via tokens only.

---

### 14. Header wastes the most valuable strip on the page
**Severity: low**

**Before.** The masthead carries the title, a tagline, and `run b93fd7ac95d79c15` —
a raw 16-character hash — in the top-right, at the same weight as the tagline.

**Why it reads as low quality.** The run id is a reproducibility feature, not a
headline. Placing it beside the product name is the "built by engineers, laid out by
nobody" signal.

**Fix direction.** Demote the run id into the provenance section where it belongs
(with a copy affordance), and use the reclaimed space for the district context or
leave it quiet.

---

## Proposed execution order

Three passes. Each ends somewhere demoable.

**Pass 1 — trust and hierarchy** (findings 1, 2, 3, 6)
Fix the stale-result bug first; it is the only finding here that is genuinely a
correctness issue. Then establish the type scale and token system, because findings
2 and 3 cannot be done properly without it, and rebuild the verdict as a hero with
distinct PROCEED / PROCEED_WITH_CHANGES / RECONSIDER treatments. This is the pass
that changes the first three seconds.

**Pass 2 — the map and the numbers** (findings 4, 7, 5, 12)
Replace the basemap and design the three data layers as a set, including the
empty-state for zero buyers. Rebuild the financial roadmap as a designed component
with a real hero figure and correct number formatting. Restructure the narration.
This is the pass that makes the product look like it was designed by someone who
understood the data.

**Pass 3 — interaction polish** (findings 8, 9, 10, 11, 13, 14)
Anchored provenance popover, the motion set, the icon set, the mobile layout fix,
dark mode, header cleanup.

**Deliberately not proposed:** a redesign of the information architecture. The
current section order — verdict, market, roadmap, stress test, risks, why,
alternatives, provenance — is a sound narrative and matches how the engines
actually reason. The problem is that every section is rendered at the same weight,
which is a hierarchy problem, not a structure problem.

One caveat on scope: passes 1 and 2 touch `web/index.html` only. Nothing above
requires changing an engine, an API response or a Fact — the data the UI needs is
already in the envelope, including the buyer count, the severity levels, the hard
gates and the full provenance. This is a presentation-layer job throughout.

---

## Execution record

**Pass 1 and Pass 2 — done.** Findings 1, 2, 3, 6, 4, 7, 5, 12 all implemented.
Three bugs surfaced while building that the audit had not predicted: bar fills
rendered at 0px because a `<span>` in a non-flex parent stays `display:inline`;
panel sections were squeezed because flex children shrink by default; and CARTO's
basemap now demands an API key, so the muting is done with raster paint
properties on keyless OSM tiles instead.

**Pass 3 — done, with a correction to this document's own estimate.** Four of the
six items in Pass 3 had already been delivered in Pass 2 as a side effect of
building the token and icon system:

| Finding | Expected in Pass 3 | Actually found |
|---|---|---|
| 10 · iconography | replace emoji, build an icon set | already done — 0 emoji, 15 inline SVG icons. Only the severity *shapes* needed sharpening |
| 9 · motion | build the motion set | already done — 6 transitions, 4 keyframes, reduced-motion block |
| 14 · header | demote the run id | already done — run id was already out of the masthead. Only a copy affordance was missing |
| 13 · dark mode | add it | already done — 30 tokens redefined under `prefers-color-scheme` |

Only **8** (the popover) and **11** (mobile) were real work. That is a
mis-estimate in the original prioritisation, not extra scope discovered: Pass 2's
token work carried more of Pass 3 than this document anticipated.

One further bug caught by looking at a screenshot rather than by an assertion:
the anchored popover was clipped by `.sec { overflow: hidden }`. The
layout-shift test passed — there genuinely was no shift — while the chips and
the note were cut off and unreadable. An explicit clipping assertion now guards
it.
