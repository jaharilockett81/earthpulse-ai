# Evaluation: Qloo taste vs. keyword vs. footprint-only (live)

**Source:** the live deployment at https://earthpulse-ai-plos.onrender.com, which calls the Qloo hackathon API
(`fixtures: false` on every response). It was measured on 2026-10-30 between 05:08 and 05:13 UTC through
`GET /api/check?compare=true`, which runs the same pipeline as the Comparison Lab. The deployment was commit
`bf88943`; later commits change UI, accounting and docs only, not these metrics.
Only aggregate metrics are recorded here. No place names or other Qloo response data are stored, per Qloo's terms.

**Reproduce:** `python scripts/evaluate.py --url https://earthpulse-ai-plos.onrender.com --out eval.md --json eval.json`.
Qloo's rankings can change over time, so expect the same shape of result rather than identical numbers.

## Hypothesis

Qloo's cross-domain taste signals change *which* places are recommended, not only their order. They do this
without making trips meaningfully longer than a taste-blind plan.

## Setup

- **Five personas.** These are invented test inputs, not real users. Each has 3–4 cross-domain interests
  (film, music, books, brands, concepts), a city, and four categories.
- **Two-day plans.** Each arm returns its top 6 places.
- **Three arms.** All three use the same Qloo place directory, city, categories, filters, 25 km area,
  verification and EPA carbon rules:
  - **Q, Qloo taste:** ranked by Qloo affinity for the user's resolved interests.
  - **K, Keyword:** no taste signals, ranked by overlap between the user's own words and each place's name,
    tags and keywords.
  - **F, Footprint only:** no taste signals, ranked by straight-line distance from the start, plus a small
    bonus for a lower-impact Qloo tag.
- Every arm passed the grounding validator, including the geography check (every place within 25 km and no
  leg over 50 km), on every persona.

## Results per persona

| Persona | City | Interests matched | Overlap Q∩K | Overlap Q∩F | Theme match Q/K/F | Avg km from start Q/K/F | Plan km Q/K/F | Plan kg CO2e Q/K/F | Qloo calls |
|---|---|---|---|---|---|---|---|---|---|
| P1 Ghibli naturalist | Kyoto | 4/4 (1 broader tag) | 2/6 | 0/6 | 0 / 0 / 0 | 1.88 / 3.48 / 1.01 | 13.69 / 32.16 / 17.61 | 0.00 / 1.08 / 0.42 | 15 |
| P2 Vinyl & jazz | Chicago | 3/3 | 0/6 | 1/6 | 1.00 / 0.67 / 1.00 | 2.00 / 4.39 / 2.92 | 24.33 / 22.96 / 28.81 | 0.71 / 0.78 / 0.98 | 13 |
| P3 Slow-living reader | Lisbon | 3/3 | 0/6 | 2/6 | 0 / 0 / 0 | 1.05 / 1.21 / 0.89 | 13.15 / 15.58 / 10.66 | 0.11 / 0.00 / 0.00 | 13 |
| P4 Outdoor maker | Portland, OR | 3/3 | 2/6 | 2/6 | 0.83 / 0.83 / 0.83 | 0.72 / 0.62 / 0.55 | 8.27 / 11.70 / 10.91 | 0.00 / 0.24 / 0.25 | 13 |
| P5 Design lover | Copenhagen | 2/3 | 0/6 | 0/6 | 0 / 0 / 0.17 | 1.06 / 0.67 / 0.59 | 11.28 / 5.29 / 5.45 | 0.13 / 0.00 / 0.00 | 22 |

Interest matches were checked with single runs on the same deployment. Every input resolved to the
same-named Qloo entity or tag, with two exceptions. P1's "wildlife photography" matched the broader Qloo tag
"Photography". P5's "Kinfolk magazine" is not in Qloo's catalogue, and the app says so rather than
substituting a different magazine (an earlier build matched it to "InStyle Magazine"; fixed in `3463e6e`).

## Averages over the five personas

| Metric | Qloo | Keyword | Footprint |
|---|---|---|---|
| Overlap with the Qloo list (of 6) | n/a | 0.8 | 1.0 |
| Average straight-line distance from start (km) | 1.34 | 2.07 | 1.19 |
| Planned travel, straight-line (km) | 14.14 | 17.54 | 14.69 |
| Planned CO2e, walking + transit (kg) | 0.19 | 0.42 | 0.33 |
| Theme match with the Qloo portrait | 0.37 | 0.30 | 0.40 |

## What this shows

- **Qloo changes what is recommended.** On average fewer than one of the six places in the Qloo list also
  appears in the keyword list, and one in six in the footprint-only list. Taste signals select different
  places, not a re-sorted copy of the same ones.
- **Taste did not cost distance here.** Qloo plans averaged 14.1 km of straight-line travel. Keyword plans
  averaged 17.5 km and footprint-only plans 14.7 km. Qloo plans were shorter than keyword plans for 3 of 5
  personas and longer for 2 (Chicago, Copenhagen).
- **Footprint-only is closest to the start, as designed.** It had the lowest average distance from the
  start (1.19 km). Its whole-plan totals were not always the lowest, because plan travel also depends on
  the hops between stops.

## Where Qloo did not win

- **Theme match.** The automatic "theme match" proxy did not favour Qloo on average (0.37 vs. 0.30 vs. 0.40).
  For three personas it was 0 for every arm, because the portrait themes (such as film genres) rarely
  appear as place tags. This proxy is weak and is reported only for transparency.
- **Keyword match.** The keyword arm matched the user's literal words more often, as expected, since that
  is what it optimises.
- **Copenhagen (P5).** The keyword and footprint plans were shorter than the Qloo plan.

## Limitations

- Five personas is a smoke-level sample. No significance testing was done and none is claimed.
- **Cultural relevance is not measured by these numbers.** It needs human judgment. The Comparison Lab
  collects blind A/B ratings in each viewer's browser; no ratings from real users have been collected for
  this report.
- Distances are straight-line (haversine) from the start, a lower bound on real travel. CO2e uses EPA
  2025 factors (see `docs/METHODOLOGY.md`). A plan total of 0.00 kg means every leg was 2.5 km or less
  and was assigned walking, not that data was missing.
- Qloo's results for a city can change between runs, and Qloo's own place-search coverage varies by city.
  For example, "Copenhagen" matched a much smaller namesake town until discovery switched to querying around the
  geocoded city point. That change came after this run, so these numbers come from the earlier discovery method.

## Regression gates (run in CI with synthetic data)

These run on every push via `pytest`:

- `tests/test_geography.py`:
  - a state-wide destination keeps only in-area stops;
  - a category with only far-away places explains itself with counts;
  - a destination with everything out of area fails honestly;
  - impossible coordinates are rejected;
  - every returned place is accounted for in the drop reasons.
- `scripts/failure_drill.py`: 9 failure scenarios (rate limits, timeouts, bad key, unknown interest, empty
  city, partial outage, missing coordinates, invented LLM numbers).
- `scripts/evaluate.py` exits non-zero if any arm fails grounding or a persona errors.
