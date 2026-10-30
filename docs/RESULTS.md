# Results: what works, what was tested, what is not done

Last updated Oct 30, 2026 (UTC). Every number here comes from a command you can re-run or a request to the live
deployment. Nothing is extrapolated.

## Status at a glance

| Item | Status |
|---|---|
| Public demo | **Live:** https://earthpulse-ai-plos.onrender.com (Render free plan). `/api/health` reports `qloo_configured: true` and `fixtures: false`. |
| Public repo with MIT license | **Live:** https://github.com/jaharilockett81/earthpulse-ai |
| **Live Qloo integration** | **Verified on the deployment.** Search, tag search, tag insights, and place insights (with signals, explainability, `filter.location.query` and `filter.location` POINT + radius) all return real data. Typical run: 12–15 Qloo calls. |
| Agentic pipeline (10 stages) | Verified live: all stages complete for 5 personas in 5 cities |
| Geographic validation | States and countries refused before any Qloo call; Qloo queried around the validated city point (see the live West Palm Beach run below) |
| Three-arm ablation (Qloo, keyword, footprint-only) | Live numbers in [EVALUATION.md](EVALUATION.md) |
| Grounding validation (8 checks incl. geography) | Runs on every result before display; passed on every live run above |
| CI | GitHub Actions runs the test suite on every push |

## Bugs found on live data and fixed

| Symptom (live) | Root cause (evidence) | Fix |
|---|---|---|
| "Oregon" plan with 8 stops and 1,924 km of straight-line travel | Qloo treats "Oregon" as the whole state. Nothing bounded how far a stop could be from the start, so stops spread across the state. After the gate, a live run showed every Oregon place more than 25 km from Qloo's Oregon point. | `DISCOVERY_RADIUS_KM` (default 25) gate. Places further away, or with impossible coordinates, are dropped and counted. A new `geography` grounding check fails any place beyond the radius or leg over 2× radius. If nothing is in the area, the run fails with "try a specific city". |
| "Florida" plan: about 100 candidates rejected, 1 stop over 2 days, 36.1 km | A state is not a city. Qloo resolved "Florida" to a statewide area and the plan was measured from Qloo's point for the state, so one stop out-and-back was 36.1 km. The geocoder also maps "Florida" to Floridablanca, Colombia, so a name match alone can't be trusted. | A destination stage runs before any Qloo call. It refuses states and countries and offers city choices. A geocoder hit is accepted only if it is a populated place whose name matches. Qloo is then queried around the city point with a radius (`filter.location`), not by the state name. Partial plans are labelled "X of Y stops" with counts and opt-in fixes (40 or 60 km radius, 1-day plan). Every leg names its from and to. |
| "Copenhagen" returned 1 restaurant, 0 museums or cafés | Qloo's `filter.location.query=Copenhagen` resolved to a much smaller namesake town; `København` returned full results | First fixed by a retry around the geocoded point (live: 1 → 53 places). Now superseded: every run queries Qloo around the validated city point. |
| "Kinfolk magazine" became "InStyle Magazine" | The only shared word, "magazine", pushed string similarity to 0.75 | A match must share a distinctive (non-generic) word unless similarity is at least 0.85. Live: now "Not matched in Qloo". |
| "botanical gardens" matched "Botanical Gardens of Peter the Great" | Substring match regardless of length | Substring counts only if it covers at least 60% of the other name. Lowercase concepts try Qloo tags first. |
| Kyoto distances about 10 km for central places | Qloo's Kyoto locality point is an administrative centroid in the mountains | Start from the geocoded city centre when it is within 60 km of Qloo's locality |
| Every place "lower-impact" | Area-level tags such as "Walkable" counted as a place signal | Narrowed the signal list to the place's own offering |
| Empty category with no explanation | "No museums & culture passed the filters" did not say why | Each category records returned, kept and dropped counts with reasons (out of area, other category, duplicate, closed, budget, step-free). Notes quote those counts. A test checks every returned place is accounted for. |

## Live West Palm Beach, FL check (Oct 30, 08:55 UTC)

Request: "Lana Del Rey, vintage film", 2 days, parks, museums, cafés and restaurants. Both interests were
matched in Qloo.

- **25 km (default):** 7 of 8 stops, labelled partial.
  - Qloo returned 62 places around the city point and 58 fit; 4 were duplicates.
  - Museums & culture had only 2 places, one of them a duplicate.
  - Every leg names its ends and starts from "West Palm Beach city centre".
  - 45.7 km straight-line, 1.76 kg CO2e vs. 8.48 kg by car. Grounding 8/8.
- **40 km (the offered option):** 8 of 8 stops, complete.
  - Farthest stop 13.8 km from the centre.
  - 55.1 km straight-line, 2.11 kg vs. 10.23 kg by car. Grounding 8/8.
- **"Florida":** refused with city choices before any Qloo call.

## Automated tests (mocked Qloo, no key)

`python -m pytest -q` → **68 passed** (Oct 30). This includes:

- `tests/test_geography.py`:
  - "Florida", "Oregon" and "Florida, USA" ask for a city before any Qloo call; the geocoder's "Floridablanca" for "Florida" is never used;
  - a one-stop, two-day plan is labelled partial, its legs name both ends, and day 2 has no travel;
  - spread-out Qloo results keep only in-area stops (the Oregon regression);
  - a West Palm Beach run where every museum is out of area explains itself;
  - a destination with everything out of area fails honestly;
  - impossible or swapped coordinates are rejected and unknown coordinates are kept as Not verified;
  - grounding catches a far place;
  - every returned place is accounted for.
- `tests/test_api.py`:
  - discovery constrained to the validated city point and radius;
  - the three-arm compare;
  - the city-centre origin;
  - secrets never leak;
  - timeouts, rate limits, constraint change and re-plan.
- `tests/test_grounding.py`: tampering with provenance, interests, affinity, AI numbers, CO2e and constraints.
- `tests/test_units.py` and `tests/test_client.py`: parsers, ranking, swaps, seed matching, client retries.

## Failure drill

`python scripts/failure_drill.py` → **9/9 pass** ([FAILURE_DRILL.md](FAILURE_DRILL.md)). It covers:

- persistent 429, and a single 429 followed by recovery;
- timeout;
- bad key;
- unknown interest;
- empty city;
- one category's call failing;
- missing coordinates;
- an LLM that invents ratings and prices (all refused).

## Evaluation

See [EVALUATION.md](EVALUATION.md): five personas, three arms, live Qloo.

- Qloo lists share on average 0.8 of 6 places with the keyword list and 1.0 with the footprint-only list.
- Average planned straight-line travel was 14.1 km for Qloo, 17.5 km for keyword and 14.7 km for
  footprint-only.
- Where Qloo did not win is reported too.

No significance testing; cultural relevance needs human ratings, which have not been collected.

## Not done, and why

| Missing | Why | Blocks submission? |
|---|---|---|
| Real route distances (walking/transit network) | No authorised routing API in scope. Distances are labelled straight-line everywhere. | No |
| Opening-hours verification | Qloo hours are not reliably present; we never claim a place is open at a given time | No |
| Human relevance ratings | Needs real users; the lab collects them per browser | No |
| Certifications / destination policies | No verifiable, licensable source found in time | No |
| Demo video and screenshots | Owner records them (the build environment cannot open the live site in a browser) | Video optional per rules |

## Human approval

EarthPulse takes no consequential actions: it books nothing, pays nothing and sends nothing. AI output is never
executed; it can only reword facts, and it passes the grounding check first.
