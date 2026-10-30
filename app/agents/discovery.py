"""Discovery Agent.

One Qloo place-insights call per chosen category, all scoped to the user's destination.
In "qloo" mode the call carries the user's taste signals (entities + tags) so Qloo ranks
places by affinity; in "baseline" mode the same call is made WITHOUT taste signals.

Because Qloo's `filter.tags` is a soft union, every returned place is re-classified from its
own tags. Non-experiences (banks, schools…), closed places and over-budget places are dropped.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..models import RunRequest
from ..qloo.client import CallStats, QlooBadRequest, QlooClient, QlooError
from ..qloo.schemas import Locality, Place
from ..qloo.taxonomy import CATEGORIES, classify, has_step_free_tag, is_blocked, low_impact_signals

TAKE_PER_CATEGORY = 20
ADAPT_TAKE = 50  # one wider re-query for a category that came back too thin (bounded: at most once)


@dataclass
class Candidate:
    place: Place
    category: str
    step_free: bool = False
    signals: list[str] = field(default_factory=list)
    distance_km: float | None = None
    trip: dict | None = None
    score: float = 0.0
    score_parts: dict = field(default_factory=dict)
    keyword_hits: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.place.entity_id


@dataclass
class DiscoveryResult:
    candidates: list[Candidate]
    locality: Locality | None
    per_category: dict[str, dict]
    errors: list[QlooError]
    constrained: bool = False  # True when Qloo was queried around the geocoded city point


def _drop_reason(place: Place, req: RunRequest) -> str | None:
    """Why a place is unusable for this request, or None if it can be kept."""
    if place.is_closed:
        return "closed"
    if is_blocked(place):
        return "not_an_experience"
    if req.budget and place.price_level and place.price_level > req.budget:
        return "over_budget"
    if req.step_free and not has_step_free_tag(place):
        return "no_step_free_tag"
    return None


async def discover(client: QlooClient, req: RunRequest, *, seed_ids: list[str], seed_tags: list[str],
                   stats: CallStats, use_signals: bool = True, center: dict | None = None) -> DiscoveryResult:
    """`center` is the validated, geocoded destination city ({name, lat, lon}).

    With a center, Qloo is asked only for places within the user's radius of it (`filter.location`
    POINT + `filter.location.radius`), so geography is constrained at the source. Without one (the
    geocoder couldn't confirm the city), Qloo resolves the name itself and the area gate filters after.
    """
    if center:
        try:
            found = await _discover(client, req, seed_ids=seed_ids, seed_tags=seed_tags, stats=stats,
                                    use_signals=use_signals, point=(center["lat"], center["lon"]),
                                    radius_m=int(req.radius_km * 1000))
            found.locality = Locality(entity_id="geocoded", name=center["name"], lat=center["lat"], lon=center["lon"])
            found.constrained = True
            return found
        except QlooBadRequest:  # point search refused: fall back to Qloo's name lookup + the area gate
            pass
    return await _discover(client, req, seed_ids=seed_ids, seed_tags=seed_tags, stats=stats,
                           use_signals=use_signals)


async def _discover(client: QlooClient, req: RunRequest, *, seed_ids: list[str], seed_tags: list[str],
                    stats: CallStats, use_signals: bool = True,
                    point: tuple[float, float] | None = None, radius_m: int = 25000) -> DiscoveryResult:
    async def one(key: str, take: int = TAKE_PER_CATEGORY):
        cat = CATEGORIES[key]
        return await client.place_insights(
            location_query=req.location,
            seed_ids=seed_ids if use_signals else None,
            seed_tags=seed_tags if use_signals else None,
            tags=list(cat.tags),
            price_max=req.budget,
            take=take,
            explain=use_signals,
            stats=stats,
            point=point,
            radius_m=radius_m,
        )

    results = await asyncio.gather(*[one(k) for k in req.categories], return_exceptions=True)
    seen: set[str] = set()
    candidates: list[Candidate] = []
    per_category: dict[str, dict] = {}
    errors: list[QlooError] = []
    locality: Locality | None = None
    need = {k: (1 if k == "stay" else req.days) for k in req.categories}

    looked: set[tuple[str, str]] = set()

    def absorb(key: str, res) -> None:
        nonlocal locality
        stat = per_category.setdefault(key, {"label": CATEGORIES[key].label, "returned": 0, "kept": 0, "dropped": 0,
                                             "why_dropped": {}})
        if isinstance(res, QlooError):
            errors.append(res)
            stat["error"] = res.user_message
            return
        if isinstance(res, Exception):
            raise res
        places, loc = res
        locality = locality or loc
        stat["returned"] = max(stat["returned"], len(places))
        for p in places:
            if (key, p.entity_id) in looked:  # a re-query returns the first pass again; count each place once
                continue
            looked.add((key, p.entity_id))
            if p.entity_id in seen:  # already kept from another category's call
                stat["dropped"] += 1
                stat["why_dropped"]["duplicate"] = stat["why_dropped"].get("duplicate", 0) + 1
                continue
            got = classify(p, [key]) or classify(p, req.categories)
            why = _drop_reason(p, req) if got else "other_category"
            if why:
                stat["dropped"] += 1
                stat["why_dropped"][why] = stat["why_dropped"].get(why, 0) + 1
                continue
            seen.add(p.entity_id)
            candidates.append(Candidate(place=p, category=got, step_free=has_step_free_tag(p),
                                        signals=low_impact_signals(p)))
            stat["kept"] += 1

    for key, res in zip(req.categories, results):
        absorb(key, res)
    # Observe -> adapt: a category with fewer usable places than the plan needs gets exactly one
    # wider re-query (Qloo returns the next-ranked places). Constraints are never relaxed.
    thin = [k for k in req.categories if not per_category[k].get("error")
            and per_category[k]["kept"] < need[k] and per_category[k]["returned"] >= TAKE_PER_CATEGORY]
    if thin:
        retry = await asyncio.gather(*[one(k, ADAPT_TAKE) for k in thin], return_exceptions=True)
        for key, res in zip(thin, retry):
            before = per_category[key]["kept"]
            absorb(key, res)
            per_category[key]["adapted"] = {"take": ADAPT_TAKE, "gained": per_category[key]["kept"] - before}
    if errors and not candidates:
        raise errors[0]
    return DiscoveryResult(candidates=candidates, locality=locality, per_category=per_category, errors=errors)
