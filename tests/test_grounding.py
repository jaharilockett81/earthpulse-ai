import copy
import json

import httpx
import respx
from fastapi.testclient import TestClient

from app.agents import grounding
from app.main import create_app
from app.models import RunRequest
from app.qloo import fixtures

from .conftest import BASE
from .test_api import BODY, events


def _result(settings, qloo_mock):
    app = create_app(settings)
    res = events(TestClient(app).post("/api/run", json=BODY))[-1]
    assert res["type"] == "result" and res["grounding"]["passed"]
    names = {cid: c["name"] for cid, c in res["cards"].items()}
    return res, RunRequest(**BODY), names


def _ids(g):
    return {c["id"]: c["passed"] for c in g["checks"]}


def test_clean_run_passes_all_checks(settings, qloo_mock):
    res, _, _ = _result(settings, qloo_mock)
    assert all(_ids(res["grounding"]).values()) and len(res["grounding"]["checks"]) == 8


def test_detects_place_not_from_qloo(settings, qloo_mock):
    res, req, names = _result(settings, qloo_mock)
    bad = copy.deepcopy(res)
    cid = bad["days"][0]["stops"][0]["id"]
    bad["cards"][cid]["name"] = "Invented Café"
    assert _ids(grounding.validate(bad, req, names, res["seeds"]))["provenance"] is False


def test_detects_fake_interest_and_affinity(settings, qloo_mock):
    res, req, names = _result(settings, qloo_mock)
    bad = copy.deepcopy(res)
    c = next(c for c in bad["cards"].values() if c["affinity"] is not None)
    c["taste_links"] = [{"name": "Something you never said", "score": 0.9}]
    c["affinity"] = 0.11
    g = _ids(grounding.validate(bad, req, names, res["seeds"]))
    assert g["interests"] is False and g["affinity"] is False


def test_repairs_ungrounded_ai_sentence(settings, qloo_mock):
    res, req, names = _result(settings, qloo_mock)
    bad = copy.deepcopy(res)
    c = bad["cards"][bad["days"][0]["stops"][0]["id"]]
    c["why"] = {**c["why"], "text": "Rated 4.9 by 1200 locals.", "label": "ai_written"}
    g = grounding.validate(bad, req, names, res["seeds"])
    assert g["passed"] and g["repaired"] == 1
    assert c["why"]["label"] != "ai_written" and "4.9" not in c["why"]["text"]


def test_detects_tampered_emissions_and_constraints(settings, qloo_mock):
    res, req, names = _result(settings, qloo_mock)
    bad = copy.deepcopy(res)
    c = bad["cards"][bad["days"][0]["stops"][0]["id"]]
    c["trip"]["modes"][0]["kg_co2e"] = 0.01
    bad["summary"]["suggested_kg_co2e"] += 5
    c["category"] = "stay"
    g = _ids(grounding.validate(bad, req, names, res["seeds"]))
    assert g["arithmetic"] is False and g["constraints"] is False


def test_adaptation_requeries_thin_category_once(settings):
    """First page: 20 places that all fail the budget; the agent widens once and finds affordable ones."""
    calls = []

    def handler(req: httpx.Request):
        resp = fixtures.handler(req)
        p = req.url.params
        if p.get("filter.type") == "urn:entity:place" and "park" in p.get("filter.tags", ""):
            calls.append(int(p["take"]))
            body = json.loads(resp.content)
            ents = body["results"]["entities"]
            while len(ents) < int(p["take"]):
                ents.append({**ents[len(ents) % 13], "entity_id": f"X{len(ents)}-{p['take']}"})
            for i, e in enumerate(ents):
                e.setdefault("properties", {})["price_level"] = 4 if (p["take"] == "20" or i % 2) else 1
            return httpx.Response(200, json=body)
        return resp

    with respx.mock(base_url=BASE) as r:
        r.route().mock(side_effect=handler)
        res = events(TestClient(create_app(settings)).post("/api/run", json={**BODY, "budget": 1}))[-1]
    assert calls == [20, 50]
    stage = next(s for s in res["trace"] if s["id"] == "discovery")
    assert stage["data"]["per_category"]["nature"]["adapted"]["gained"] > 0
    assert "searched wider once" in stage["detail"]
    assert any(res["cards"][s["id"]]["category"] == "nature" for d in res["days"] for s in d["stops"])


def test_failure_drill_all_pass():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("drill", Path(__file__).parent.parent / "scripts" / "failure_drill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, _, fn in mod.SCENARIOS:
        ok, observed = fn()
        assert ok, f"{name}: {observed}"
