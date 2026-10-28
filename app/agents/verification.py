"""Verification Agent.

Re-checks every planned stop against the place's own Qloo data and recomputes every number
before anything is shown. A stop that fails a hard check is replaced by the next ranked
alternate in the same category (which must itself pass); the replacement is reported.
"""

from __future__ import annotations

from ..evidence.emissions import trip_estimates
from ..models import RunRequest
from ..qloo.taxonomy import classify, has_step_free_tag, is_blocked
from .discovery import Candidate


def check(c: Candidate, req: RunRequest, mode: str) -> list[dict]:
    p = c.place
    out = [
        {"id": "category", "hard": True, "passed": classify(p, [c.category]) == c.category,
         "detail": "Category confirmed from the place's own Qloo tags."},
        {"id": "experience", "hard": True, "passed": not is_blocked(p),
         "detail": "Not a bank, school, clinic or similar non-experience."},
        {"id": "open", "hard": True, "passed": p.is_closed is not True,
         "detail": "Qloo does not list it as closed." if p.is_closed is False else
                   "Not marked closed by Qloo (opening hours not verified)."},
    ]
    if req.budget:
        ok = p.price_level is None or p.price_level <= req.budget
        out.append({"id": "budget", "hard": True, "passed": ok,
                    "detail": "Price not listed — budget not verified." if p.price_level is None else
                              f"Listed price level {p.price_level} within budget {req.budget}."})
    if req.step_free:
        out.append({"id": "step_free", "hard": True, "passed": has_step_free_tag(p),
                    "detail": "Qloo lists a wheelchair-accessible entrance."})
    if c.distance_km is not None:
        same = c.trip == trip_estimates(c.distance_km, car_occupants=req.travelers, car_free=req.car_free)
        out.append({"id": "emissions_recomputed", "hard": True, "passed": same,
                    "detail": "CO2e figures recomputed independently from EPA factors."})
    else:
        out.append({"id": "coordinates", "hard": False, "passed": False,
                    "detail": "No coordinates — distance and emissions not verified."})
    if mode == "qloo":
        out.append({"id": "taste_link", "hard": False, "passed": p.affinity is not None,
                    "detail": "Qloo returned an affinity score for your taste." if p.affinity is not None
                              else "No affinity score returned."})
    return out


def passes(checks: list[dict]) -> bool:
    return all(ch["passed"] for ch in checks if ch["hard"])


def verify(req: RunRequest, plan: dict, mode: str) -> dict:
    ranked: dict[str, list[Candidate]] = plan["ranked"]
    chosen: dict[str, list[Candidate]] = plan["chosen"]
    used = {c.id for lst in chosen.values() for c in lst}
    results: dict[str, list[dict]] = {}
    replaced = []
    for key, lst in chosen.items():
        fixed = []
        for c in lst:
            chk = check(c, req, mode)
            if passes(chk):
                results[c.id] = chk
                fixed.append(c)
                continue
            sub = None
            for alt in ranked.get(key, []):
                if alt.id in used:
                    continue
                alt_chk = check(alt, req, mode)
                if passes(alt_chk):
                    sub = alt
                    results[alt.id] = alt_chk
                    break
            failed = [ch["id"] for ch in chk if ch["hard"] and not ch["passed"]]
            replaced.append({"removed": c.place.name, "failed": failed, "replacement": sub.place.name if sub else None})
            if sub:
                used.add(sub.id)
                fixed.append(sub)
        chosen[key] = fixed
    ids = [c.id for lst in chosen.values() for c in lst]
    return {"checks": results, "replaced": replaced, "duplicates": len(ids) - len(set(ids)),
            "stops_checked": len(results)}
