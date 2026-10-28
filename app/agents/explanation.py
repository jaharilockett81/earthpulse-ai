"""Explanation Agent.

Builds the result cards. Each card's "why" is assembled from grounded facts only:
Qloo's explainability (which of your interests drove the match), taste themes shared with your
portrait, the place's own Qloo tags, and computed distance. If an LLM is configured it may
reword those facts into one sentence; the reworded text is validated (no new numbers) and
labelled "AI-written". Every other statement on a card carries a claim label.
"""

from __future__ import annotations

from ..llm import LLM
from ..qloo.taxonomy import CATEGORIES
from .discovery import Candidate

PRICE_TEXT = {1: "$", 2: "$$", 3: "$$$", 4: "$$$$"}


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def facts_for(c: Candidate, seeds: list[dict], portrait: dict, origin: dict | None, mode: str) -> tuple[list[str], dict]:
    names = {s["entity_id"]: s["name"] for s in seeds if s.get("entity_id")}
    links = [{"name": names[x.entity_id], "score": round(x.score, 3)} for x in c.place.explainability
             if x.entity_id in names][:3]
    theme_names = {t["name"].lower(): t["name"] for t in portrait.get("taste", []) + portrait.get("ambience", [])}
    shared = [theme_names[n.lower()] for n in c.place.tag_names() if n.lower() in theme_names][:3]
    facts: list[str] = []
    if mode == "qloo":
        if links:
            facts.append(f"Qloo's explainability links it most strongly to your interest in {links[0]['name']}.")
        elif any(s.get("tag_id") for s in seeds):
            facts.append("Qloo ranked it for the taste themes you described.")
        if shared:
            facts.append(f"It shares taste themes from your portrait: {_join(shared)}.")
    elif c.keyword_hits:
        facts.append(f"Its listing matches your words: {_join(c.keyword_hits[:3])}.")
    else:
        facts.append(f"A listed {CATEGORIES[c.category].label.lower()} option with no keyword match to your words.")
    tags = [t for t in c.place.tag_names() if t not in shared][:3]
    if tags:
        facts.append(f"Qloo tags it as {_join(tags)}.")
    if c.signals:
        facts.append(f"Lower-impact signals in its tags: {_join(c.signals[:2])}.")
    if c.distance_km is not None and origin:
        facts.append(f"It is {c.distance_km} km from {origin['label']} in a straight line.")
    return facts, {"links": links, "shared": shared}


def claims_for(c: Candidate, origin: dict | None) -> list[dict]:
    p = c.place
    out = []
    if p.address:
        out.append({"label": "listed", "text": f"Address: {p.address}"})
    out.append({"label": "listed", "text": f"Price: {PRICE_TEXT[p.price_level]}" if p.price_level else "Price not listed"})
    if p.affinity is not None:
        out.append({"label": "qloo_signal", "text": f"Taste affinity {p.affinity:.2f} (Qloo, 0–1)"})
    for s in c.signals[:3]:
        out.append({"label": "qloo_signal", "text": f"Tag: {s} (a taste signal, not a certification)"})
    if c.step_free:
        out.append({"label": "listed", "text": "Wheelchair-accessible entrance (Qloo tag)"})
    if c.distance_km is not None and origin:
        out.append({"label": "computed", "text": f"{c.distance_km} km straight-line from {origin['label']}"})
    else:
        out.append({"label": "not_verified", "text": "Distance and emissions not available"})
    out.append({"label": "not_verified", "text": "Opening hours and availability not verified"})
    return out


def card(c: Candidate, facts: list[str], meta: dict, origin: dict | None, checks: list[dict] | None) -> dict:
    p = c.place
    return {
        "id": c.id,
        "name": p.name,
        "category": c.category,
        "category_label": CATEGORIES[c.category].label,
        "image_url": p.image_url,
        "address": p.address,
        "website": p.website,
        "price_level": p.price_level,
        "price_text": PRICE_TEXT.get(p.price_level or 0, "Price not listed"),
        "lat": p.lat,
        "lon": p.lon,
        "affinity": p.affinity,
        "score": c.score,
        "score_parts": c.score_parts,
        "distance_km": c.distance_km,
        "trip": c.trip,
        "signals": c.signals,
        "step_free": c.step_free,
        "tags": p.tag_names()[:8],
        "keyword_hits": c.keyword_hits,
        "taste_links": meta["links"],
        "shared_themes": meta["shared"],
        "why": {"text": " ".join(facts[:2]) if facts else "", "facts": facts,
                "label": "qloo_signal" if meta["links"] or meta["shared"] else "listed"},
        "claims": claims_for(c, origin),
        "checks": checks or [],
    }


async def explain(cards: list[dict], llm: LLM, use_llm: bool) -> str:
    """Optionally reword each card's facts. Returns 'ai' if any card was reworded, else 'rules'."""
    if not use_llm or not llm.available or not cards:
        return "rules"
    polished = await llm.polish_explanations(
        [{"id": c["id"], "name": c["name"], "facts": c["why"]["facts"]} for c in cards])
    if not polished:
        return "rules"
    for c in cards:
        if c["id"] in polished:
            c["why"]["text"] = polished[c["id"]]
            c["why"]["label"] = "ai_written"
    return "ai"
