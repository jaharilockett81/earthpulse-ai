# Judging criteria → evidence

Each row points to code you can read, a test or script you can run, and what to look at in the live demo
(https://earthpulse-ai-plos.onrender.com).

## A. Technological implementation

| Claim | Code | Test / script | Demo evidence |
|---|---|---|---|
| Qloo used at 6 points: search, tags, tag insights, place insights with signals, explainability, Taste Bridge | `app/qloo/client.py`, `app/agents/taste.py`, `discovery.py`, `bridge.py` | `tests/test_client.py`, `tests/test_api.py` | The agent timeline shows the Qloo call count; each card's evidence drawer shows the Qloo affinity and the interests credited by explainability |
| City-level destination, discovery constrained at the source | `app/evidence/destination.py`, `app/agents/discovery.py` | `tests/test_geography.py` (state-only, geocoder mismatch, one-stop plan), `tests/test_api.py::test_discovery_is_constrained_around_the_validated_city` | Try “Florida”: city choices appear before any Qloo call; the timeline's first stage shows the resolved city and radius |
| Deterministic geographic gate | `app/agents/sustainability.py::gate_by_area`, `grounding.py` (geography) | `tests/test_geography.py` | Try "Portland, OR": every stop within 25 km |
| Grounding validator: 8 checks, withholds on failure | `app/agents/grounding.py` | `tests/test_grounding.py` | The "Grounding check: 8 of 8 passed" panel under each plan |
| Failure handling | `app/qloo/client.py`, `app/main.py` | `scripts/failure_drill.py` (9/9) | Unknown interest → "Not matched in Qloo" note |
| No secrets exposed | `app/config.py`, `app/main.py` | `tests/test_api.py` (secret never in stream or health) | `/api/health` shows only `qloo_configured: true` |

## B. Design

| Claim | Code | Check | Demo evidence |
|---|---|---|---|
| Coherent editorial identity (forest green, ivory, serif display) | `static/styles.css` | Playwright at 1360 px and 390 px, no horizontal scroll | Landing → plan → results |
| Every number carries a claim label (Listed, Computed, Qloo signal, AI-written, Not verified) | `app/agents/explanation.py`, `static/app.js` | `tests/test_grounding.py` (labels) | Chips beside each figure |
| Lighter swap as a side-by-side comparison | `static/app.js::swapCompare` | Screenshot at 390 px | Cards with a 🌿 Lighter swap block |
| Clear empty and error states with real counts | `app/agents/orchestrator.py::empty_note` | `tests/test_geography.py` | Notes under the plan |

## C. Potential impact

| Claim | Code | Evidence |
|---|---|---|
| Transport CO2e per leg from EPA 2025 factors, compared with the same trip by car | `app/evidence/emissions.py` | `docs/METHODOLOGY.md`; the arithmetic grounding check recomputes every figure |
| Taste and footprint traded off visibly | `app/agents/planning.py` (swaps), `bridge.py` | Lighter swap and Taste Bridge panels |
| Measured, reproducible comparison | `scripts/evaluate.py --url` | `docs/EVALUATION.md`: Qloo plans averaged 14.1 km vs. 17.5 km (keyword) and 14.7 km (footprint-only) over 5 live personas; losses reported too |

## D. Quality of the idea

| Claim | Evidence |
|---|---|
| Would be meaningfully worse without Qloo | Ablation: Qloo lists share fewer than 1 of 6 places with the keyword list (`docs/EVALUATION.md`). Cross-domain inputs (a film, a brand, an author) have no keyword path to a café or park. |
| Non-obvious use of cultural intelligence | Taste Bridge: places outside your chosen categories that Qloo still rates at your plan's level, within 4 km of a stop |
| Honest by construction | Grounding validator, claim labels, `docs/RESULTS.md` lists what is not verified |
