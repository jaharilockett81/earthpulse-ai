"""Distance math and optional geocoding of the user's starting point."""

from __future__ import annotations

import logging
import math

import httpx

log = logging.getLogger("earthpulse.geo")

GEOCODE_SOURCE = {
    "name": "Open-Meteo Geocoding API (GeoNames data, CC BY 4.0)",
    "url": "https://open-meteo.com/en/docs/geocoding-api",
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088  # mean Earth radius, km
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


_CACHE: dict[str, dict] = {}


async def geocode(name: str, url: str, timeout_s: float = 6.0,
                  transport: httpx.AsyncBaseTransport | None = None) -> dict | None:
    """Resolve a place name to {name, lat, lon, label}. Returns None on any failure."""
    name = name.strip()
    if len(name) < 2:
        return None
    key = name.lower()
    if key in _CACHE:
        return _CACHE[key]
    # Open-Meteo matches on the place name; drop a trailing ", FL"-style qualifier for the query
    # but use it to prefer the right admin area.
    head, _, tail = name.partition(",")
    try:
        async with httpx.AsyncClient(timeout=timeout_s, transport=transport) as c:
            r = await c.get(url, params={"name": head.strip(), "count": 5, "language": "en", "format": "json"})
            r.raise_for_status()
            results = (r.json() or {}).get("results") or []
    except Exception as exc:  # noqa: BLE001 — geocoding is optional; any failure falls back to Qloo's locality
        log.warning("geocode.failed err=%s", type(exc).__name__)
        return None
    if not results:
        return None
    pick = results[0]
    hint = tail.strip().lower()
    if hint:
        for res in results:
            hay = " ".join(str(res.get(k, "")) for k in ("admin1", "country", "country_code")).lower()
            if hint in hay or (len(hint) == 2 and hint == str(res.get("country_code", "")).lower()):
                pick = res
                break
    try:
        lat, lon = float(pick["latitude"]), float(pick["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    label = ", ".join(str(p) for p in (pick.get("name"), pick.get("admin1"), pick.get("country")) if p)
    out = {"name": pick.get("name", head), "lat": lat, "lon": lon, "label": label}
    if len(_CACHE) < 500:
        _CACHE[key] = out
    return out
