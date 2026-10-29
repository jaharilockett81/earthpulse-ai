# Strategy: competitive position, gap analysis, architecture decision

## 2025 winners and notable entries (from their public Devpost pages)

Only what those pages state. None of them names benchmark methodology, so none is assumed.

| Project | Core user problem | Qloo integration (as described) | Differentiator | Possible weaknesses | EarthPulse's distinct position |
|---|---|---|---|---|---|
| **GeoTaste** (Grand Prize) | Turning location data into business insight without weeks of market research | “Powered by Qloo's global business database”; endpoints not named | Map + 13+ chart types + OpenAI consulting chat | Business-only audience; insights are LLM-written with no stated evidence trail | Consumer travel; every number traced to Qloo or EPA, labelled on screen |
| **Alloy** (honourable mention) | Cultural mismatch in M&A due diligence | `/search` to find entity IDs for “cultural proxies”, Taste AI for audience/brand profiles; Persona API unavailable, web-search fallback | ReAct agent (Gemini) producing compatibility scores and reports | Scores have no described validation; speed/cost claims without methodology | Deterministic pipeline with a built-in ablation that measures what Qloo adds |
| **Resonance AI** | Political campaign messaging that ignores culture | Qloo for music/entertainment/brand affinities via a Python wrapper | Generated multi-channel campaign packages | Streamlit/ADK UI; no custom frontend; validation limited by data | Custom, accessible consumer UI; outputs are real places, not generated copy |
| **Zesty** | Taste bubbles; recommendations that are all the same | Fetches content “at the farthest point” from user taste; endpoints not named | Unrecommendation engine, “Taste Nemesis” | No reported accuracy or user testing; “opposite” can feel random | **Taste Bridge** stretches you outside your usual categories but stays a strong taste match and a short walk away, with evidence |

**Takeaways we used:** winners turned Qloo into a decision, not a list (GeoTaste, Alloy); a specific audience beats “everyone”; and a visible, polished UI matters. **Where they were thin:** evidence for claims, and proof that Qloo, not the LLM, was doing the work. EarthPulse leans into both.

## Gap analysis against the brief (as of Oct 29)

| Requirement | Status |
|---|---|
| Working agentic app using Qloo | Built; deterministic 9-stage pipeline with real tool calls. **Live Qloo not yet exercised (no key in this environment).** |
| Public demo | **Blocked on Jahari:** Render deploy + `QLOO_API_KEY` |
| Public repo + license | MIT license ready. **Blocked on Jahari:** creating the GitHub repo |
| Setup instructions, description | README, METHODOLOGY, DEVPOST drafted |
| Cultural DNA, Decision Studio, evidence inspector, comparison lab, agent activity | Built |
| Revise plan when a constraint changes | Built (adjust panel + “what changed”) |
| Reproducible persona evaluation | Harness built (`scripts/evaluate.py`); **live results pending key** |
| Taste Bridge | Built |
| Official certifications / destination policies as evidence | Not built: no verifiable, licensable source found in time. Unverified things are labelled “Not verified”. |
| Demo video | Optional per rules; script in `docs/DEMO_SCRIPT.md` |

## Architecture decision: keep FastAPI + no-build frontend (no Next.js migration)

The uploaded project was already FastAPI with a static frontend, not Streamlit, so the brief's migration condition
doesn't apply. A Next.js rewrite with a day left would trade working, tested code for setup risk, add a second
deploy target, and not change what judges see. The static frontend already streams live agent events, is responsive,
and has keyboard support. We revisit this after the hackathon if the product needs accounts or saved plans.

## Who would use this after the hackathon (hypotheses, no traction claimed)

- **Primary user:** environmentally conscious city-breakers (weekend trips, often by rail) who care about taste and
  aesthetics and don't want “eco” to mean “generic”. Their problem: planning tools optimise for preference *or* for
  impact, and the trade-off is invisible.
- **Why EarthPulse could be better:** taste-matched real places, explained; the cheapest carbon win shown at the
  moment of choice (lighter swaps, Taste Bridge); evidence the user can check.
- **Possible business models to test:** premium trip planning; destination discovery licensing for tourism boards
  promoting car-free neighbourhoods; a B2B “taste + footprint” API for sustainable hotels to recommend nearby
  experiences. All unvalidated.
- **Moat to build:** a growing set of blind A/B ratings (consented, aggregated) showing where taste signals help,
  plus better evidence data (routing, local transit factors, certifications).
