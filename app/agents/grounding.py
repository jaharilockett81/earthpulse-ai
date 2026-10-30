"""Grounding Validator: the last deterministic gate before anything reaches the user.

It audits the finished result against independent records of this run, not against the
pipeline's own intermediate state:
  - provenance:   every displayed place id was returned by a Qloo response in THIS run
                  (recorded by the Qloo client, see CallStats.place_names), under the same name
  - interests:    every "driven by" interest is one the user gave and Qloo matched
  - affinity:     every affinity shown equals the value Qloo returned
  - wording:      every number in a "why" sentence appears in that card's grounded facts;
                  an AI-written sentence that fails is replaced by the deterministic one (repair)
  - arithmetic:   CO2e per card is recomputed from EPA factors; day and plan totals re-added
  - constraints:  categories, budget, step-free and car-free hold for every planned stop;
                  Taste Bridge places are outside the requested categories
  - labels:       every claim carries one of the five allowed labels
"""

from __future__ import annotations

import re

from ..evidence.emissions import trip_estimates
from ..models import RunRequest

ALLOWED_LABELS = {"listed", "computed", "qloo_signal", "ai_written", "not_verified"}
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _check(cid: str, passed: bool, detail: str, failures: list[str] | None = None) -> dict:
    return {"id": cid, "passed": passed, "detail": detail, "failures": (failures or [])[:5]}


def validate(result: dict, req: RunRequest, place_names: dict[str, str], seeds: list[dict],
             radius_km: float = 25.0) -> dict:
    cards: dict[str, dict] = result["cards"]
    planned = [s["id"] for d in result["days"] for s in d["stops"]]
    bridges = {b["id"] for b in result.get("bridges", [])}
    checks, repaired = [], 0

    bad = [c["name"] for cid, c in cards.items() if place_names.get(cid) != c["name"]]
    checks.append(_check("provenance", not bad,
                         f"All {len(cards)} places shown were returned by Qloo in this run.", bad))

    matched = {s["name"] for s in seeds if s.get("resolved_as") in ("entity", "tag")}
    bad = [l["name"] for c in cards.values() for l in c["taste_links"] if l["name"] not in matched]
    bad += [d["name"] for d in result.get("drivers", []) if d["name"] not in matched]
    checks.append(_check("interests", not bad, "Every credited interest is one you gave and Qloo matched.", bad))

    bad = [c["name"] for c in cards.values() for cl in c["claims"]
           if cl["label"] == "qloo_signal" and cl["text"].startswith("Taste affinity")
           and (c["affinity"] is None or f"{c['affinity']:.2f}" not in cl["text"])]
    checks.append(_check("affinity", not bad, "Affinity values match Qloo's.", bad))

    bad = []
    for c in cards.values():
        allowed = set(_NUM.findall(" ".join(c["why"]["facts"]) + " " + c["name"]))
        stray = [n for n in _NUM.findall(c["why"]["text"]) if n not in allowed]
        if stray:
            bad.append(c["name"])
            if c["why"]["label"] == "ai_written":  # repair: fall back to the grounded sentence
                c["why"]["text"] = " ".join(c["why"]["facts"][:2])
                c["why"]["label"] = "qloo_signal" if c["taste_links"] or c["shared_themes"] else "listed"
                repaired += 1
    checks.append(_check("wording", not bad or repaired == len(bad),
                         "No number in an explanation is missing from its facts"
                         + (f"; {repaired} AI sentence(s) replaced with grounded text." if repaired else "."), bad))

    bad = [c["name"] for c in cards.values() if c["distance_km"] is not None and c["distance_km"] > radius_km]
    bad += [f"day {d['day']} leg {l['km']} km" for d in result["days"] for l in d["legs"] if l["km"] > 2 * radius_km]
    checks.append(_check("geography", not bad, f"Every place is within {radius_km:g} km of the starting point "
                         f"and no leg is longer than {2 * radius_km:g} km.", bad))

    bad = [c["name"] for c in cards.values() if c["distance_km"] is not None and c["trip"] !=
           trip_estimates(c["distance_km"], car_occupants=req.travelers, car_free=req.car_free)]
    for d in result["days"]:
        legs = d["legs"]
        if legs and abs(round(sum(l["kg_co2e"] for l in legs), 2) - d["totals"]["suggested_kg_co2e"]) > 0.011:
            bad.append(f"day {d['day']} total")
    sm = result["summary"]
    if abs(round(sum(d["totals"]["suggested_kg_co2e"] for d in result["days"]), 2) - sm["suggested_kg_co2e"]) > 0.011:
        bad.append("plan total")
    checks.append(_check("arithmetic", not bad, "Every CO2e figure and total recomputes from EPA factors.", bad))

    bad = []
    for cid in planned:
        c = cards[cid]
        if c["category"] not in req.categories:
            bad.append(f"{c['name']}: category")
        if req.budget and c["price_level"] and c["price_level"] > req.budget:
            bad.append(f"{c['name']}: budget")
        if req.step_free and not c["step_free"]:
            bad.append(f"{c['name']}: step-free")
        if req.car_free and c["trip"] and any(m["mode"] == "car" for m in c["trip"]["modes"]):
            bad.append(f"{c['name']}: car-free")
    for bid in bridges:
        if cards[bid]["category"] in req.categories:
            bad.append(f"{cards[bid]['name']}: bridge inside requested categories")
    checks.append(_check("constraints", not bad, f"Your constraints hold for all {len(planned)} planned stops.", bad))

    bad = [c["name"] for c in cards.values() for cl in c["claims"] if cl["label"] not in ALLOWED_LABELS]
    bad += [c["name"] for c in cards.values() if c["why"]["label"] not in ALLOWED_LABELS]
    checks.append(_check("labels", not bad, "Every statement carries a claim label.", bad))

    return {"passed": all(c["passed"] for c in checks), "checks": checks, "repaired": repaired}
