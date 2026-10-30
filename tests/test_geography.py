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


def test_spread_out_qloo_results_keep_only_in_area_stops(settings):
    # The geocoder can't confirm this name, so Qloo's own name lookup is used and the area gate filters after.
    body = {**BODY, "location": "Springfield", "prompt": "Patagonia, Bon Iver and pottery"}
    res = _run(settings, _shifting(lambda p, i: i % 2 == 1), body)
    assert res["type"] == "result"
    stops = [res["cards"][s["id"]] for d in res["days"] for s in d["stops"]]
    assert stops and all(c["distance_km"] is not None and c["distance_km"] <= 25 for c in stops)
    assert all(leg["km"] <= 50 for d in res["days"] for leg in d["legs"])
    assert res["summary"]["km"] < 200  # the Oregon bug produced 1,924 km
    ev = next(s for s in res["trace"] if s["id"] == "evidence")
    assert ev["data"]["out_of_area"] > 0 and "left out" in ev["detail"]
    assert {c["id"]: c["passed"] for c in res["grounding"]["checks"]}["geography"] is True


def test_category_with_only_far_places_explains_itself(settings):
    museum_tags = set(CATEGORIES["culture"].tags)
    body = {**BODY, "location": "West Palm Beach, FL"}
    res = _run(settings, _shifting(lambda p, i: bool(museum_tags & set(p.get("filter.tags", "").split(",")))), body)
    assert res["type"] == "result"
    assert all(res["cards"][s["id"]]["category"] != "culture" for d in res["days"] for s in d["stops"])
    note = next(n for n in res["notes"] if n.startswith("Qloo returned ") and "museums" in n.lower())
    assert "too far away (more than 25 km)" in note


def test_zero_eligible_venues_fails_honestly_with_counts_and_an_offer(settings):
    res = _run(settings, _shifting(lambda p, i: True), {**BODY, "location": "Springfield"})
    assert res["type"] == "error" and res["code"] == "out_of_area"
    assert res["suggestions"] == [{"label": "Search within 40 km", "patch": {"radius_km": 40}}]
    assert res["coverage"]["kept"] == 0 and res["coverage"]["why_dropped"]["out_of_area"] > 0


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
    res = _run(settings, _shifting(lambda p, i: i % 3 == 0), {**BODY, "location": "Springfield"})
    disc = next(s for s in res["trace"] if s["id"] == "discovery")
    for stat in disc["data"]["per_category"].values():
        assert stat["returned"] == stat["kept"] + stat["dropped"] == stat["kept"] + sum(stat["why_dropped"].values())



# ---------------------------------------------------------------- destination resolution (Florida regression)

def _count_qloo(settings, body):
    calls = []

    def handler(req):
        calls.append(req)
        return fixtures.handler(req)
    return _run(settings, handler, body), calls


def test_state_only_destination_asks_for_a_city_before_any_qloo_call(settings):
    for loc in ("Florida", "florida", "Florida, USA", "Oregon"):
        res, calls = _count_qloo(settings, {**BODY, "location": loc})
        assert res["type"] == "error" and res["code"] == "needs_city", loc
        assert calls == []
    res, _ = _count_qloo(settings, {**BODY, "location": "Florida"})
    labels = [s["label"] for s in res["suggestions"]]
    assert "West Palm Beach" in labels and res["suggestions"][0]["patch"] == {"location": labels[0]}


def test_city_names_that_contain_a_region_are_not_refused():
    from app.evidence.destination import region_of
    assert region_of("West Palm Beach, FL") is None and region_of("Portland, OR") is None
    assert region_of("New York") is None and region_of("Washington, DC") is None
    assert region_of("Oregon")[1][0] == "Portland, OR"


async def test_geocoder_mismatch_is_not_used_as_a_substitute(monkeypatch):
    from app.evidence import destination

    async def floridablanca(q, url, **k):  # what Open-Meteo really returns for "Florida"
        return {"name": "Floridablanca", "lat": 7.06, "lon": -73.09, "label": "Floridablanca, Santander, Colombia",
                "feature_code": "PPLA2"}

    async def a_state(q, url, **k):
        return {"name": "Narnia", "lat": 1.0, "lon": 1.0, "label": "Narnia", "feature_code": "ADM1"}

    monkeypatch.setattr(destination, "geocode", floridablanca)
    d = await destination.resolve("Floridia", "u")
    assert d["status"] == "unconfirmed" and "Floridablanca" in d["reason"]
    monkeypatch.setattr(destination, "geocode", a_state)
    assert (await destination.resolve("Narnia", "u"))["status"] == "unconfirmed"


def test_one_stop_itinerary_is_labelled_partial_with_named_legs(settings):
    keep_cafes = lambda p, i: not ("cafe" in p.get("filter.tags", "") and i == 0)  # noqa: E731
    body = {**BODY, "location": "Springfield", "categories": ["coffee", "culture"], "days": 2}
    res = _run(settings, _shifting(keep_cafes), body)
    s = res["summary"]
    assert res["type"] == "result" and s["stops"] == 1 and s["requested_stops"] == 4 and s["complete"] is False
    assert s["empty_days"] == [2]
    assert any(n.startswith("Partial plan: 1 of the 4 stops") for n in res["notes"])
    assert {"label": "Search within 40 km", "patch": {"radius_km": 40}} in res["suggestions"]
    day1, day2 = res["days"]
    assert day2["legs"] == [] and day2["totals"]["km"] == 0
    stop = res["cards"][day1["stops"][0]["id"]]
    out, back = day1["legs"]
    assert out["from"] == back["to"] == res["origin"]["label"] and out["to"] == back["from"] == stop["name"]
    assert out["distance_kind"] == "straight_line"
    assert abs(day1["totals"]["km"] - 2 * stop["distance_km"]) < 0.05  # one stop: out and back, nothing else


def test_thin_category_at_the_source_offers_a_wider_area(settings):
    def handler(req):
        resp = fixtures.handler(req)
        p = req.url.params
        if req.url.path == "/v2/insights" and p.get("filter.type") == "urn:entity:place" \
                and set(CATEGORIES["culture"].tags) & set(p.get("filter.tags", "").split(",")):
            body = json.loads(resp.content)
            body["results"]["entities"] = body["results"]["entities"][:1]
            return httpx.Response(200, json=body)
        return resp
    res = _run(settings, handler, {**BODY, "location": "Springfield", "categories": ["culture", "coffee"]})
    assert res["summary"]["complete"] is False
    assert res["suggestions"][0] == {"label": "Search within 40 km", "patch": {"radius_km": 40}}
