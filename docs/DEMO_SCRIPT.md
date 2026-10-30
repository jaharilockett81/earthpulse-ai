# Demo script (90–120 s)

Record against the **live Render URL with the real Qloo key**, never in synthetic mode. Warm the server first (open
`/api/health`), and do one throwaway run of the demo request so Qloo responses are cached and the take is smooth.
Say that it's cached if asked; don't hide it.

| Time | Screen | Say |
|---|---|---|
| 0–15 s | Landing page | “Most recommendation platforms understand what we like. Few help us connect those interests to more sustainable decisions. EarthPulse does both.” |
| 15–35 s | Planner: type *Studio Ghibli*, pick it from Qloo autocomplete; add *botanical gardens* (becomes a Qloo taste tag), *independent coffee*; city Kyoto | “These are real Qloo entities and tags. Qloo connects taste across film, music, books and places.” |
| 35–65 s | Build my plan: watch the agent timeline; land on “Your culture-inspired weekend is ready.” Point at Cultural DNA, then a stop card | “Each step is a real backend event: matching, taste portrait, one Qloo place call per category, evidence, planning, verification. Here's which of my interests drove the plan, from Qloo's explainability.” |
| 65–85 s | Open “Evidence & sources” on a card; then a lighter swap or the Taste Bridge | “Every claim is labelled. CO2e comes from EPA emission factors, with the formula and limits right here. Distances are straight-line lower bounds, and opening hours aren't verified, and we say so.” |
| 85–105 s | Back to planner → Compare with and without Qloo; rate both, reveal; metrics table | “Same place directory, same rules. Only the taste signal differs. Rate blind, then reveal. Our persona evaluation is in the README.” |
| 100–105 s | Scroll to the Grounding check panel | “Before anything is shown, a deterministic check proves every place came from Qloo in this run and every number recomputes.” |
| 105–120 s | Adjust: tick “I won't drive”, regenerate, show “Plan revised” | “Change a constraint and the agent re-plans and shows what changed. EarthPulse makes sustainability personal, practical, and culturally relevant.” |

## 20-second judge explanation: why Qloo is essential

“EarthPulse ranks places by Qloo's cross-domain taste affinity: a film and an album you love decide which café you
see. Qloo's explainability tells you *which* interest drove each pick. Turn Qloo off, as the comparison lab does
with the same place directory and rules, and you get keyword matching instead. Without Qloo there is no taste
match, no Cultural DNA, no Taste Bridge, and no lighter swap, because a swap is defined as ‘nearly as good a
taste match, but closer’.”

## If something fails live
Say so. The app shows honest errors (rate limit, timeout). Retry once after a minute; otherwise show the failure
drill table as evidence of the behaviour.
