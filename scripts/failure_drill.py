"""Deliberate failure drill: break Qloo (and the LLM) on purpose and check EarthPulse fails honestly.

    python scripts/failure_drill.py                  # print the table
    python scripts/failure_drill.py --out docs/FAILURE_DRILL.md

Every scenario runs the real FastAPI app in-process. Qloo is replaced by a mock (synthetic data from
app/qloo/fixtures.py with a fault injected), so this is repeatable and needs no key. The point is
behaviour: no fake data on failure, partial outages degrade gracefully, ungrounded AI text is refused.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import respx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.qloo import fixtures  # noqa: E402

BASE = "https://hackathon.api.qloo.com"
BODY = {"prompt": "Studio Ghibli, botanical gardens and independent coffee", "location": "Kyoto",
        "categories": ["nature", "coffee", "culture", "dining"], "priorities": ["low_carbon_travel"]}


def _settings(**kw) -> Settings:
    base = dict(qloo_api_key="drill-key", qloo_max_rps=1000, anthropic_api_key="", environment="test",
                runs_per_hour_per_ip=1000)
    base.update(kw)
    return Settings(**base)


def _is_places(req: httpx.Request) -> bool:
    return req.url.path == "/v2/insights" and req.url.params.get("filter.type") == "urn:entity:place"


def run(handler, body=BODY, settings=None, llm=None) -> list[dict]:
    with respx.mock(assert_all_called=False) as r:
        r.route(host="hackathon.api.qloo.com").mock(side_effect=handler)
        if llm is not None:
            r.post("https://api.anthropic.com/v1/messages").mock(side_effect=llm)
        resp = TestClient(create_app(settings or _settings())).post("/api/run", json=body)
    return [json.loads(x) for x in resp.text.splitlines() if x.strip()]


def last(evs):
    return evs[-1]


# ----------------------------------------------------------------------------- scenarios

def s_rate_limit():
    evs = run(lambda req: httpx.Response(429, headers={"retry-after": "0"}))
    e = last(evs)
    return e.get("code") == "qloo_rate_limited" and not any(x["type"] == "result" for x in evs), e.get("message")


def s_timeout():
    def h(req):
        raise httpx.ReadTimeout("drill")
    e = last(run(h))
    return e.get("code") == "qloo_timeout", e.get("message")


def s_auth():
    e = last(run(lambda req: httpx.Response(401)))
    return e.get("code") == "qloo_auth", e.get("message")


def s_unknown_interest():
    def h(req):
        if req.url.path == "/search":
            return httpx.Response(200, json={"results": []})
        if req.url.path == "/v2/tags":
            return httpx.Response(200, json={"results": {"tags": []}})
        return fixtures.handler(req)
    e = last(run(h, body={**BODY, "prompt": "zzqxv flimflam"}))
    return e.get("code") == "no_match", e.get("message")


def s_empty_city():
    def h(req):
        if _is_places(req):
            return httpx.Response(200, json={"results": {"entities": []}})
        return fixtures.handler(req)
    e = last(run(h, body={**BODY, "location": "Middle of the Ocean"}))
    return e.get("code") == "no_places", e.get("message")


def s_partial_outage():
    def h(req):
        if _is_places(req) and "cafe" in req.url.params.get("filter.tags", ""):
            return httpx.Response(503)
        return fixtures.handler(req)
    e = last(run(h))
    ok = e["type"] == "result" and any("Cafés" in n for n in e["notes"]) and \
        all(e["cards"][s["id"]]["category"] != "coffee" for d in e["days"] for s in d["stops"])
    return ok, f"plan still built ({e.get('summary', {}).get('stops')} stops); note: " + \
        next((n for n in e.get("notes", []) if "Cafés" in n), "none")


def s_missing_coordinates():
    def h(req):
        resp = fixtures.handler(req)
        if _is_places(req):
            body = json.loads(resp.content)
            for ent in body["results"]["entities"]:
                ent.pop("location", None)
            return httpx.Response(200, json=body)
        return resp
    e = last(run(h))
    ok = e["type"] == "result" and all(
        any(c["label"] == "not_verified" and "Distance" in c["text"] for c in e["cards"][s["id"]]["claims"])
        for d in e["days"] for s in d["stops"]) and e["summary"]["complete"] is False
    nv = sum(1 for d in e.get("days", []) for s in d["stops"]
             if any(c["label"] == "not_verified" and "Distance" in c["text"] for c in e["cards"][s["id"]]["claims"]))
    return ok, f"{nv} stops labelled 'Distance and emissions not available'; plan marked incomplete"


def s_ungrounded_ai_text():
    # The LLM claims ratings and prices that are not in the facts; validation must refuse them.
    def h(req):
        return fixtures.handler(req)
    seen = {"items": 0}

    def llm(req: httpx.Request) -> httpx.Response:
        user = json.loads(req.content)["messages"][0]["content"]
        ids = json.loads(user)["items"] if user.strip().endswith("}") else []
        seen["items"] = len(ids)
        items = [{"id": it["id"], "text": f"A gem rated 4.9 stars with mains from $12 near {it['name']}."} for it in ids]
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps({"items": items})}]})
    e = last(run(h, settings=_settings(anthropic_api_key="drill-llm"), llm=llm))
    ai = sum(1 for c in e.get("cards", {}).values() if c["why"]["label"] == "ai_written")
    ok = e["type"] == "result" and seen["items"] > 0 and ai == 0
    return ok, f"LLM rewrote {seen['items']} cards with invented numbers; {ai} accepted; explanation_source={e.get('explanation_source')}"


def s_rate_limit_then_recover():
    state = {"n": 0}

    def h(req):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return fixtures.handler(req)
    e = last(run(h))
    return e["type"] == "result", f"{state['n']} Qloo calls incl. 1 retried 429; run completed with {e.get('summary', {}).get('stops')} stops"


SCENARIOS = [
    ("Qloo rate-limits every call (429)", "Honest 'rate-limited' error, no plan, no fake data", s_rate_limit),
    ("Single 429 then recovery", "Bounded retry, run completes", s_rate_limit_then_recover),
    ("Qloo times out", "Honest timeout error", s_timeout),
    ("Invalid API key (401)", "Honest auth error", s_auth),
    ("Interest Qloo doesn't know", "Clear 'not recognised' message", s_unknown_interest),
    ("City with no places", "Clear 'no places' message", s_empty_city),
    ("One category's Qloo call fails (503)", "Plan built from the rest, outage noted", s_partial_outage),
    ("Places missing coordinates", "Distance/CO2e labelled Not verified", s_missing_coordinates),
    ("LLM invents ratings and prices", "AI text rejected by grounding validation", s_ungrounded_ai_text),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    rows, fails = [], 0
    for name, expect, fn in SCENARIOS:
        t = time.monotonic()
        try:
            ok, observed = fn()
        except Exception as exc:  # noqa: BLE001
            ok, observed = False, f"crashed: {type(exc).__name__}: {exc}"
        fails += not ok
        rows.append(f"| {name} | {expect} | {observed} | {'PASS' if ok else 'FAIL'} | {int((time.monotonic() - t) * 1000)} ms |")
    md = "\n".join([
        "# Failure drill", "",
        "Generated by `python scripts/failure_drill.py`. Each scenario runs the real app with Qloo mocked and one fault "
        "injected (synthetic data, no key). The Observed column is built from the app's actual response for that run.", "",
        "| Scenario | Expected | Observed | Result | Time |", "|---|---|---|---|---|", *rows, "",
        f"**{len(SCENARIOS) - fails}/{len(SCENARIOS)} passed.**", ""])
    if a.out:
        Path(a.out).write_text(md)
        print(f"wrote {a.out}")
    print(md)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
