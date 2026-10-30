"""Taste Bridge Agent.

Finds places OUTSIDE the categories the user picked that Qloo still rates as a strong match for
their taste, and that sit a short walk or transit hop from a stop already in the plan. The aim is to
make a low-effort, low-impact addition discoverable, not to add novelty for its own sake.

A bridge needs all three:
  - taste:       Qloo affinity at least the plan's median affinity minus BRIDGE_AFFINITY_SLACK
  - feasibility: within MAX_HOP_KM (straight line) of a planned stop, and passes verification
  - evidence:    the hop from that stop is computed (walk, or bus via EPA factors) and compared
                 with making a separate car round trip from the start point
One extra Qloo call per run.
"""

from __future__ import annotations

from statistics import median

from ..evidence.emissions import car_vs_lowest, leg_estimate, trip_estimates
from ..evidence.geo import haversine_km
from ..models import RunRequest
from ..qloo.client import CallStats, QlooClient
from ..qloo.taxonomy import CATEGORIES, classify, has_step_free_tag, low_impact_signals
from . import verification
from .discovery import Candidate, _drop_reason

BRIDGE_AFFINITY_SLACK = 0.05
MAX_BRIDGES = 3
MAX_HOP_KM = 4.0  # straight line from the nearest planned stop: a walk (≤2.5 km) or one short transit hop


def bridge_categories(req: RunRequest) -> list[str]:
    return [k for k in CATEGORIES if k not in req.categories and k != "stay"]


async def find_bridges(client: QlooClient, req: RunRequest, *, seed_ids: list[str], seed_tags: list[str],
                       planned: list[Candidate], origin: dict | None, stats: CallStats) -> dict:
    keys = bridge_categories(req)
    anchors = [c for c in planned if c.place.lat is not None and c.place.lon is not None]
    affs = [c.place.affinity for c in planned if c.place.affinity is not None]
    if not keys or not anchors or not affs:
        return {"bridges": [], "considered": 0, "reason": "Nothing to bridge from"}
    floor = round(median(affs) - BRIDGE_AFFINITY_SLACK, 3)
    tags = [t for k in keys for t in CATEGORIES[k].tags]
    places, _ = await client.place_insights(location_query=req.location, seed_ids=seed_ids, seed_tags=seed_tags,
                                            tags=tags, price_max=req.budget, take=25, stats=stats)
    planned_ids = {c.id for c in planned}
    out, used_cats, considered = [], set(), 0
    for p in sorted(places, key=lambda p: p.affinity or 0, reverse=True):
        if p.entity_id in planned_ids or p.lat is None or p.lon is None or (p.affinity or 0) < floor:
            continue
        cat = classify(p, keys)
        if not cat or cat in used_cats or _drop_reason(p, req):
            continue
        considered += 1
        near = min(anchors, key=lambda a: haversine_km(a.place.lat, a.place.lon, p.lat, p.lon))
        hop_km = round(haversine_km(near.place.lat, near.place.lon, p.lat, p.lon), 2)
        if hop_km > MAX_HOP_KM:
            continue
        c = Candidate(place=p, category=cat, step_free=has_step_free_tag(p), signals=low_impact_signals(p))
        if origin:
            c.distance_km = round(haversine_km(origin["lat"], origin["lon"], p.lat, p.lon), 2)
            c.trip = trip_estimates(c.distance_km, car_occupants=req.travelers, car_free=req.car_free)
        c.score_parts = {"base": round(p.affinity or 0, 3)}
        c.score = c.score_parts["base"]
        checks = verification.check(c, req, "qloo")
        if not verification.passes(checks):
            continue
        car_rt = car_vs_lowest(c.trip)[0] if c.trip else None
        out.append({"candidate": c, "checks": checks, "near_id": near.id, "near_name": near.place.name,
                    "hop": leg_estimate(hop_km, req.travelers, req.car_free), "affinity_floor": floor,
                    "separate_trip_car_kg": car_rt})
        used_cats.add(cat)
        if len(out) >= MAX_BRIDGES:
            break
    return {"bridges": out, "considered": considered, "affinity_floor": floor,
            "categories": [CATEGORIES[k].label for k in keys]}
