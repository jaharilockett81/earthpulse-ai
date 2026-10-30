"""Taste Intelligence Agent.

Turns what the user loves into Qloo signals:
  - free text  -> interests (LLM if configured, deterministic splitter otherwise)
  - interests  -> Qloo entities via /search, or Qloo taste tags via /v2/tags for concepts
                 like "slow living" that are not entities
  - entities   -> a taste portrait via /v2/insights?filter.type=urn:tag
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from difflib import SequenceMatcher

from ..llm import LLM
from ..models import RunRequest, Seed
from ..qloo.client import CallStats, QlooBadRequest, QlooClient, QlooError

SEARCH_TYPES = [
    "urn:entity:movie", "urn:entity:artist", "urn:entity:tv_show", "urn:entity:book", "urn:entity:person",
    "urn:entity:podcast", "urn:entity:brand", "urn:entity:place", "urn:entity:destination", "urn:entity:videogame",
]
TASTE_TAG_TYPES = ["urn:tag:genre:qloo", "urn:tag:keyword:qloo", "urn:tag:genre:music"]
AMBIENCE_TAG_TYPES = ["urn:tag:ambience:qloo"]

_LEAD = re.compile(
    r"^\s*(please\s+)?(plan|build|make|create|find|suggest|give)\s+(me\s+)?(an?\s+)?"
    r"((day|weekend|trip|itinerary|plan|afternoon|evening|day trip)\s+)*"
    r"((inspired|based)\s+(by|on)|for\s+someone\s+who\s+(loves|likes)|around|with)\s+",
    re.I,
)


_LOVES = re.compile(
    r"^.*?\b(?:who\s+(?:loves?|likes?|enjoys?|is\s+into)|(?:inspired|based)\s+(?:by|on)|(?:fans?|lovers?)\s+of|"
    r"(?:i|we)\s+(?:love|like|enjoy|adore)|into)\s+",
    re.I,
)
_TAIL = re.compile(r"\s+\b(?:in|near|around|at)\s+[A-Z][\w .,'-]*$")


def heuristic_interests(prompt: str) -> list[str]:
    text = _LEAD.sub("", prompt.strip())
    text = _LOVES.sub("", text, count=1)
    text = _TAIL.sub("", text)
    text = re.sub(r"\b(i|we)\s+(love|like|enjoy)\s+", "", text, flags=re.I)
    parts = re.split(r",|;|\band\b|&|\+|\n", text, flags=re.I)
    out = []
    for p in parts:
        p = p.strip(" .!?\"'")
        if 2 <= len(p) <= 80:
            out.append(p)
    return list(dict.fromkeys(out))[:5]


async def parse_intent(req: RunRequest, llm: LLM) -> tuple[list[Seed], str]:
    if req.seeds:
        return req.seeds, "form"
    prompt = req.prompt or ""
    names = await llm.parse_interests(prompt) if llm.available else None
    source = "ai" if names else "rules"
    names = names or heuristic_interests(prompt)
    return [Seed(name=n) for n in names], source


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()  # Amélie -> Amelie
    s = re.sub(r"\(.*?\)", "", s.lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(re.sub(r"\b(the|a|an)\b", " ", s).split())


def similar(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb or na in nb.split(" "):
        return 1.0
    short, long_ = sorted((na, nb), key=len)
    # Substring counts as a match only when it covers most of the other name, so "botanical gardens"
    # does not match "Botanical Gardens of Peter the Great".
    if len(short) > 3 and short in long_ and len(short) / len(long_) >= 0.6:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


async def _tag_match(client: QlooClient, name: str, stats: CallStats) -> dict | None:
    try:
        tags = await client.search_tags(name, take=6, stats=stats)
    except QlooBadRequest:
        return None
    tbest = max(tags, key=lambda t: similar(name, t.name), default=None)
    if tbest and similar(name, tbest.name) >= 0.6:
        return {"name": tbest.name, "tag_id": tbest.id, "kind": "taste tag", "resolved_as": "tag"}
    return None


async def _resolve_one(client: QlooClient, seed: Seed, stats: CallStats) -> dict:
    base = {"input": seed.name, "name": seed.name, "entity_id": None, "tag_id": None,
            "kind": seed.kind or "interest", "image_url": None, "resolved_as": "none", "tags": []}
    if seed.entity_id:
        return {**base, "entity_id": seed.entity_id, "resolved_as": "entity"}
    # All-lowercase free text ("botanical gardens", "slow living") is usually a concept, not a title:
    # try Qloo taste tags first, and only fall back to entity search.
    if seed.name == seed.name.lower():
        tag = await _tag_match(client, seed.name, stats)
        if tag:
            return {**base, **tag}
    try:
        try:
            hits = await client.search(seed.name, types=SEARCH_TYPES, take=6, stats=stats)
        except QlooBadRequest:  # a type in our list isn't accepted for search — fall back to untyped
            hits = await client.search(seed.name, take=8, stats=stats)
    except QlooBadRequest:
        hits = []
    hits = [h for h in hits if "urn:entity:album" not in h.types]
    best = max(hits, key=lambda h: (similar(seed.name, h.name), h.popularity or 0), default=None)
    if best and similar(seed.name, best.name) >= 0.72:
        return {**base, "name": best.name, "entity_id": best.entity_id, "kind": best.kind,
                "image_url": best.image_url, "resolved_as": "entity",
                "tags": [t.name for t in best.tags][:8], "disambiguation": best.disambiguation}
    tag = await _tag_match(client, seed.name, stats)
    if tag:
        return {**base, **tag}
    if best and similar(seed.name, best.name) >= 0.5:
        return {**base, "name": best.name, "entity_id": best.entity_id, "kind": best.kind,
                "image_url": best.image_url, "resolved_as": "entity", "approximate": True,
                "tags": [t.name for t in best.tags][:8]}
    return base


async def resolve_seeds(client: QlooClient, seeds: list[Seed], stats: CallStats) -> list[dict]:
    results = await asyncio.gather(*[_resolve_one(client, s, stats) for s in seeds], return_exceptions=True)
    out = []
    first_error: QlooError | None = None
    for seed, r in zip(seeds, results):
        if isinstance(r, QlooError):
            first_error = first_error or r
            out.append({"input": seed.name, "name": seed.name, "resolved_as": "error", "entity_id": None,
                        "tag_id": None, "kind": seed.kind or "interest", "tags": []})
        elif isinstance(r, Exception):
            raise r
        else:
            out.append(r)
    if first_error and not any(s["resolved_as"] in ("entity", "tag") for s in out):
        raise first_error
    return out


async def taste_portrait(client: QlooClient, entity_ids: list[str], stats: CallStats) -> dict:
    if not entity_ids:
        return {"taste": [], "ambience": []}
    taste, ambience = await asyncio.gather(
        client.taste_tags(entity_ids, TASTE_TAG_TYPES, take=12, stats=stats),
        client.taste_tags(entity_ids, AMBIENCE_TAG_TYPES, take=6, stats=stats),
        return_exceptions=True,
    )

    def pack(x):
        if isinstance(x, Exception):
            return []
        seen, out = set(), []
        for t in x:
            k = t.name.lower()
            if k not in seen:
                seen.add(k)
                out.append({"id": t.id, "name": t.name, "affinity": t.affinity})
        return out

    return {"taste": pack(taste), "ambience": pack(ambience)}
