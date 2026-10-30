# Repository audit (Oct 30, 2026)

## Implemented and tested (mocked Qloo)
Taste matching (search → tags fallback), taste portrait, per-category place discovery with taste signals and
explainability, bounded adaptation for thin categories, EPA-based evidence, scoring with documented weights, day
plans with legs, lighter swaps, verification with replacement, grounded explanations (optional validated LLM),
Taste Bridge, grounding check, blind Qloo-vs-baseline lab with metrics, adjust-and-regenerate with a diff, persona
evaluation harness, failure drill, NDJSON live timeline, responsive UI, per-IP rate limits, CI workflow.

## Simulated / not verified
- All Qloo traffic so far is mocked or synthetic (`app/qloo/fixtures.py`, names start with “[Synthetic]”).
- No live evaluation numbers exist.

## Eligibility gaps
| Requirement | Gap |
|---|---|
| Working app using Qloo | Live Qloo unverified (no key in build env) |
| Public functional demo | Not deployed |
| Public repo + license | Repo not created (license ready) |
| Description | Drafted in DEVPOST.md; needs live URL + repo URL |

## Risks
1. **Live schema drift** (highest): field names come from the hackathon guide and other entrants' probes. Parsers are
   tolerant and tests cover variants, but only a live run proves it. Mitigation: smoke test immediately after deploy.
2. **Render free-tier cold start** (~1 min): warm the URL before judging windows; note it in the README.
3. **Qloo quota/rate limits**: ~15–20 calls per run, 24 h cache, 4 req/s throttle, 20 runs/hour/IP.
4. **Thin cities**: some categories may return few places; adaptation + notes handle it honestly.

## Priorities
- **P0 (required):** repo, deploy, key, live smoke test, fix any schema issues, Devpost text with URLs.
- **P1 (high value):** live persona evaluation into EVALUATION.md, real screenshots, README live link.
- **P2 (optional):** demo video, certification data, routing distances.
