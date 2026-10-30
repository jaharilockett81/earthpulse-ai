# Results: what works, what was tested, what is not done

Last updated Oct 30, 2026. Every number here comes from a command you can re-run. Nothing is extrapolated.

## Status at a glance

| Item | Status |
|---|---|
| Agentic pipeline (10 stages incl. Taste Bridge and grounding) | Implemented, tested with mocked Qloo |
| **Live Qloo integration** | **Not yet verified.** No Qloo key was available in the build environment. The client follows the hackathon API schema; it must be verified on the deployed server. |
| Public demo (Render) | **Not deployed yet.** Needs the repo + `QLOO_API_KEY` set by the owner. |
| Public repo with MIT license | License file ready; **repo not created yet** |
| Baseline comparison (in-app lab + persona script) | Implemented; **live numbers pending the key** |
| Failure drill | Implemented; 9/9 scenarios pass (mocked Qloo) |
| Grounding validation | Implemented; runs on every result before display |

## Automated tests (mocked Qloo, no key)

`python -m pytest -q` → **50 passed** (Oct 30). Coverage by area:

| Area | Tests |
|---|---|
| Qloo response parsing (tolerant, malformed records, nested/bare lists, explainability) | `test_units.py` |
| Auth failure (401/403), timeouts, 429 retry and persistent 429, 5xx, missing key | `test_client.py`, `test_api.py`, failure drill |
| Ranking weights, distance penalty, boosts, lighter swap | `test_units.py` |
| Constraint filtering (budget, step-free, car-free, categories) and constraint change → re-plan | `test_api.py`, `test_grounding.py` |
| Missing sustainability evidence (no coordinates → Not verified) | failure drill |
| Orchestration: every stage emitted in order, result shape | `test_api.py` |
| Baseline: sends no taste signal, keyword base, blind A/B | `test_api.py`, `test_units.py` |
| Grounding: provenance, invented interests/affinity, AI number repair, tampered CO2e, constraint breach | `test_grounding.py` |
| Bounded adaptation: thin category re-queried exactly once (20 → 50) | `test_grounding.py` |
| Input validation, secret never in stream or health, rate limiting, static app served | `test_api.py` |

## End-to-end (local server, synthetic fixtures)

`EARTHPULSE_DEV_FIXTURES=1 uvicorn app.main:app` then `python scripts/smoke.py` → **OK**: health, autocomplete,
a full streamed run and a comparison. Browser check with Playwright at 1360 px and 390 px: no console errors, no
horizontal scroll. This proves the app wiring, **not** Qloo's data quality.

## Failure drill

See [FAILURE_DRILL.md](FAILURE_DRILL.md) (`python scripts/failure_drill.py`). 9/9 pass: persistent 429, single 429
then recovery, timeout, bad key, unknown interest, empty city, one category's Qloo call failing (plan still built
and the outage is noted), missing coordinates, and an LLM that invents ratings and prices (all 8 sentences refused).

## Baseline comparison

The persona harness (`scripts/evaluate.py`) has only been run on synthetic data, which says nothing about Qloo.
**No Qloo-vs-baseline result is claimed.** To produce one:

```bash
QLOO_API_KEY=... python scripts/evaluate.py --out docs/EVALUATION.md
```

It writes aggregate metrics only (overlap, theme match, keyword match, diversity, distance, evidence coverage,
latency) for five invented personas, with no place names, per Qloo's terms. If Qloo does not beat the baseline on
some persona, that row is reported as is.

## Not done, and why

| Missing | Why | How to finish | Blocks submission? |
|---|---|---|---|
| Public repo | The build session can't create GitHub repos | Owner creates `earthpulse-ai`; we push | **Yes** |
| Deployed demo | Needs the repo and a Render account | Render → New → Blueprint | **Yes** |
| Live Qloo verification | No key in the build environment | Set `QLOO_API_KEY` on Render; run `scripts/smoke.py <url>` | **Yes** (rules require real Qloo use) |
| Live evaluation numbers | Same | `scripts/evaluate.py` with the key | No, but strongly recommended |
| Certifications / destination policies | No verifiable, usable source found in time | Future work | No |
| Demo video | Optional under the rules | Script in DEMO_SCRIPT.md | No |

## Human approval

EarthPulse takes no consequential actions: it books nothing, pays nothing and sends nothing. AI output is never
executed; it can only reword facts, and it passes the grounding check first. The only “actions” are the user's own
choices to regenerate or open a link.
