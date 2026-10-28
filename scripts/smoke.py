"""End-to-end smoke test against a running EarthPulse server (local or deployed).

    python scripts/smoke.py https://your-app.onrender.com

Checks health, autocomplete, a full streamed run and a comparison. Prints a short summary only;
it never writes Qloo response data to disk.
"""

from __future__ import annotations

import json
import sys
import time

import httpx

BODY = {
    "prompt": "A weekend for someone who loves Amélie, Studio Ghibli and slow living",
    "location": "Lisbon",
    "categories": ["nature", "coffee", "culture", "dining"],
    "priorities": ["low_carbon_travel"],
}


def stream(c: httpx.Client, path: str, body: dict) -> list[dict]:
    evs = []
    with c.stream("POST", path, json=body, timeout=120) as r:
        if r.status_code != 200:
            r.read()
            fail(f"{path} -> HTTP {r.status_code}: {r.text[:200]}")
        for line in r.iter_lines():
            if line.strip():
                ev = json.loads(line)
                evs.append(ev)
                if ev["type"] == "stage" and ev["stage"]["status"] != "running":
                    st = ev["stage"]
                    print(f"   {st['status']:>7}  {st['name']:<38} {st['ms']:>6} ms  {st['detail']}")
    return evs


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main(base: str) -> None:
    with httpx.Client(base_url=base.rstrip("/"), timeout=30) as c:
        h = c.get("/api/health").json()
        print(f"health: qloo_configured={h['qloo_configured']} llm={h['llm_configured']} fixtures={h['fixtures']}")
        if not h["qloo_configured"] and not h["fixtures"]:
            fail("QLOO_API_KEY is not set on the server")
        s = c.get("/api/search", params={"q": "Amélie"})
        print(f"search: HTTP {s.status_code}, {len(s.json().get('results', []))} results")
        if s.status_code != 200:
            fail(f"search failed: {s.text[:200]}")
        t = time.monotonic()
        print("run:")
        res = stream(c, "/api/run", BODY)[-1]
        if res["type"] != "result":
            fail(f"run ended with {res}")
        sm = res["summary"]
        print(f"run: {sm['stops']} stops, {sm['km']} km, {sm['suggested_kg_co2e']} kg vs car {sm['car_kg_co2e']} kg, "
              f"{sm['swaps']} swaps, qloo calls {res['stats']}, {time.monotonic() - t:.1f}s")
        if res["fixtures"]:
            print("WARNING: server is serving SYNTHETIC fixtures, not Qloo")
        print("compare:")
        cmp = stream(c, "/api/compare", BODY)[-1]
        if cmp["type"] != "compare":
            fail(f"compare ended with {cmp}")
        print(f"compare: overlap {cmp['overlap']}, metrics {cmp['metrics']}")
    print("OK")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000")
