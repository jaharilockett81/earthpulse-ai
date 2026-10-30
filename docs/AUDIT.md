# Repository audit (updated Oct 30, 2026)

## What each "agent" actually is

EarthPulse is a deterministic, bounded pipeline of tool-using stages. We do not call it an autonomous agent loop.

| Stage | Kind | Tools it calls | Decision it makes |
|---|---|---|---|
| Intent | Rules (optional LLM, validated) | Anthropic API (optional) | Which interests are in the text |
| Resolve | Tool-using | Qloo `/search`, `/v2/tags` | Entity vs. tag vs. "not matched"; rejects weak matches |
| Portrait | Tool-using | Qloo `/v2/insights` (tags) | Themes and ambience your interests share |
| Discovery | Tool-using, adaptive | Qloo `/v2/insights` (places), Open-Meteo | Re-queries a thin category once (take 50). Retries around the geocoded city when Qloo picked a namesake town. |
| Evidence | Pure functions | Open-Meteo (start point) | Distances, EPA CO2e, area gate (25 km) |
| Planning | Pure functions | none | Multi-objective score, day plans, lighter swaps |
| Verification | Pure functions | none | Per-stop checks, replaces failures from ranked alternates |
| Explanation | Rules (optional LLM, validated) | Anthropic API (optional) | Grounded "why" sentence |
| Taste Bridge | Tool-using | Qloo `/v2/insights` (places) | Strong matches outside your categories, within 4 km of a stop |
| Grounding | Pure functions | none | 8 checks; withholds the result on failure |

Every stage logs its name, status, duration and a detail line, and streams them to the UI. Qloo calls log the
path, status, attempt and time, never the key. Retries are bounded (3 attempts), as is adaptation (once per
category) and relocation (once per run). Nothing loops.

## Implemented and verified live

- **Qloo:** search, tags, tag insights, place insights with taste signals, explainability, location query and
  POINT + radius.
- **Geography:** area gate and the geography grounding check.
- **Plans:** EPA CO2e on every leg, lighter swaps, Taste Bridge.
- **Comparison:** three-arm compare in the Comparison Lab.
- **Diagnostics:** per-category drop reasons, `/api/check` diagnostics, CI.

## Simulated

- Tests and the failure drill use synthetic data (`app/qloo/fixtures.py`, names start with "[Synthetic]"). This is
  by design: Qloo's terms do not allow committing recorded responses.

## Eligibility

| Requirement | Status |
|---|---|
| Working app using Qloo | Met: live, verified |
| Public functional demo | Met: https://earthpulse-ai-plos.onrender.com |
| Public repo + license | Met: MIT |
| Description | `docs/DEVPOST.md` |

## Remaining risks

1. **Render free-tier cold start (~1 min).** Open the URL before judging.
2. **Qloo rate limits.** 12–22 calls per run (a compare reuses cached calls), 24 h cache, 4 req/s throttle,
   per-IP run limits.
3. **City coverage varies in Qloo.** Thin categories are explained with counts, never filled with invented places.
4. **Straight-line distances.** These are lower bounds, labelled as such.
