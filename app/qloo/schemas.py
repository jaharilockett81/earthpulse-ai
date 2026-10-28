"""Validated projections of Qloo responses.

Field names follow the hackathon API (hackathon.api.qloo.com) as documented in Qloo's
hackathon developer guide and as observed by live probes published by other entrants
(see docs/METHODOLOGY.md#qloo-schema-provenance). Parsing is tolerant: one malformed
record is dropped rather than failing the whole response, and unknown fields are ignored.
Only fields EarthPulse displays or reasons over are kept.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from pydantic import BaseModel, Field

log = logging.getLogger("earthpulse.qloo")


class TagRef(BaseModel):
    id: str
    name: str
    type: str = ""


class SearchHit(BaseModel):
    entity_id: str
    name: str
    types: list[str] = Field(default_factory=list)
    disambiguation: str | None = None
    popularity: float | None = None
    image_url: str | None = None
    short_description: str | None = None
    tags: list[TagRef] = Field(default_factory=list)

    @property
    def kind(self) -> str:
        """Human label for the entity type, e.g. 'movie' from 'urn:entity:movie'."""
        for t in self.types:
            if t.startswith("urn:entity:"):
                return t.split(":")[-1].replace("_", " ")
        return "interest"


class Contribution(BaseModel):
    entity_id: str
    score: float


class Place(BaseModel):
    entity_id: str
    name: str
    lat: float | None = None
    lon: float | None = None
    affinity: float | None = None
    popularity: float | None = None
    explainability: list[Contribution] = Field(default_factory=list)
    tags: list[TagRef] = Field(default_factory=list)
    address: str | None = None
    website: str | None = None
    price_level: int | None = None
    image_url: str | None = None
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    is_closed: bool | None = None
    primary_genre: str | None = None
    primary_genre_id: str | None = None

    def tag_ids(self) -> set[str]:
        return {t.id for t in self.tags}

    def tag_names(self) -> list[str]:
        return [t.name for t in self.tags]


class Locality(BaseModel):
    entity_id: str
    name: str
    disambiguation: str | None = None
    lat: float | None = None
    lon: float | None = None


class TagInsight(BaseModel):
    id: str
    name: str
    subtype: str | None = None
    affinity: float | None = None


# --------------------------------------------------------------------------- helpers


def _num(v: Any) -> float | None:
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _str(v: Any) -> str | None:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return None


def _tags(raw: Any) -> list[TagRef]:
    out: list[TagRef] = []
    if not isinstance(raw, list):
        return out
    for t in raw:
        if isinstance(t, str):
            out.append(TagRef(id=t, name=t.split(":")[-1].replace("_", " ")))
        elif isinstance(t, dict):
            tid = _str(t.get("tag_id")) or _str(t.get("id"))
            name = _str(t.get("name"))
            if tid and name:
                out.append(TagRef(id=tid, name=name, type=_str(t.get("type")) or ""))
    return out


def _image(props: dict) -> str | None:
    img = props.get("image")
    if isinstance(img, dict) and _str(img.get("url")):
        return _str(img.get("url"))
    imgs = props.get("images")
    if isinstance(imgs, list) and imgs and isinstance(imgs[0], dict):
        return _str(imgs[0].get("url"))
    return None


def _tolerant(items: Iterable[Any], fn) -> list:
    out = []
    dropped = 0
    for item in items:
        try:
            parsed = fn(item)
        except Exception:  # noqa: BLE001 — one odd record must not sink the response
            parsed = None
        if parsed is None:
            dropped += 1
        else:
            out.append(parsed)
    if dropped:
        log.info("qloo.parse dropped=%d malformed records", dropped)
    return out


# --------------------------------------------------------------------------- parsers


def _search_hit(h: Any) -> SearchHit | None:
    if not isinstance(h, dict):
        return None
    eid, name = _str(h.get("entity_id")) or _str(h.get("id")), _str(h.get("name"))
    if not eid or not name:
        return None
    props = h.get("properties") if isinstance(h.get("properties"), dict) else {}
    types = [t for t in h.get("types", []) if isinstance(t, str)] if isinstance(h.get("types"), list) else []
    if not types and _str(h.get("subtype")):
        types = [h["subtype"]]
    return SearchHit(
        entity_id=eid,
        name=name,
        types=types,
        disambiguation=_str(h.get("disambiguation")),
        popularity=_num(h.get("popularity")),
        image_url=_image(props),
        short_description=_str(props.get("short_description")) or _str(props.get("description")),
        tags=_tags(h.get("tags")),
    )


def parse_search(body: Any) -> list[SearchHit]:
    """/search returns `results` as a bare list (some versions nest under results.entities)."""
    if not isinstance(body, dict):
        return []
    res = body.get("results")
    if isinstance(res, dict):
        res = res.get("entities")
    return _tolerant(res if isinstance(res, list) else [], _search_hit)


def _contributions(q: dict) -> list[Contribution]:
    ex = q.get("explainability")
    items: list = []
    if isinstance(ex, dict):
        items = ex.get("signal.interests.entities") or []
    elif isinstance(ex, list):
        items = ex
    out = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict):
            eid = _str(it.get("entity_id")) or _str(it.get("id"))
            score = _num(it.get("score"))
            if eid and score is not None:
                out.append(Contribution(entity_id=eid, score=score))
    return sorted(out, key=lambda c: c.score, reverse=True)


def _place(e: Any) -> Place | None:
    if not isinstance(e, dict):
        return None
    eid, name = _str(e.get("entity_id")) or _str(e.get("id")), _str(e.get("name"))
    if not eid or not name:
        return None
    props = e.get("properties") if isinstance(e.get("properties"), dict) else {}
    loc = e.get("location") if isinstance(e.get("location"), dict) else {}
    q = e.get("query") if isinstance(e.get("query"), dict) else {}
    pg = props.get("primary_genre") if isinstance(props.get("primary_genre"), dict) else {}
    kws = props.get("keywords") if isinstance(props.get("keywords"), list) else []
    price = _num(props.get("price_level"))
    return Place(
        entity_id=eid,
        name=name,
        lat=_num(loc.get("lat")),
        lon=_num(loc.get("lon")),
        affinity=_num(q.get("affinity")),
        popularity=_num(e.get("popularity")),
        explainability=_contributions(q),
        tags=_tags(e.get("tags")),
        address=_str(props.get("address")),
        website=_str(props.get("website")),
        price_level=int(price) if price is not None and 1 <= price <= 4 else None,
        image_url=_image(props),
        description=_str(props.get("short_description")) or _str(props.get("description")),
        keywords=[k["name"].strip() for k in kws if isinstance(k, dict) and _str(k.get("name"))][:12],
        is_closed=props.get("is_closed") if isinstance(props.get("is_closed"), bool) else None,
        primary_genre=_str(pg.get("name")),
        primary_genre_id=_str(pg.get("id")),
    )


def parse_places(body: Any) -> tuple[list[Place], Locality | None]:
    if not isinstance(body, dict):
        return [], None
    res = body.get("results")
    ents = res.get("entities") if isinstance(res, dict) else None
    places = _tolerant(ents if isinstance(ents, list) else [], _place)
    locality = None
    q = body.get("query") if isinstance(body.get("query"), dict) else {}
    locs = q.get("localities") if isinstance(q.get("localities"), dict) else {}
    filt = locs.get("filter") if isinstance(locs.get("filter"), list) else []
    if filt and isinstance(filt[0], dict) and _str(filt[0].get("name")):
        f0 = filt[0]
        l = f0.get("location") if isinstance(f0.get("location"), dict) else {}
        locality = Locality(
            entity_id=_str(f0.get("entity_id")) or "",
            name=f0["name"].strip(),
            disambiguation=_str(f0.get("disambiguation")),
            lat=_num(l.get("lat")),
            lon=_num(l.get("lon")),
        )
    return places, locality


def _tag_insight(t: Any) -> TagInsight | None:
    if not isinstance(t, dict):
        return None
    tid, name = _str(t.get("tag_id")) or _str(t.get("id")), _str(t.get("name"))
    if not tid or not name:
        return None
    q = t.get("query") if isinstance(t.get("query"), dict) else {}
    return TagInsight(id=tid, name=name, subtype=_str(t.get("subtype")) or _str(t.get("type")), affinity=_num(q.get("affinity")))


def parse_tag_insights(body: Any) -> list[TagInsight]:
    if not isinstance(body, dict):
        return []
    res = body.get("results")
    tags = res.get("tags") if isinstance(res, dict) else None
    if tags is None and isinstance(res, dict):
        tags = res.get("entities")
    return _tolerant(tags if isinstance(tags, list) else [], _tag_insight)
