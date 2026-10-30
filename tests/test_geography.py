"""Geographic validation: no released plan may contain out-of-area places or impossible legs.

Regression for a live report of an "Oregon" plan with 8 stops and 1,924 km of straight-line travel:
the destination resolved to an area far larger than a city, and nothing bounded how far a stop could be.
"""

import json

import httpx
import respx
from fastapi.testclient import TestClient

from app.agents import grounding, sustainability
from app.agents.discovery import Candidate
from app.main import create_app
from app.qloo import fixtures
from app.qloo.schemas import Place
from app.qloo.taxonomy import CATEGORIES

from .conftest import BASE
from .test_api import BODY, events


def _shifting(should_move):
    """fixtures.handler, but places for which should_move(params, index) is true move ~330 km north."""
    def handler(req):
        resp = fixtures.handler(req)
        p = req.url.params
        if req.url.path == "/v2/insights" and p.get("filter.type") == "urn:entity:place":
            body = json.loads(resp.content)
            for i, ent in enumerate(body["results"]["entities"]):
                if should_move(p, i):
                    ent["location"]["lat"] += 3.0
            return httpx.Response(200, json=body)
        return resp
    return handler


def _run(settings, handler, body):
    with respx.mock(base_url=BASE, assert_all_called=False) as r:
        r.route().mock(side_effect=handler)
        return events(TestClient(create_app(settings)).post("/api/run", json=body))[-1]


def test_statewide_destination_keeps_only_in_area_stops(settings):
    body = {**BODY, "location": "Oregon", "prompt": "Patagonia, Bon Iver and pottery"}
    res = _run(settings, _shifting(lambda p, i: i % 2 == 1), body)
    assert res["type"] == "result"
    stops = [res["cards"][s["id"]] for d in res["days"] for s in d["stops"]]
    assert stops and all(c["distance_km"] is not None and c["distance_km"] <= 25 for c in stops)
    assert all(leg["km"] <= 50 for d in res["days"] for leg in d["legs"])
    assert res["summary"]["km"] < 200  # the bug produced 1,924 km
    ev = next(s for s in res["trace"] if s["id"] == "evidence")
    assert ev["data"]["out_of_area"] > 0 and "left out" in ev["detail"]
    assert {c["id"]: c["passed"] for c in res["grounding"]["checks"]}["geography"] is True


def test_category_with_only_far_places_explains_itself(settings):
    museum_tags = set(CATEGORIES["culture"].tags)
    body = {**BODY, "location": "West Palm Beach, FL"}
    res = _run(settings, _shifting(lambda p, i: bool(museum_tags & set(p.get("filter.tags", "").split(",")))), body)
    assert res["type"] == "result"
    assert all(res["cards"][s["id"]]["category"] != "culture" for d in res["days"] for s in d["stops"])
    note = next(n for n in res["notes"] if "museums" in n.lower())
    assert note.startswith("Qloo returned ") and "too far away (more than 25 km)" in note


def test_everything_out_of_area_fails_honestly(settings):
    res = _run(settings, _shifting(lambda p, i: True), {**BODY, "location": "Oregon"})
    assert res["type"] == "error" and res["code"] == "out_of_area" and "Portland, OR" in res["message"]


def test_gate_rejects_impossible_coordinates_and_keeps_unknown():
    def cand(eid, lat, lon, km):
        c = Candidate(place=Place(entity_id=eid, name=eid, lat=lat, lon=lon), category="nature")
        c.distance_km = km
        return c
    keep, out = sustainability.gate_by_area(
        [cand("ok", 45.5, -122.6, 3), cand("far", 44.0, -121.3, 160), cand("swapped", -122.6, 45.5, None),
         cand("unknown", None, None, None)], {"lat": 45.5, "lon": -122.6}, 25)
    assert [c.id for c in keep] == ["ok", "unknown"] and {c.id for c in out} == {"far", "swapped"}


def test_grounding_flags_far_place_if_one_slips_through(settings, qloo_mock):
    res = events(TestClient(create_app(settings)).post("/api/run", json=BODY))[-1]
    cid = res["days"][0]["stops"][0]["id"]
    res["cards"][cid]["distance_km"] = 900.0
    g = grounding.validate(res, __import__("app.models", fromlist=["RunRequest"]).RunRequest(**BODY),
                           {k: c["name"] for k, c in res["cards"].items()}, res["seeds"])
    assert {c["id"]: c["passed"] for c in g["checks"]}["geography"] is False


def test_every_returned_place_is_accounted_for(settings):
    res = _run(settings, _shifting(lambda p, i: i % 3 == 0), {**BODY, "location": "Oregon"})
    disc = next(s for s in res["trace"] if s["id"] == "discovery")
    for stat in disc["data"]["per_category"].values():
        assert stat["returned"] == stat["kept"] + stat["dropped"] == stat["kept"] + sum(stat["why_dropped"].values())
