# Devpost submission text

- **Live demo:** https://earthpulse-ai-plos.onrender.com (free tier; the first visit after idle can take about a minute)
- **Code (MIT):** https://github.com/jaharilockett81/earthpulse-ai

**Title:** EarthPulse AI — Your taste. A lighter footprint.

**One-liner:** A Qloo-powered planning agent that builds city days matched to your cultural taste, then shows the
travel-emissions evidence behind every pick and the lighter options you'd actually enjoy.

## Inspiration
Recommendation apps know what we like but ignore what it costs to get there. Sustainability apps know the cost but
feel like homework. We wanted both in one place: a plan that is unmistakably *yours*, with the climate trade-offs
made visible and easy to act on.

## What it does
Tell EarthPulse a few things you love, like *Amélie*, Studio Ghibli and “slow living”, and where you're going. It
builds a one or two day plan of cafés, parks, museums, bookshops, music venues and restaurants that people with your
taste love, and shows for every stop:

- **why it's there**, using Qloo's explainability to name which of your interests drove the match,
- **how far** it is and the **round-trip CO2e** by car, bus, rail, bike or foot, from U.S. EPA emission factors,
- a **lighter swap** when a much closer place is nearly as good a match, with the CO2e saved,
- a **claim label** on every statement: Listed, Computed, Qloo signal, AI-written or Not verified.

A **Taste Bridge** looks beyond the kinds of places you asked for and surfaces strong taste matches a short walk or
hop from your plan, with the CO2e of that hop next to a separate car trip. Change any constraint and the agent
re-plans and shows exactly what changed.

A **comparison lab** runs the same request three ways over the very same place directory: ranked by Qloo's taste
graph, by plain keyword matching, and by footprint alone. You rate the Qloo and keyword lists blind before revealing
which is which, then see measured metrics for all three.

## How we built it
FastAPI backend and a no-build HTML/CSS/JS frontend on Render. A deterministic ten-stage pipeline
(understand → match → portrait → discover → evidence → plan → verify → explain → bridge → grounding check) streams its
progress live to the page over NDJSON. Tool-using stages call Qloo and a geocoder; correctness-critical stages
(geographic gate, scoring, verification, grounding) are pure, tested functions. Qloo powers five of the stages: `/search` and `/v2/tags` resolve interests, tag insights build a taste
portrait, place insights with taste signals and explainability find and rank places, and the explainability scores
power the “why”. The Qloo client is throttled under 5 req/s, cached for 24 h and retries 429s and 5xx. An optional
LLM only parses free text and rewords facts; it never adds places or numbers.

## Testing and evaluation
63 automated tests run in CI with Qloo mocked (Qloo's terms don't allow committing its responses). They cover
parsing, auth failures, timeouts, 429s, ranking, constraints, geography, grounding tampering, secret leakage and
the evaluation harness. A failure drill breaks Qloo and the LLM nine ways on purpose; all nine fail honestly.

We then ran a three-arm ablation on the live deployment with real Qloo data, using five invented personas in
Kyoto, Chicago, Lisbon, Portland and Copenhagen:

- Qloo's six picks share on average fewer than one place with a keyword ranker over the same directory, and one
  with a footprint-only ranker. Taste changes *what* you are offered.
- Planned straight-line travel averaged 14.1 km for Qloo, 17.5 km for keyword and 14.7 km for footprint-only.
- Qloo did not win everywhere: it lost on distance in two cities, and an automatic theme-match proxy did not
  favour it.

Five personas is a small sample, so we claim no significance; the full table is in `docs/EVALUATION.md`.

## Challenges we ran into
- `filter.tags` behaves as a soft union, so banks and schools leak into results. We re-classify every place from its
  own tags and drop non-experiences.
- Only about a third of places list a price, so we show “Price not listed” instead of guessing.
- Making sustainability claims honest: distances are straight-line lower bounds, transit routes aren't verified, and
  tags like “vegan options” are taste signals, not certifications. The UI says exactly that.
- Real data surprised us. “Oregon” meant the whole state, which produced a 1,900 km “day plan”. “Copenhagen”
  matched a far smaller namesake town. “Kinfolk magazine” matched “InStyle Magazine”. Each became a deterministic
  check:
  - a 25 km geographic gate plus a grounding check on every leg;
  - a retry around the geocoded city, disclosed to the user;
  - stricter entity matching that says “not matched” instead of guessing.

## Accomplishments that we're proud of
- An ablation built into the product that shows what Qloo's taste graph adds.
- Every number on screen traces back to a source or formula in the evidence drawer.
- Lighter swaps: a concrete, low-effort way to cut travel emissions without giving up taste.

## What we learned
Cross-domain taste is a strong signal for places: a film and an album say a lot about which café you'll love.
And sustainability features land better as better options than as warnings.

## Known limitations
Straight-line distances (figures are lower bounds); U.S. EPA factors used everywhere; no certification data yet;
opening hours not verified; in-memory cache.

## What's next
Real routing distances, local transit factors outside the U.S., group taste blending for friends travelling together,
and saving plans to share.

## Built with
Qloo Taste AI (Hackathon API), Python, FastAPI, httpx, Pydantic, Leaflet, OpenStreetMap, Open-Meteo geocoding,
U.S. EPA GHG Emission Factors Hub, Render, Anthropic API (optional).
