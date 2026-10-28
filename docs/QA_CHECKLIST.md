# QA checklist (run against the live Render URL before submitting)

## Required by the hackathon
- [ ] Live demo URL loads without login
- [ ] Public GitHub repo with a detected MIT license (GitHub shows “MIT license” in the sidebar)
- [ ] Devpost text pasted from `docs/DEVPOST.md`, live URL and repo URL filled in
- [ ] README “Live demo” link updated

## Function
- [ ] `/api/health` shows `qloo_configured: true`, `fixtures: false`
- [ ] `python scripts/smoke.py <url>` prints OK
- [ ] Autocomplete returns results for “Amélie”, “Radiohead”, “Murakami”
- [ ] Each landing example runs to a full plan
- [ ] Free-text “Describe it” mode works
- [ ] Starting point (e.g. “Alfama”) changes the distances; an unknown one shows a note
- [ ] 1-day and 2-day plans; budget $; step-free; car-free (no car figures shown)
- [ ] Evidence drawer: claims, explainability table, score breakdown, EPA table, checks, Esc closes it
- [ ] Comparison lab: rate both, reveal, tally updates
- [ ] A nonsense city or interest shows a clear error, not a blank page

## Design / accessibility
- [ ] Phone width (390 px): no horizontal scroll, timeline compact, cards readable
- [ ] Keyboard only: tab through planner, autocomplete arrows/Enter, drawer focus and Esc
- [ ] Map shows numbered stops and the start point

## Screenshots for Devpost (1360×900 desktop, 390 wide mobile)
1. Landing hero
2. Planner with three favourites picked
3. Results: live agent timeline mid-run
4. Results: stats row, taste portrait and map
5. A stop card with a lighter swap
6. Evidence drawer (claims + EPA table)
7. Comparison lab after reveal
8. Mobile results view
