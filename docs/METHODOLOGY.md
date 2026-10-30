# Methodology

Everything EarthPulse shows is either data Qloo listed, a number we computed from a cited source, or a
clearly labelled signal. This page documents each step, weight and source.

## Pipeline

| # | Stage | Agent | Qloo calls |
|---|---|---|---|
| 1 | Understand request | Taste Intelligence | 0 |
| 2 | Match interests | Taste Intelligence | 1–2 per interest (`/search`, then `/v2/tags` if no entity matches) |
| 3 | Taste portrait | Taste Intelligence | 2 (`/v2/insights`, `filter.type=urn:tag`: genre/keyword tags and ambience tags) |
| 4 | Discover places | Discovery | 1 per category (`/v2/insights`, `filter.type=urn:entity:place`) |
| 5 | Sustainability evidence | Sustainability | 0 (geocoding via Open-Meteo if a start point is given) |
| 6 | Plan | Planning | 0 |
| 7 | Verify | Verification | 0 |
| 8 | Explain | Explanation | 0 (one optional LLM call) |
| 9 | Taste Bridge | Taste Bridge | 1 (`/v2/insights` over the categories you didn't pick) |
| 10 | Grounding check | Grounding | 0 |

If a category returns a full first page (20) but fewer usable places than the plan needs after filtering, Discovery
re-queries that category once with `take=50`. This is the only retry that isn't an error retry, and it is shown in the
timeline.

Responses are cached for 24 hours and calls are spaced to stay under the key's 5 requests/second.

### Interest parsing
Picks from the autocomplete already carry a Qloo entity ID. Free text is split by deterministic rules; if an
Anthropic key is configured, an LLM may extract interests instead, but every interest it returns must share a word
with the user's text or it is discarded.

### Matching
`/search` across movies, artists, TV, books, people, podcasts, brands, places, destinations and video games. The best
hit is accepted at a normalised name similarity ≥ 0.85, or ≥ 0.72 if the names share a distinctive word (not a
generic one such as “magazine”, “records” or “film”). Otherwise `/v2/tags?filter.query=` is tried (≥ 0.6), then a
looser entity match (≥ 0.5 and a shared distinctive word, shown as “closest match”). All-lowercase concepts (“slow
living”) try tags first. Unmatched interests are listed, not hidden.

### Discovery and filtering
One place-insights call per category with `signal.interests.entities`, `signal.interests.tags`,
`filter.location.query`, `filter.tags` and `feature.explainability=true`. Because `filter.tags` is a soft union, each
returned place is re-classified from its **own** tags. Dropped: places tagged as non-experiences (banks, schools,
clinics, radio stations…), places marked closed, places above the chosen price level, and, when requested, places
without Qloo's `wheelchair_accessible_entrance` tag. About two-thirds of places have no price level; they are kept
and shown as “Price not listed”.

Every returned place is accounted for per category as kept or dropped. Dropped places carry a reason: duplicate,
other category, not an experience, closed, over budget, not step-free, or out of area. An empty category's note
quotes these counts, for example “Qloo returned 12 museums & culture for X, but none fit: 12 too far away (more than
25 km)”. Places are never invented to fill a category.

### Geographic validation
1. **Destination.** Qloo resolves the destination name (`filter.location.query`). Open-Meteo geocodes it too.
   - If Qloo's locality is more than 60 km from the geocoded city and too few places come back, discovery retries
     once with `filter.location=POINT(lon lat)` and `filter.location.radius=15000` around the geocoded point.
   - The retry is shown in a note and in the discovery stage.
   - This is how “Copenhagen” (matched by Qloo to a small namesake town) was fixed.
2. **Start point.** The start is your geocoded starting point, if it lies within 60 km of the destination.
   Otherwise it is the geocoded city centre, if that lies within 60 km of Qloo's locality. Otherwise it is
   Qloo's locality point.
3. **Area gate.** A place more than `DISCOVERY_RADIUS_KM` (default 25 km) in a straight line from the start is
   dropped and counted as “out of area”. So is a place with impossible coordinates (latitude outside ±90 or
   longitude outside ±180). A place with no coordinates is kept but labelled Not verified, with no distance or
   CO2e.
4. **Nothing in the area.** If no place survives, the run stops with “try a specific city” rather than building
   a plan from far-away places. A whole-state destination such as “Oregon” produced a 1,924 km plan before this
   gate existed.
5. **Grounding.** The grounding check independently re-verifies that every place shown is within the radius and
   that no leg exceeds twice the radius.

## Scoring

```
score = base − distance_penalty + boosts
```

| Term | Rule |
|---|---|
| base (Qloo mode) | Qloo `query.affinity` for your taste signals (0–1) |
| base (baseline) | share of your words found in the place's name, tags and keywords (0–1) |
| distance penalty | with “low-carbon travel”, “I won't drive”, or the slider above its midpoint: 0.02 per km beyond the first km, max 0.25 (car-free: 0.03, max 0.35), multiplied by 2 × balance |
| balance | the “More like my taste ↔ Lighter footprint” slider, 0 to 1 in steps of 0.25 (default 0.5, so the multiplier is 1). At 0 distance is ignored; at 1 it counts double. |
| nature boost | +0.05 for parks and gardens when “more time in nature” is on |
| plant-forward boost | +0.06 when the place's tags/keywords mention vegan, vegetarian or plant-based |
| secondhand boost | +0.06 when they mention thrift, vintage, second-hand or used |

Penalties and boosts are identical in every mode, so the comparison lab isolates the taste signal. Hard constraints
(category, budget, step-free, car-free, area, not closed) are filters applied before scoring, so no weight can trade
them away. Ties are broken by Qloo popularity, then by the order Qloo returned. The weights are judgement calls, not
an objectively correct trade-off; the slider exists so the user can make the trade-off themselves.

### Comparison arms
- **Qloo:** base = Qloo affinity.
- **Keyword:** no taste signals sent to Qloo; base = keyword overlap.
- **Footprint only:** same candidate pool as keyword; base = 1 − min(distance, radius) ÷ radius, plus 0.05 for a
  lower-impact tag; unknown distance scores 0.

### Lighter swap
For each planned stop, an unplanned place in the same category qualifies if its base score is within 0.06 of the
stop's, it is at most 60% of the distance, and at least 1 km closer. The best-matching qualifier is shown with the
round-trip CO2e saved by car (or by bus when car-free).

### Day plans
Each day takes the next-best place per category (one stay at most), ordered by time of day: cafés in the morning,
parks at midday, culture and shops in the afternoon, food and music in the evening. Legs run start → stops → start.
Each leg suggests walking if ≤ 2.5 km, otherwise bus/transit, and is compared with driving.

## Emissions

Source: U.S. EPA, *GHG Emission Factors Hub*, 2025 edition, Table 10
(<https://www.epa.gov/system/files/documents/2025-01/ghg-emission-factors-hub-2025.pdf>).
CO2e = CO2 + 28 × CH4 + 265 × N2O (AR5 GWPs from the Hub's Table 11).

| Mode | CO2 kg | CH4 g | N2O g | Unit | CO2e kg |
|---|---|---|---|---|---|
| Passenger car | 0.297 | 0.0059 | 0.0053 | vehicle-mile | 0.2986 |
| Bus | 0.066 | 0.0046 | 0.0019 | passenger-mile | 0.0666 |
| Transit rail | 0.093 | 0.0075 | 0.0010 | passenger-mile | 0.0935 |

Car emissions are divided by the number of travellers. Walking and cycling are counted as zero tailpipe emissions
(cycling offered within 10 km, walking within 2.5 km; EarthPulse heuristics).

**Assumptions and uncertainty.** Distances are great-circle (haversine), so real routes are longer and every figure
is a lower bound. Factors are U.S. national averages. Transit factors vary widely with occupancy, and no transit
route is verified. Numbers are for comparing options, not for carbon accounting.

## Verification
Before display every stop is re-checked: category from its own tags, not a non-experience, not marked closed, within
budget (or price not listed), step-free if requested, and its CO2e figures recomputed independently. A stop failing a
hard check is replaced by the next-ranked alternate that passes, and the replacement is reported.

## Explanations
Each card's “why” is built from facts only: Qloo explainability (which of your interests contributed most), taste
themes shared with your portrait, the place's own Qloo tags, lower-impact tag signals and computed distance. If an
LLM is configured it may reword those facts; any sentence containing a number not present in the facts is rejected,
and accepted sentences are labelled AI-written.

## Grounding check
Runs on every result (and both comparison lists) before it is sent. Checks: provenance (place ids and names match
what the Qloo client recorded from this run's responses), interests, affinity values, explanation numbers (AI text
repaired if needed), geography (every place within the radius, no leg over twice the radius), arithmetic (CO2e
recomputed, totals re-added), constraints, claim labels. A hard failure
withholds the result with an error.

## Qloo schema provenance
docs.qloo.com blocks automated reading. Field names follow Qloo's hackathon developer guide and live-probe notes
published by other entrants. Parsers are tolerant: malformed records are dropped and unknown fields ignored.
No Qloo responses are stored in this repository, per Qloo's terms.
