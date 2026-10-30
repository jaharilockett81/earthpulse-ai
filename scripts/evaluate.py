"""Reproducible three-arm ablation over fixed test personas.

    python scripts/evaluate.py --url https://earthpulse-ai-plos.onrender.com --out docs/eval.md --json eval.json
    QLOO_API_KEY=... python scripts/evaluate.py --out docs/eval.md       # in-process, live Qloo
    python scripts/evaluate.py --fixtures                                 # synthetic dry run, no key

Arms, all on the same Qloo place directory, city, categories, filters, 25 km area and carbon rules:
  qloo       ranked by Qloo taste affinity for the user's interests
  baseline   no taste signals; ranked by keyword overlap with the user's words
  footprint  no taste signals; ranked by distance from the start plus lower-impact tags

Aggregate metrics only: no place names or other Qloo response data are written, per Qloo's terms.
Personas are invented test inputs, not real users. Exits 1 if any arm fails grounding (which includes
the geography check) or a persona errors, so it can gate a release.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import statistics
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import orchestrator  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm import LLM  # noqa: E402
from app.models import RunRequest  # noqa: E402
from app.qloo import fixtures  # noqa: E402
from app.qloo.client import QlooClient, QlooError  # noqa: E402

PERSONAS = [
    {"id": "P1 Ghibli naturalist", "prompt": "Studio Ghibli, Japanese architecture, botanical gardens, wildlife photography",
     "location": "Kyoto", "categories": ["nature", "culture", "coffee", "dining"]},
    {"id": "P2 Vinyl & jazz", "prompt": "Miles Davis, Blue Note Records, Haruki Murakami",
     "location": "Chicago", "categories": ["live_music", "books_music", "coffee", "dining"]},
    {"id": "P3 Slow-living reader", "prompt": "Amélie, slow living, Sally Rooney",
     "location": "Lisbon", "categories": ["coffee", "books_music", "nature", "culture"]},
    {"id": "P4 Outdoor maker", "prompt": "Patagonia, Bon Iver, pottery",
     "location": "Portland, OR", "categories": ["nature", "makers", "coffee", "dining"]},
    {"id": "P5 Design lover", "prompt": "Wes Anderson, Bauhaus, Kinfolk magazine",
     "location": "Copenhagen", "categories": ["culture", "coffee", "makers", "dining"]},
]
ARMS = ["qloo", "baseline", "footprint"]
KEYS = ["theme_match_rate", "keyword_match_rate", "categories", "tag_diversity", "avg_km", "km",
        "suggested_kg_co2e", "distance_evidence_rate", "lower_impact_signal_rate", "ms"]
LABELS = {"theme_match_rate": "Share sharing a theme with the Qloo taste portrait (favours Qloo)",
          "keyword_match_rate": "Share whose name/tags contain the user's words (favours keyword)",
          "categories": "Distinct categories", "tag_diversity": "Tag diversity (unique ÷ total)",
          "avg_km": "Average straight-line distance from start (km)", "km": "Planned travel, straight-line (km)",
          "suggested_kg_co2e": "Planned CO2e, walking + transit (kg)",
          "distance_evidence_rate": "Share with distance + CO2e evidence",
          "lower_impact_signal_rate": "Share with a lower-impact Qloo tag", "ms": "Pipeline time per list (ms)"}


def _row(p: dict, cmp: dict) -> dict:
    matched = sum(1 for s in cmp["seeds"] if s["resolved_as"] in ("entity", "tag"))
    return {"id": p["id"], "matched": f"{matched}/{len(cmp['seeds'])}", "overlap": cmp["overlap"],
            "overlap_footprint": cmp["overlap_footprint"], "items": cmp["items"], "metrics": cmp["metrics"],
            "grounding": cmp["grounding"], "calls": cmp["stats"]["network_calls"]}


async def evaluate_local(use_fixtures: bool) -> list[dict]:
    settings = get_settings()
    if use_fixtures:
        settings = dataclasses.replace(settings, qloo_api_key="synthetic", qloo_max_rps=1000)
        client = QlooClient(settings, transport=fixtures.transport())
    elif not settings.qloo_configured:
        sys.exit("QLOO_API_KEY is not set (pass --url to evaluate a deployment, or --fixtures for a dry run).")
    else:
        client = QlooClient(settings)
    llm = LLM(dataclasses.replace(settings, anthropic_api_key=""))  # rules only: reproducible
    rows = []
    try:
        for p in PERSONAS:
            req = RunRequest(prompt=p["prompt"], location=p["location"], categories=p["categories"],
                             priorities=["low_carbon_travel"], days=2)
            try:
                cmp = await orchestrator.compare(req, client=client, llm=llm, settings=settings)
            except (QlooError, orchestrator.StageFailed) as e:
                rows.append({"id": p["id"], "error": getattr(e, "user_message", None) or e.message})
                continue
            rows.append(_row(p, {**cmp, "items": len(cmp["lists"]["A"])}))
    finally:
        await client.aclose()
    return rows


def evaluate_url(base: str) -> list[dict]:
    rows = []
    with httpx.Client(base_url=base.rstrip("/"), timeout=120) as c:
        for p in PERSONAS:
            r = c.get("/api/check", params={"prompt": p["prompt"], "location": p["location"], "days": 2,
                                            "categories": ",".join(p["categories"]), "compare": "true"})
            j = r.json()
            if r.status_code != 200 or not j.get("ok"):
                rows.append({"id": p["id"], "error": j.get("message") or f"HTTP {r.status_code}"})
                continue
            if j.get("fixtures"):
                sys.exit("The deployment is serving synthetic fixtures, not Qloo. Refusing to report it as live.")
            rows.append(_row(p, j))
    return rows


def aggregate(rows: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]
    return {k: {a: round(statistics.mean(r["metrics"][a][k] for r in ok), 3) if ok else None for a in ARMS}
            for k in KEYS}


def render(rows: list[dict], agg: dict, source: str, synthetic: bool) -> str:
    when = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = ["# Evaluation: Qloo taste vs. keyword vs. footprint-only", ""]
    if synthetic:
        out += ["> **SYNTHETIC DRY RUN.** Generated from `app/qloo/fixtures.py`, not Qloo. These numbers say nothing "
                "about Qloo; they only show the harness works.", ""]
    out += [f"Run: {when}. Source: {source}. {len(PERSONAS)} invented personas, top 6 places per arm, 2-day plans.", "",
            "## Averages over personas", "", "| Metric | Qloo | Keyword | Footprint |", "|---|---|---|---|"]
    out += [f"| {LABELS[k]} | {agg[k]['qloo']} | {agg[k]['baseline']} | {agg[k]['footprint']} |" for k in KEYS]
    out += ["", "## Per persona", "", "| Persona | Matched | Overlap Q∩K | Overlap Q∩F | Theme Q/K/F | Avg km Q/K/F | "
            "Plan kg Q/K/F | Qloo calls |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            out.append(f"| {r['id']} | error: {r['error']} | | | | | | |")
            continue
        m = r["metrics"]
        f = lambda k: "/".join(str(m[a][k]) for a in ARMS)  # noqa: E731
        out.append(f"| {r['id']} | {r['matched']} | {r['overlap']}/{r['items']} | {r['overlap_footprint']}/{r['items']} | "
                   f"{f('theme_match_rate')} | {f('avg_km')} | {f('suggested_kg_co2e')} | {r['calls']} |")
    out += ["", "Neither automatic relevance proxy is neutral; the Comparison Lab's blind ratings are the human test. "
            "No significance testing: five personas is a smoke-level sample.", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="evaluate a deployment through its /api/check endpoint")
    ap.add_argument("--fixtures", action="store_true", help="synthetic dry run, no Qloo key needed")
    ap.add_argument("--out", help="write markdown here instead of stdout")
    ap.add_argument("--json", help="also write the machine-readable report here")
    a = ap.parse_args()
    rows = evaluate_url(a.url) if a.url else asyncio.run(evaluate_local(a.fixtures))
    agg = aggregate(rows)
    md = render(rows, agg, a.url or ("fixtures" if a.fixtures else "in-process, live Qloo"), a.fixtures)
    if a.json:
        Path(a.json).write_text(json.dumps({"rows": rows, "averages": agg, "synthetic": a.fixtures}, indent=2))
    if a.out:
        Path(a.out).write_text(md)
        print(f"wrote {a.out}")
    else:
        print(md)
    bad = [r["id"] for r in rows if "error" in r or not all(r["grounding"].values())]
    if bad:
        print(f"FAILED: {', '.join(bad)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
