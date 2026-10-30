# Demo script (about 2 minutes)

Record against the **live Render URL with the real Qloo key**, never in synthetic mode. Warm the server first (open
`/api/health`), and do one throwaway run of the demo request so Qloo responses are cached and the take is smooth.
Say that it's cached if asked; don't hide it.

| Time | Screen | Say |
|---|---|---|
| 0–12 s | Landing page | “Cultural recommendations ignore what it costs to get there. Sustainable ones ignore who you are. EarthPulse does both.” |
| 12–30 s | Planner: type *Studio Ghibli*, pick it from Qloo autocomplete; add *Japanese architecture*, *botanical gardens*; city Kyoto | “These are real Qloo entities and taste tags. Qloo connects taste across film, music, books and places.” |
| 30–55 s | Build my plan: watch the agent timeline; land on the plan. Point at Cultural DNA, then a stop card | “Each step is a real backend event: one Qloo place call per category, a 25 km area check, evidence, planning, verification. Here's which of my interests drove each pick, from Qloo's explainability.” |
| 55–75 s | Open “Evidence & sources” on a card; then a 🌿 Lighter swap block | “Every claim is labelled. CO2e comes from EPA factors, compared with the same trip by car. The lighter swap keeps most of the taste match and cuts the trip. Distances are straight-line lower bounds, and we say so.” |
| 75–90 s | Adjust and regenerate: drag the slider to “Lighter footprint”, regenerate, show “Plan revised” | “You choose the trade-off. Constraints never bend; only how much distance counts.” |
| 90–108 s | Compare with and without Qloo; rate both, reveal; three-column metrics | “Same place directory and rules. Keyword ranking and a footprint-only ranking pick almost entirely different places. Across five live personas Qloo's plans were also shorter on average, and we publish where it lost.” |
| 108–120 s | Planner: type a whole state, “Oregon”, and run | “And it refuses to fake it: a whole state can't be a walking day, so it asks for a city instead of a 1,900 km itinerary.” |

## 20-second judge explanation: why Qloo is essential

“EarthPulse ranks places by Qloo's cross-domain taste affinity: a film and an album you love decide which café you
see. Qloo's explainability tells you *which* interest drove each pick. Turn Qloo off, as the comparison lab does
with the same place directory and rules, and you get keyword matching instead. Without Qloo there is no taste
match, no Cultural DNA, no Taste Bridge, and no lighter swap, because a swap is defined as ‘nearly as good a
taste match, but closer’.”

## If something fails live
Say so. The app shows honest errors (rate limit, timeout). Retry once after a minute; otherwise show the failure
drill table as evidence of the behaviour.
