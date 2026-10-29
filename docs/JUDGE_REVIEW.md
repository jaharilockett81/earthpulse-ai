# Self-review through each judging lens

Our own critique, not official scores.

## Technological implementation
- **Strengths:** Qloo used at six points (search, tags, tag insights, place insights with signals, explainability,
  a second place call for Taste Bridge). Bounded, deterministic pipeline; throttle, cache, retries, typed errors.
  43 automated tests incl. auth/timeout/rate-limit/secret-leak cases. Built-in ablation.
- **Weaknesses:** live Qloo not yet exercised in this build environment; in-memory cache and rate limits.
- **Fixes done:** persona evaluation harness; timeout and secret-leak tests. **Remaining:** run live smoke test and
  evaluation once the key is set; fix any schema surprises.

## Design
- **Strengths:** cohesive palette and type, live timeline, evidence drawer, map, Cultural DNA bars, mobile layout
  checked at 390 px with no horizontal scroll, keyboard support, reduced-motion support.
- **Weaknesses:** images depend on Qloo providing them; placeholders otherwise.
- **Fixes done:** compact timeline on mobile, explicit loading/empty/error states.

## Potential impact
- **Strengths:** a named user (eco-minded city-breakers), concrete actions (swaps, bridges, walking legs), computed
  savings with sources.
- **Weaknesses:** U.S. EPA factors applied worldwide; straight-line distances.
- **Fixes:** stated on every evidence panel; roadmap includes routing and local factors.

## Quality of the idea
- **Strengths:** Taste Bridge (outside your categories, still your taste, a short hop away, with evidence), blind
  Qloo-vs-baseline lab, claim labels. Distinct from 2025 winners (see STRATEGY.md).
- **Weaknesses:** the evaluation needs live numbers to be persuasive.
