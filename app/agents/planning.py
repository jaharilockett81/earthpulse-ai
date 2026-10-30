"""Planning Agent.

Ranks candidates and lays them out as a 1–2 day plan.

Score (all weights are here, documented in docs/METHODOLOGY.md):
    score = base
          − distance penalty × 2·balance   (when "low-carbon travel" is a priority, car-free, or balance > 0.5)
          + priority boosts       (from the place's own Qloo tags)

`base` is Qloo's affinity for the user's taste (qloo mode) or plain keyword overlap with the
user's words (baseline mode). Penalties and boosts are identical in both modes, so the
comparison lab isolates what Qloo's taste signals add.
"""

from __future__ import annotations

import re

from ..evidence.emissions import car_vs_lowest, leg_estimate
from ..evidence.geo import haversine_km
from ..models import RunRequest
from ..qloo.taxonomy import CATEGORIES
from .discovery import Candidate

DIST_FREE_KM = 1.0  # no penalty for the first km
DIST_PER_KM = 0.02  # score lost per km beyond that…
DIST_CAP = 0.25  # …up to this much
CARFREE_PER_KM, CARFREE_CAP = 0.03, 0.35
BOOST_NATURE = 0.05  # nature_time: parks & gardens
BOOST_PLANT = 0.06  # plant_forward: vegan / vegetarian / plant-based tags
BOOST_SECONDHAND = 0.06  # secondhand: thrift / vintage / used tags
SWAP_AFFINITY_GAP = 0.06  # a lighter swap may be at most this much lower in base score…
SWAP_DIST_RATIO = 0.6  # …and at most 60% of the distance…
SWAP_MIN_KM_SAVED = 1.0  # …and at least 1 km closer.
DAYPART_ORDER = {"morning": 0, "midday": 1, "afternoon": 2, "evening": 3}

_PLANT = re.compile(r"vegan|vegetarian|plant", re.I)
_SECOND = re.compile(r"thrift|vintage|second|used", re.I)


def score(c: Candidate, req: RunRequest, base: float) -> None:
    parts = {"base": round(base, 3)}
    if c.distance_km is not None and ("low_carbon_travel" in req.priorities or req.car_free or req.balance > 0.5):
        per, cap = (CARFREE_PER_KM, CARFREE_CAP) if req.car_free else (DIST_PER_KM, DIST_CAP)
        weight = 2 * req.balance  # the taste <-> footprint slider; 1.0 at the default
        pen = min(cap, max(0.0, c.distance_km - DIST_FREE_KM) * per) * weight
        if pen:
            parts["distance_penalty"] = -round(pen, 3)
    text = " ".join([*c.signals, *c.place.tag_names(), *c.place.keywords])
    if "nature_time" in req.priorities and c.category == "nature":
        parts["nature_boost"] = BOOST_NATURE
    if "plant_forward" in req.priorities and _PLANT.search(text):
        parts["plant_forward_boost"] = BOOST_PLANT
    if "secondhand" in req.priorities and _SECOND.search(text):
        parts["secondhand_boost"] = BOOST_SECONDHAND
    c.score_parts = parts
    c.score = round(sum(parts.values()), 4)


def rank(cands: list[Candidate]) -> dict[str, list[Candidate]]:
    by_cat: dict[str, list[Candidate]] = {}
    for c in cands:
        by_cat.setdefault(c.category, []).append(c)
    for lst in by_cat.values():
        lst.sort(key=lambda c: (c.score, c.place.popularity or 0), reverse=True)
    return by_cat


def picks_per_category(req: RunRequest, key: str) -> int:
    return 1 if key == "stay" else req.days


def lighter_swap(pick: Candidate, pool: list[Candidate], taken: set[str], req: RunRequest) -> dict | None:
    if pick.distance_km is None or pick.trip is None:
        return None
    best = None
    for alt in pool:
        if alt.id in taken or alt.id == pick.id or alt.distance_km is None or alt.trip is None:
            continue
        if alt.score_parts.get("base", 0) < pick.score_parts.get("base", 0) - SWAP_AFFINITY_GAP:
            continue
        if alt.distance_km > pick.distance_km * SWAP_DIST_RATIO or pick.distance_km - alt.distance_km < SWAP_MIN_KM_SAVED:
            continue
        if best is None or alt.score_parts["base"] > best.score_parts["base"]:
            best = alt
    if not best:
        return None
    pc, pl = car_vs_lowest(pick.trip)
    bc, bl = car_vs_lowest(best.trip)
    if pc is not None and bc is not None:
        mode, saved = "car", pc - bc
    else:
        mode, saved = "bus", next(m["kg_co2e"] for m in pick.trip["modes"] if m["mode"] == "bus") - \
            next(m["kg_co2e"] for m in best.trip["modes"] if m["mode"] == "bus")
    return {
        "from_id": pick.id,
        "to_id": best.id,
        "km_closer": round(pick.distance_km - best.distance_km, 2),
        "base_gap": round(pick.score_parts["base"] - best.score_parts["base"], 3),
        "kg_co2e_saved": round(saved, 2),
        "compared_mode": mode,
        "kind": "computed",
    }


def build_days(req: RunRequest, chosen: dict[str, list[Candidate]], origin: dict | None) -> list[dict]:
    days = []
    for d in range(req.days):
        stops = []
        for key, lst in chosen.items():
            if key == "stay" and d > 0:
                continue
            if d < len(lst):
                stops.append(lst[d])
        stops.sort(key=lambda c: DAYPART_ORDER[CATEGORIES[c.category].daypart])
        legs, km, low, car = [], 0.0, 0.0, 0.0
        # Every leg names both ends: start -> stops in daypart order -> back to start.
        start = {"name": origin["label"], "lat": origin["lat"], "lon": origin["lon"]} if origin else None
        points = [{"name": c.place.name, "lat": c.place.lat, "lon": c.place.lon} for c in stops]
        if start and points:
            points = [start, *points, start]
        coords_ok = all(p.get("lat") is not None and p.get("lon") is not None for p in points)
        if coords_ok and len(points) > 1:
            for a, b in zip(points, points[1:]):
                leg = leg_estimate(haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]), req.travelers, req.car_free)
                leg.update({"from": a["name"], "to": b["name"], "distance_kind": "straight_line"})
                legs.append(leg)
                km += leg["km"]
                low += leg["kg_co2e"]
                car += leg["car_kg_co2e"] or 0.0
        days.append({
            "day": d + 1,
            "stops": [{"id": c.id, "slot": CATEGORIES[c.category].daypart, "category": c.category} for c in stops],
            "legs": legs,
            "totals": {
                "km": round(km, 2),
                "suggested_kg_co2e": round(low, 2),
                "car_kg_co2e": None if req.car_free else round(car, 2),
                "kind": "computed",
                "complete": coords_ok,
            },
        })
    return days


def plan(req: RunRequest, cands: list[Candidate], origin: dict | None) -> dict:
    ranked = rank(cands)
    chosen: dict[str, list[Candidate]] = {}
    for key in req.categories:
        lst = ranked.get(key, [])
        chosen[key] = lst[: picks_per_category(req, key)]
    taken = {c.id for lst in chosen.values() for c in lst}
    alternates = {k: [c.id for c in ranked.get(k, []) if c.id not in taken][:3] for k in req.categories}
    swaps = {}
    for key, lst in chosen.items():
        for c in lst:
            s = lighter_swap(c, ranked.get(key, []), taken, req)
            if s:
                swaps[c.id] = s
    return {"ranked": ranked, "chosen": chosen, "alternates": alternates, "swaps": swaps,
            "days": build_days(req, chosen, origin)}
