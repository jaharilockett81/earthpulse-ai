import pytest

from app.agents import planning
from app.agents.baseline import keyword_base, words
from app.agents.discovery import Candidate
from app.agents.taste import heuristic_interests, similar
from app.evidence.emissions import FACTORS, leg_estimate, trip_estimates
from app.models import RunRequest
from app.qloo.schemas import parse_places, parse_search, parse_tag_insights
from app.qloo.taxonomy import classify, is_blocked, low_impact_signals

from .conftest import place


# ---------------------------------------------------------------- emissions

def test_epa_co2e_factors_match_hub_table_10():
    assert FACTORS["car"].co2e_kg == pytest.approx(0.2986, abs=1e-4)
    assert FACTORS["bus"].co2e_kg == pytest.approx(0.0666, abs=1e-4)
    assert FACTORS["transit_rail"].co2e_kg == pytest.approx(0.0935, abs=1e-4)


def test_trip_estimates_round_trip_and_modes():
    t = trip_estimates(1.609344)  # exactly 1 mile each way
    car = next(m for m in t["modes"] if m["mode"] == "car")
    assert car["kg_co2e"] == round(2 * FACTORS["car"].co2e_kg, 2)
    assert {m["mode"] for m in t["modes"]} == {"car", "bus", "transit_rail", "bike", "walk"}
    assert t["source"]["url"].startswith("https://www.epa.gov/")


def test_trip_estimates_car_free_and_occupancy():
    assert "car" not in {m["mode"] for m in trip_estimates(5, car_free=True)["modes"]}
    solo = trip_estimates(8)["modes"][0]["kg_co2e"]
    four = trip_estimates(8, car_occupants=4)["modes"][0]["kg_co2e"]
    assert four == pytest.approx(solo / 4, abs=0.01)
    assert "walk" not in {m["mode"] for m in trip_estimates(8)["modes"]}
    assert "bike" not in {m["mode"] for m in trip_estimates(12)["modes"]}


def test_leg_estimate_walks_short_hops():
    assert leg_estimate(1.0)["mode"] == "walk"
    leg = leg_estimate(6.0)
    assert leg["mode"] == "bus" and leg["kg_co2e"] < leg["car_kg_co2e"]
    assert leg_estimate(6.0, car_free=True)["car_kg_co2e"] is None


# ---------------------------------------------------------------- schemas

def test_parse_places_is_tolerant_and_extracts_fields():
    body = {"results": {"entities": [
        place(price_level=2, address="1 Main St", keywords=[{"name": "vegan"}]),
        {"name": "no id"},
        "junk",
        place(eid="P2", name="Odd", price_level=9),
    ]}, "query": {"localities": {"filter": [{"entity_id": "L", "name": "Lisbon", "location": {"lat": 38.7, "lon": -9.1}}]}}}
    places, loc = parse_places(body)
    assert [p.entity_id for p in places] == ["P1", "P2"]
    assert places[0].price_level == 2 and places[0].keywords == ["vegan"] and places[0].affinity == 0.8
    assert places[1].price_level is None
    assert loc.name == "Lisbon" and loc.lat == 38.7


def test_parse_explainability_sorted():
    p = place()
    p["query"]["explainability"] = {"signal.interests.entities": [{"entity_id": "a", "score": 0.2}, {"entity_id": "b", "score": 0.9}]}
    places, _ = parse_places({"results": {"entities": [p]}})
    assert [c.entity_id for c in places[0].explainability] == ["b", "a"]


def test_parse_search_bare_list_and_nested():
    hit = {"entity_id": "E1", "name": "Amélie", "types": ["urn:entity:movie"]}
    assert parse_search({"results": [hit]})[0].kind == "movie"
    assert parse_search({"results": {"entities": [hit]}})[0].entity_id == "E1"
    assert parse_search({"oops": 1}) == []


def test_parse_tag_insights():
    out = parse_tag_insights({"results": {"tags": [{"tag_id": "t1", "name": "cozy", "query": {"affinity": 0.5}}, {"x": 1}]}})
    assert len(out) == 1 and out[0].affinity == 0.5


# ---------------------------------------------------------------- taxonomy

def _p(**kw):
    return parse_places({"results": {"entities": [place(**kw)]}})[0][0]


def test_classify_uses_own_tags():
    museum = _p(tags=[{"tag_id": "urn:tag:category:place:art_museum", "name": "Art museum"}])
    assert classify(museum, ["nature", "culture"]) == "culture"
    assert classify(museum, ["nature"]) is None


def test_blocklist():
    assert is_blocked(_p(name="First Bank", tags=[{"tag_id": "urn:tag:category:place:bank", "name": "Bank"}]))
    assert is_blocked(_p(name="KXYZ Radio", tags=[]))
    assert not is_blocked(_p())


def test_low_impact_signals_are_from_tags():
    p = _p(tags=[{"tag_id": "x:vegan", "name": "Vegan options"}, {"tag_id": "y", "name": "Loud"}])
    assert low_impact_signals(p) == ["Vegan options"]


