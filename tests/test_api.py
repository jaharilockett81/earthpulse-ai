import json

import httpx
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from .conftest import BASE


def events(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


BODY = {"prompt": "A weekend for someone who loves Amélie and slow living", "location": "Lisbon",
        "categories": ["nature", "coffee", "culture", "dining"], "priorities": ["low_carbon_travel"]}


def test_health_hides_secrets(settings):
    r = TestClient(create_app(settings)).get("/api/health")
    assert r.status_code == 200
    assert "test-key" not in r.text and r.json()["qloo_configured"] is True


def test_run_streams_all_stages_and_result(settings, qloo_mock):
    r = TestClient(create_app(settings)).post("/api/run", json=BODY)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    evs = events(r)
    done = [e["stage"]["id"] for e in evs if e["type"] == "stage" and e["stage"]["status"] == "done"]
    assert done == ["intent", "resolve", "portrait", "discovery", "evidence", "planning", "verification", "explanation", "bridge", "grounding"]
    res = evs[-1]
    assert res["type"] == "result"
    assert len(res["days"]) == 2 and res["summary"]["stops"] == 8
    for d in res["days"]:
        for s in d["stops"]:
            card = res["cards"][s["id"]]
            assert card["name"].startswith("[Synthetic]")
            assert "Bank" not in card["name"]
            assert card["trip"]["source"]["name"].startswith("U.S. EPA")
            assert all(ch["passed"] for ch in card["checks"] if ch["hard"])
            assert {c["label"] for c in card["claims"]} >= {"listed", "computed", "not_verified"}
    # Qloo calls carried the taste signal
    insight_calls = [c.request for c in qloo_mock.calls if c.request.url.path == "/v2/insights"
                     and c.request.url.params.get("filter.type") == "urn:entity:place"]
    assert insight_calls and all(c.url.params.get("signal.interests.entities") for c in insight_calls)


def test_step_free_filter_only_returns_tagged(settings, qloo_mock):
    res = events(TestClient(create_app(settings)).post("/api/run", json={**BODY, "step_free": True}))[-1]
    assert res["type"] == "result"
    assert all(res["cards"][s["id"]]["step_free"] for d in res["days"] for s in d["stops"])


def test_compare_is_blind_and_baseline_sends_no_taste(settings, qloo_mock):
    evs = events(TestClient(create_app(settings)).post("/api/compare", json=BODY))
    cmp = evs[-1]
    assert cmp["type"] == "compare"
    assert sorted(cmp["reveal"].values()) == ["baseline", "qloo"]
    assert cmp["lists"]["A"] and cmp["lists"]["B"]
    place_calls = [c.request for c in qloo_mock.calls if c.request.url.params.get("filter.type") == "urn:entity:place"]
    assert any("signal.interests.entities" not in c.url.params for c in place_calls)


def test_qloo_auth_failure_is_reported_honestly(settings):
    with respx.mock(base_url=BASE) as r:
        r.route().mock(return_value=httpx.Response(403))
        evs = events(TestClient(create_app(settings)).post("/api/run", json=BODY))
    assert evs[-1] == {"type": "error", "code": "qloo_auth", "message": "Qloo rejected this server's API key."}


def test_missing_key_reports_not_configured():
    evs = events(TestClient(create_app(Settings(qloo_api_key=""))).post("/api/run", json=BODY))
    assert evs[-1]["code"] == "qloo_not_configured"


def test_validation_error_is_readable(settings):
    r = TestClient(create_app(settings)).post("/api/run", json={"location": "Lisbon"})
    assert r.status_code == 422 and "favourite" in r.json()["error"]["message"]


def test_rate_limit(qloo_mock):
    s = Settings(qloo_api_key="k", qloo_max_rps=1000, runs_per_hour_per_ip=1)
    c = TestClient(create_app(s))
    assert c.post("/api/run", json=BODY).status_code == 200
    assert c.post("/api/run", json=BODY).status_code == 429


def test_search_autocomplete(settings, qloo_mock):
    r = TestClient(create_app(settings)).get("/api/search", params={"q": "amelie"})
    assert r.status_code == 200 and r.json()["results"][0]["kind"] == "movie"


def test_fixtures_refused_in_production():
    assert Settings(qloo_api_key="", dev_fixtures=True, environment="production").fixtures_active is False
    assert Settings(qloo_api_key="", dev_fixtures=True, environment="development").fixtures_active is True


def test_static_index_served(settings):
    r = TestClient(create_app(settings)).get("/")
    assert r.status_code == 200 and "EarthPulse" in r.text


def test_taste_bridge_respects_its_contract(settings, qloo_mock):
    from app.agents.bridge import MAX_HOP_KM

    picked = set(BODY["categories"])
    found_any = False
    for city in ["Lisbon", "Chicago", "Kyoto", "Austin"]:
        res = events(TestClient(create_app(settings)).post("/api/run", json={**BODY, "location": city}))[-1]
        planned = {s["id"] for d in res["days"] for s in d["stops"]}
        for b in res["bridges"]:
            found_any = True
            card = res["cards"][b["id"]]
            assert card["category"] not in picked and card["category"] != "stay"
            assert b["id"] not in planned and b["near_id"] in planned
            assert b["hop"]["km"] <= MAX_HOP_KM
            assert card["affinity"] >= b["affinity_floor"]
            assert all(ch["passed"] for ch in card["checks"] if ch["hard"])
    assert found_any


def test_baseline_mode_run_has_no_bridge_and_keyword_base(settings, qloo_mock):
    res = events(TestClient(create_app(settings)).post("/api/run", json={**BODY, "mode": "baseline"}))[-1]
    assert res["type"] == "result" and res["bridges"] == []
    assert all(res["cards"][s["id"]]["affinity"] is None for d in res["days"] for s in d["stops"])


def test_compare_metrics_are_measured(settings, qloo_mock):
    cmp = events(TestClient(create_app(settings)).post("/api/compare", json=BODY))[-1]
    for side in ("qloo", "baseline"):
        m = cmp["metrics"][side]
        assert {"theme_match_rate", "keyword_match_rate", "tag_diversity", "distance_evidence_rate",
                "lower_impact_signal_rate", "ms", "avg_km"} <= m.keys()
        assert 0 <= m["keyword_match_rate"] <= 1 and m["ms"] >= 0


def test_constraint_change_revises_plan(settings, qloo_mock):
    c = TestClient(create_app(settings))
    a = events(c.post("/api/run", json=BODY))[-1]
    b = events(c.post("/api/run", json={**BODY, "days": 1, "step_free": True}))[-1]
    assert len(b["days"]) == 1 and len(a["days"]) == 2
    assert all(b["cards"][s["id"]]["step_free"] for s in b["days"][0]["stops"])


def test_secret_never_leaks_into_stream_or_errors(settings):
    with respx.mock(base_url=BASE) as r:
        r.route().mock(return_value=httpx.Response(500, text="boom"))
        text = TestClient(create_app(settings)).post("/api/run", json=BODY).text
    assert "test-key" not in text and "qloo_unavailable" in text


def test_timeout_is_reported(settings):
    with respx.mock(base_url=BASE) as r:
        r.route().mock(side_effect=httpx.ReadTimeout("slow"))
        evs = events(TestClient(create_app(settings)).post("/api/run", json=BODY))
    assert evs[-1]["code"] == "qloo_timeout"


def test_evaluation_harness_runs_synthetic():
    import asyncio
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("evaluate", Path(__file__).parent.parent / "scripts" / "evaluate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows, agg = asyncio.run(mod.evaluate(use_fixtures=True))
    assert len(rows) == len(mod.PERSONAS) and all("error" not in r for r in rows)
    md = mod.render(rows, agg, True)
    assert "SYNTHETIC DRY RUN" in md and "[Synthetic]" not in md  # no place names in the report


def test_check_endpoint_condensed_run_and_compare(settings, qloo_mock):
    c = TestClient(create_app(settings))
    j = c.get("/api/check", params={"prompt": "Amélie and slow living", "location": "Lisbon"}).json()
    assert j["ok"] and j["grounding"]["passed"] and j["summary"]["stops"] == 8 and "test-key" not in str(j)
    j = c.get("/api/check", params={"prompt": "Amélie", "location": "Lisbon", "compare": "true"}).json()
    assert j["ok"] and "qloo" in j["metrics"] and "overlap" in j


def test_city_centre_prefers_geocoded_town_point(settings):
    from app.qloo import fixtures

    with respx.mock(assert_all_called=False) as r:
        r.route(host="hackathon.api.qloo.com").mock(side_effect=fixtures.handler)
        lat0, lon0 = fixtures._centroid("Lisbon")
        r.get(host="geocoding-api.open-meteo.com").mock(return_value=httpx.Response(200, json={"results": [
            {"name": "Lisbon", "latitude": lat0 + 0.05, "longitude": lon0, "admin1": "Lisbon", "country": "Portugal"}]}))
        res = events(TestClient(create_app(settings)).post("/api/run", json=BODY))[-1]
    assert res["origin"]["label"] == "Lisbon city centre" and res["origin"]["source"]["name"].startswith("Open-Meteo")
    assert abs(res["origin"]["lat"] - (lat0 + 0.05)) < 1e-9
