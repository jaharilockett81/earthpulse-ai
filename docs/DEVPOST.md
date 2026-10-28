# Devpost submission text

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

A **comparison lab** runs the same request twice, once ranked by Qloo's taste graph and once by plain keyword
matching over the very same place directory, and asks you to rate both lists blind before revealing which is which.

## How we built it
FastAPI backend and a no-build HTML/CSS/JS frontend on Render. A deterministic eight-stage agent pipeline
(understand → match → portrait → discover → evidence → plan → verify → explain) streams its progress live to the page
over NDJSON. Qloo powers five of the stages: `/search` and `/v2/tags` resolve interests, tag insights build a taste
portrait, place insights with taste signals and explainability find and rank places, and the explainability scores
power the “why”. The Qloo client is throttled under 5 req/s, cached for 24 h and retries 429s and 5xx. An optional
LLM only parses free text and rewords facts; it never adds places or numbers.

## Challenges we ran into
- `filter.tags` behaves as a soft union, so banks and schools leak into results. We re-classify every place from its
  own tags and drop non-experiences.
- Only about a third of places list a price, so we show “Price not listed” instead of guessing.
- Making sustainability claims honest: distances are straight-line lower bounds, transit routes aren't verified, and
  tags like “vegan options” are taste signals, not certifications. The UI says exactly that.

## Accomplishments that we're proud of
- An ablation built into the product that shows what Qloo's taste graph adds.
- Every number on screen traces back to a source or formula in the evidence drawer.
- Lighter swaps: a concrete, low-effort way to cut travel emissions without giving up taste.

## What we learned
Cross-domain taste is a strong signal for places: a film and an album say a lot about which café you'll love.
And sustainability features land better as better options than as warnings.

## What's next
Real routing distances, local transit factors outside the U.S., group taste blending for friends travelling together,
and saving plans to share.

## Built with
Qloo Taste AI (Hackathon API), Python, FastAPI, httpx, Pydantic, Leaflet, OpenStreetMap, Open-Meteo geocoding,
U.S. EPA GHG Emission Factors Hub, Render, Anthropic API (optional).
