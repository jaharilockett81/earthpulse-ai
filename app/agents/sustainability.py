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
                         transport=None, destination: dict | None = None) -> dict | None:
    """The point every distance is measured from, always named so no route has an unstated origin.

    Order: the user's own starting point (if it geocodes within MAX_ORIGIN_KM of the destination), then
    the validated city centre, then Qloo's point for the name (labelled as Qloo's, not as a city centre).
    """
    center = destination if destination and destination.get("status") == "city" else None
    ref = center or (locality.model_dump() if locality and locality.lat is not None and locality.lon is not None else None)
    if req.origin and not settings.fixtures_active:  # synthetic places have synthetic coordinates
        got = await geocode(req.origin, settings.geocode_url, transport=transport)
        far = got and ref and haversine_km(got["lat"], got["lon"], ref["lat"], ref["lon"]) > MAX_ORIGIN_KM
        if got and not far:
            return {**got, "kind": "geocoded", "source": GEOCODE_SOURCE}
    if center:
        return {"name": center["name"], "label": f"{center['name']} city centre", "lat": center["lat"],
                "lon": center["lon"], "kind": "city_centre", "source": GEOCODE_SOURCE}
    if ref:
        return {"name": locality.name, "label": f"Qloo's map point for {locality.name}", "lat": locality.lat,
                "lon": locality.lon, "kind": "qloo_locality",
                "source": {"name": "Qloo resolved locality point", "url": None}}
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


def gate_by_area(cands: list[Candidate], origin: dict | None, radius_km: float) -> tuple[list[Candidate], list[Candidate]]:
    """Split candidates into (in_area, out_of_area) by straight-line distance from the origin.

    Places with no coordinates stay in (they are labelled "Not verified" later) because they
    cannot be shown to be out of area; places with impossible coordinates are out.
    """
    keep, out = [], []
    for c in cands:
        p = c.place
        bad = p.lat is not None and p.lon is not None and not (-90 <= p.lat <= 90 and -180 <= p.lon <= 180)
        if bad or (origin and c.distance_km is not None and c.distance_km > radius_km):
            out.append(c)
        else:
            keep.append(c)
    return keep, out
