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
from ..qloo.client import CallStats, QlooClient, QlooError
from ..qloo.schemas import Locality, Place
from ..qloo.taxonomy import CATEGORIES, classify, has_step_free_tag, is_blocked, low_impact_signals

TAKE_PER_CATEGORY = 20


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


def _keep(place: Place, req: RunRequest) -> str | None:
    if place.is_closed or is_blocked(place):
        return None
    if req.budget and place.price_level and place.price_level > req.budget:
        return None
    if req.step_free and not has_step_free_tag(place):
        return None
    return "ok"


async def discover(client: QlooClient, req: RunRequest, *, seed_ids: list[str], seed_tags: list[str],
                   stats: CallStats, use_signals: bool = True) -> DiscoveryResult:
    async def one(key: str):
        cat = CATEGORIES[key]
        return await client.place_insights(
            location_query=req.location,
            seed_ids=seed_ids if use_signals else None,
            seed_tags=seed_tags if use_signals else None,
            tags=list(cat.tags),
            price_max=req.budget,
            take=TAKE_PER_CATEGORY,
            explain=use_signals,
            stats=stats,
        )

    results = await asyncio.gather(*[one(k) for k in req.categories], return_exceptions=True)
    seen: set[str] = set()
    candidates: list[Candidate] = []
    per_category: dict[str, dict] = {}
    errors: list[QlooError] = []
    locality: Locality | None = None
    for key, res in zip(req.categories, results):
        stat = {"label": CATEGORIES[key].label, "returned": 0, "kept": 0, "dropped": 0}
        per_category[key] = stat
        if isinstance(res, QlooError):
            errors.append(res)
            stat["error"] = res.user_message
            continue
        if isinstance(res, Exception):
            raise res
        places, loc = res
        locality = locality or loc
        stat["returned"] = len(places)
        for p in places:
            if p.entity_id in seen:
                continue
            got = classify(p, [key]) or classify(p, req.categories)
            if not got or not _keep(p, req):
                stat["dropped"] += 1
                continue
            seen.add(p.entity_id)
            candidates.append(Candidate(place=p, category=got, step_free=has_step_free_tag(p),
                                        signals=low_impact_signals(p)))
            stat["kept"] += 1
    if errors and not candidates:
        raise errors[0]
    return DiscoveryResult(candidates=candidates, locality=locality, per_category=per_category, errors=errors)