# ---------------------------------------------------------------- taste helpers

def test_heuristic_interests():
    assert heuristic_interests("A weekend for someone who loves Amélie, Studio Ghibli and slow living") == \
        ["Amélie", "Studio Ghibli", "slow living"]
    assert heuristic_interests("Plan a day inspired by Wes Anderson and jazz in Chicago") == ["Wes Anderson", "jazz"]


def test_similar():
    assert similar("The Beatles", "Beatles") == 1.0
    assert similar("Amelie", "Totally Different") < 0.5


# ---------------------------------------------------------------- planning

def _cand(eid, aff, km, cat="nature", tags=None):
    c = Candidate(place=_p(eid=eid, name=eid, affinity=aff, tags=tags), category=cat)
    c.distance_km = km
    c.trip = trip_estimates(km)
    return c


def _req(**kw):
    base = dict(seeds=[{"name": "x"}], location="Lisbon", categories=["nature"], days=1)
    base.update(kw)
    return RunRequest(**base)


def test_distance_penalty_only_with_low_carbon_priority():
    c = _cand("a", 0.9, 11.0)
    planning.score(c, _req(priorities=["low_carbon_travel"]), 0.9)
    assert c.score_parts["distance_penalty"] == -0.2  # (11-1) * 0.02
    planning.score(c, _req(priorities=[]), 0.9)
    assert "distance_penalty" not in c.score_parts
    planning.score(c, _req(priorities=[], car_free=True), 0.9)
    assert c.score_parts["distance_penalty"] == -0.3


def test_boosts():
    c = _cand("a", 0.5, 1.0, tags=[{"tag_id": "urn:tag:category:place:park", "name": "Park"},
                                   {"tag_id": "x", "name": "Vegan cafe"}])
    planning.score(c, _req(priorities=["nature_time", "plant_forward"]), 0.5)
    assert c.score == pytest.approx(0.5 + planning.BOOST_NATURE + planning.BOOST_PLANT)


def test_lighter_swap_found_and_saving_computed():
    req = _req(priorities=[])
    far, near, worse = _cand("far", 0.90, 10.0), _cand("near", 0.87, 2.0), _cand("worse", 0.50, 1.0)
    for c in (far, near, worse):
        planning.score(c, req, c.place.affinity)
    pl = planning.plan(req, [far, near, worse], {"lat": 38.72, "lon": -9.14, "label": "x"})
    assert pl["chosen"]["nature"][0].id == "far"
    swap = pl["swaps"]["far"]
    assert swap["to_id"] == "near" and swap["km_closer"] == 8.0 and swap["kg_co2e_saved"] > 0


def test_low_carbon_ranking_prefers_close_near_equal():
    req = _req(priorities=["low_carbon_travel"])
    far, near = _cand("far", 0.90, 10.0), _cand("near", 0.87, 2.0)
    for c in (far, near):
        planning.score(c, req, c.place.affinity)
    assert planning.plan(req, [far, near], None)["chosen"]["nature"][0].id == "near"


# ---------------------------------------------------------------- baseline

def test_keyword_baseline():
    c = Candidate(place=_p(name="Jazz Garden", tags=[{"tag_id": "t", "name": "Live jazz"}]), category="nature")
    assert keyword_base(c, words(["jazz and gardens"])) == 1.0
    assert c.keyword_hits == ["garden", "jazz"]


# ---------------------------------------------------------------- request validation

def test_request_requires_taste_and_valid_categories():
    with pytest.raises(ValueError):
        RunRequest(location="Lisbon")
    with pytest.raises(ValueError):
        RunRequest(prompt="jazz", location="Lisbon", categories=["casinos"])
    r = RunRequest(prompt="jazz <script>", location="Lisbon", priorities=["low_carbon_travel", "bogus"])
    assert "<" not in r.prompt and r.priorities == ["low_carbon_travel"]


def test_similar_rejects_partial_title_matches():
    assert similar("botanical gardens", "Botanical Gardens of Peter the Great") < 0.72
    assert similar("Amelie", "Amélie") == 1.0


async def test_lowercase_concepts_try_tags_first(settings):
    import httpx
    import respx

    from app.agents.taste import _resolve_one
    from app.models import Seed
    from app.qloo.client import CallStats, QlooClient

    with respx.mock(base_url="https://hackathon.api.qloo.com", assert_all_called=False) as r:
        tags = r.get("/v2/tags").mock(return_value=httpx.Response(200, json={"results": {"tags": [
            {"id": "urn:tag:keyword:qloo:botanical_garden", "name": "botanical gardens"}]}}))
        search = r.get("/search").mock(return_value=httpx.Response(200, json={"results": []}))
        out = await _resolve_one(QlooClient(settings), Seed(name="botanical gardens"), CallStats())
    assert out["resolved_as"] == "tag" and tags.called and not search.called
