"""Synthetic Qloo responses for LOCAL UI development and tests only.

Nothing here is recorded from Qloo (Qloo's terms forbid publishing response data). Every
entity is generated from a hash of the request, every place name starts with "[Synthetic]",
and the UI shows a banner whenever this transport is active. It is refused in production
(see Settings.fixtures_active).
"""

from __future__ import annotations

import hashlib
import json
import math
import re

import httpx

from .taxonomy import CAT, GENRE, STEP_FREE_TAG

_ADJ = ["Fernleaf", "Juniper", "Copper Kettle", "Lantern", "Riverside", "Moss & Stone", "Old Mill", "Bluebird",
        "Cedar", "Willow", "Harbor", "Saltbox", "Marigold", "Driftwood", "Orchard", "Kestrel"]
_NOUN = {
    "park": "Commons", "botanical_garden": "Botanic Garden", "community_garden": "Community Garden",
    "museum": "Museum", "cultural_center": "Arts Centre", "cafe": "Café", "coffee_shop": "Coffee Roasters",
    "book_store": "Books", "record_store": "Records", "live_music_venue": "Music Hall", "jazz_club": "Jazz Club",
    "art_studio": "Studio", "pottery_classes": "Pottery", "restaurant": "Kitchen", "hotel": "Hotel",
}
_THEMES = ["slow living", "handmade", "indie", "nostalgic", "whimsical", "nature", "folk", "cozy", "artisan",
           "vinyl", "quiet", "botanical"]
_LOW = ["vegan options", "farm-to-table", "vintage", "native plants", "bike parking", "zero waste"]


def _h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)


def _centroid(city: str) -> tuple[float, float]:
    h = _h(city.lower())
    return 25 + (h % 2000) / 100, -120 + (h // 2000 % 4000) / 100


def _json(data: dict) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(data).encode(), headers={"content-type": "application/json"})


def _places(p: httpx.QueryParams) -> dict:
    city = p.get("filter.location.query", "Anytown")
    lat0, lon0 = _centroid(city)
    m = re.match(r"POINT\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)", p.get("filter.location", ""))
    if m:  # search around a point (Qloo's filter.location); same synthetic places, centred there
        lon0, lat0 = float(m.group(1)), float(m.group(2))
        city = f"{lat0:.3f},{lon0:.3f}"
    tags = [t for t in p.get("filter.tags", "").split(",") if t]
    seeds = [s for s in p.get("signal.interests.entities", "").split(",") if s]
    sig_tags = [s for s in p.get("signal.interests.tags", "").split(",") if s]
    take = int(p.get("take", "10"))
    out = []
    for i in range(min(take, 14)):
        leaf_tag = tags[i % len(tags)] if tags else CAT + "park"
        leaf = leaf_tag.split(":")[-1]
        h = _h(city, leaf_tag, str(i))
        name = f"[Synthetic] {_ADJ[h % len(_ADJ)]} {_NOUN.get(leaf, leaf.title())}"
        if i == 13:  # one non-experience, to exercise the blocklist
            name, leaf_tag = "[Synthetic] Community Bank", CAT + "bank"
        dist = 0.4 + (h % 150) / 10  # 0.4–15.3 km
        ang = (h // 150 % 360) * math.pi / 180
        ptags = [{"tag_id": leaf_tag, "name": leaf.replace("_", " "), "type": "urn:tag:category:place"}]
        theme = _THEMES[h // 7 % len(_THEMES)]
        ptags.append({"tag_id": "urn:tag:keyword:qloo:" + theme.replace(" ", "_"), "name": theme,
                      "type": "urn:tag:keyword:qloo"})
        if h % 3 == 0:
            low = _LOW[h // 11 % len(_LOW)]
            ptags.append({"tag_id": "urn:tag:offerings:place:" + low.replace(" ", "_"), "name": low,
                          "type": "urn:tag:offerings:place"})
        if h % 2 == 0:
            ptags.append({"tag_id": STEP_FREE_TAG, "name": "Wheelchair accessible entrance",
                          "type": "urn:tag:accessibility:place"})
        q: dict = {}
        if seeds or sig_tags:
            q["affinity"] = round(0.55 + (_h(*seeds, *sig_tags, name) % 440) / 1000, 3)
            if seeds:
                q["explainability"] = {"signal.interests.entities": [
                    {"entity_id": s, "score": round(0.3 + (_h(s, name) % 600) / 1000, 3)} for s in seeds]}
        props = {
            "address": f"{10 + h % 890} {_ADJ[h // 3 % len(_ADJ)]} St, {city}",
            "keywords": [{"name": theme}],
            "is_closed": False,
        }
        if h % 3 == 1:
            props["price_level"] = 1 + h % 4
        if leaf_tag.startswith(GENRE):
            props["primary_genre"] = {"id": leaf_tag, "name": leaf}
        out.append({
            "entity_id": f"SYN-{h:x}", "name": name, "popularity": round((h % 1000) / 1000, 3),
            "location": {"lat": lat0 + dist / 111 * math.cos(ang), "lon": lon0 + dist / 85 * math.sin(ang)},
            "tags": ptags, "properties": props, "query": q,
        })
    return {"success": True, "results": {"entities": out},
            "query": {"localities": {"filter": [{"entity_id": f"SYN-LOC-{_h(city):x}", "name": city.split(",")[0],
                                                 "location": {"lat": lat0, "lon": lon0}}]}}}


def handler(request: httpx.Request) -> httpx.Response:
    p = request.url.params
    path = request.url.path
    if path == "/search":
        q = p.get("query", "")
        return _json({"results": [{
            "entity_id": f"SYN-E-{_h(q.lower()):x}", "name": q.strip().title(), "types": ["urn:entity:movie"],
            "popularity": 0.9, "disambiguation": "Synthetic entity",
            "tags": [{"id": "urn:tag:genre:qloo:" + t, "name": t} for t in _THEMES[:3]]}]})
    if path == "/v2/tags":
        q = p.get("filter.query", "")
        return _json({"results": {"tags": [{"id": "urn:tag:keyword:qloo:" + q.lower().replace(" ", "_"),
                                            "name": q.lower(), "type": "urn:tag:keyword:qloo"}]}})
    if path == "/v2/insights" and p.get("filter.type") == "urn:tag":
        seeds = p.get("signal.interests.entities", "")
        n = int(p.get("take", "6"))
        pool = _THEMES if "ambience" not in p.get("filter.tag.types", "") else ["cozy", "quiet", "lively", "romantic"]
        start = _h(seeds) % len(pool)
        names = [pool[(start + i) % len(pool)] for i in range(min(n, len(pool)))]
        return _json({"results": {"tags": [{"tag_id": "urn:tag:keyword:qloo:" + x.replace(" ", "_"), "name": x,
                                            "query": {"affinity": round(0.9 - i * 0.05, 2)}}
                                           for i, x in enumerate(names)]}})
    if path == "/v2/insights":
        return _json(_places(p))
    return httpx.Response(404, json={"error": "not found"})


def transport() -> httpx.MockTransport:
    return httpx.MockTransport(handler)
