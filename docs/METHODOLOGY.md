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

Responses are cached for 24 hours and calls are spaced to stay under the key's 5 requests/second.

### Interest parsing
Picks from the autocomplete already carry a Qloo entity ID. Free text is split by deterministic rules; if an
Anthropic key is configured, an LLM may extract interests instead, but every interest it returns must share a word
with the user's text or it is discarded.

### Matching
`/search` across movies, artists, TV, books, people, podcasts, brands, places, destinations and video games. The best
hit is accepted at a normalised name similarity ≥ 0.72. Otherwise `/v2/tags?filter.query=` is tried (≥ 0.6), then a
looser entity match (≥ 0.5, shown as “closest match”). Unmatched interests are listed, not hidden.

### Discovery and filtering
One place-insights call per category with `signal.interests.entities`, `signal.interests.tags`,
`filter.location.query`, `filter.tags` and `feature.explainability=true`. Because `filter.tags` is a soft union, each
returned place is re-classified from its **own** tags. Dropped: places tagged as non-experiences (banks, schools,
clinics, radio stations…), places marked closed, places above the chosen price level, and, when requested, places
without Qloo's `wheelchair_accessible_entrance` tag. About two-thirds of places have no price level; they are kept
and shown as “Price not listed”.

## Scoring

```
score = base − distance_penalty + boosts
```

| Term | Rule |
|---|---|
| base (Qloo mode) | Qloo `query.affinity` for your taste signals (0–1) |
| base (baseline) | share of your words found in the place's name, tags and keywords (0–1) |
| distance penalty | only with “low-carbon travel” or “I won't drive”: 0.02 per km beyond the first km, max 0.25 (car-free: 0.03, max 0.35) |
| nature boost | +0.05 for parks and gardens when “more time in nature” is on |
| plant-forward boost | +0.06 when the place's tags/keywords mention vegan, vegetarian or plant-based |
| secondhand boost | +0.06 when they mention thrift, vintage, second-hand or used |

Penalties and boosts are identical in both modes, so the comparison lab isolates the taste signal.

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

## Qloo schema provenance
docs.qloo.com blocks automated reading. Field names follow Qloo's hackathon developer guide and live-probe notes
published by other entrants. Parsers are tolerant: malformed records are dropped and unknown fields ignored.
No Qloo responses are stored in this repository, per Qloo's terms.
