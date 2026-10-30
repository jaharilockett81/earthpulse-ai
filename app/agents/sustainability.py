"""Sustainability Evidence Agent.

Attaches computed, sourced travel-emissions evidence to every candidate:
  - resolves the starting point (the user's origin via geocoding, else the city centre
    Qloo resolved for the destination),
  - straight-line distance to each place,
  - round-trip CO2e per traveller by mode from EPA factors (see evidence/emissions.py),
  - lower-impact *signals* found in the place's own Qloo tags (labelled as signals, never
    as certifications).
"""

from __future__ import annotations

from ..config import Settings
from ..evidence.emissions import trip_estimates
from ..evidence.geo import GEOCODE_SOURCE, geocode, haversine_km
from ..models import RunRequest
from ..qloo.schemas import Locality
from .discovery import Candidate

MAX_ORIGIN_KM = 60  # a starting point further than this from the destination is ignored


async def resolve_origin(req: RunRequest, locality: Locality | None, settings: Settings,
                         transport=None) -> dict | None:
    if req.origin and not settings.fixtures_active:  # synthetic places have synthetic coordinates
        got = await geocode(req.origin, settings.geocode_url, transport=transport)
        far = got and locality and locality.lat is not None and locality.lon is not None and \
            haversine_km(got["lat"], got["lon"], locality.lat, locality.lon) > MAX_ORIGIN_KM
        if got and not far:
            return {**got, "kind": "geocoded", "source": GEOCODE_SOURCE}
    if locality and locality.lat is not None and locality.lon is not None:
        # Qloo's locality point can be an administrative centroid (Kyoto's sits in the northern
        # mountains), so prefer the geocoded town centre when it agrees with Qloo's locality.
        if not settings.fixtures_active:
            town = await geocode(req.location, settings.geocode_url, transport=transport)
            if town and haversine_km(town["lat"], town["lon"], locality.lat, locality.lon) <= MAX_ORIGIN_KM:
                return {**town, "label": f"{town['name']} city centre", "kind": "city_centre", "source": GEOCODE_SOURCE}
        return {"name": locality.name, "label": f"{locality.name} city centre", "lat": locality.lat,
                "lon": locality.lon, "kind": "city_centre",
                "source": {"name": "Qloo resolved locality centroid", "url": None}}
    return None


def attach_evidence(cands: list[Candidate], origin: dict | None, req: RunRequest) -> dict:
    with_dist = 0
    for c in cands:
        p = c.place
        if origin and p.lat is not None and p.lon is not None:
            c.distance_km = round(haversine_km(origin["lat"], origin["lon"], p.lat, p.lon), 2)
            c.trip = trip_estimates(c.distance_km, car_occupants=req.travelers, car_free=req.car_free)
            with_dist += 1
    return {"with_distance": with_dist, "without_distance": len(cands) - with_dist,
            "with_signals": sum(1 for c in cands if c.signals)}
