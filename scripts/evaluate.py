"""Reproducible Qloo-vs-baseline evaluation over fixed test personas.

    QLOO_API_KEY=... python scripts/evaluate.py --out docs/EVALUATION.md      # live Qloo
    python scripts/evaluate.py --fixtures                                     # synthetic dry run

For each persona it runs the comparison pipeline (same city, categories, filters and carbon rules;
one list ranked by Qloo taste signals, one by keyword overlap) and reports measured, aggregate
metrics only. No place names or other Qloo response data are written, per Qloo's terms.
Personas are invented test inputs, not real users.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import statistics
import sys
from pathlib import Path

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
KEYS = ["theme_match_rate", "keyword_match_rate", "categories", "tag_diversity", "avg_km",
        "distance_evidence_rate", "lower_impact_signal_rate", "ms"]


async def evaluate(use_fixtures: bool) -> tuple[list[dict], dict]:
    settings = get_settings()
    if use_fixtures:
        settings = dataclasses.replace(settings, qloo_api_key="synthetic", qloo_max_rps=1000)
        client = QlooClient(settings, transport=fixtures.transport())
    elif not settings.qloo_configured:
        sys.exit("QLOO_API_KEY is not set (or pass --fixtures for a synthetic dry run).")
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
            except QlooError as e:
                rows.append({"id": p["id"], "error": e.user_message})
                continue
            matched = sum(1 for s in cmp["seeds"] if s["resolved_as"] in ("entity", "tag"))
            rows.append({"id": p["id"], "matched": f"{matched}/{len(cmp['seeds'])}", "overlap": cmp["overlap"],
                         "items": len(cmp["lists"]["A"]), "qloo": cmp["metrics"]["qloo"],
                         "baseline": cmp["metrics"]["baseline"], "calls": cmp["stats"]["network_calls"]})
    finally:
        await client.aclose()
    ok = [r for r in rows if "error" not in r]
    agg = {k: {m: round(statistics.mean(r[m][k] for r in ok if r[m][k] is not None), 3) if ok else None
               for m in ("qloo", "baseline")} for k in KEYS}
    return rows, agg


def render(rows: list[dict], agg: dict, use_fixtures: bool) -> str:
    when = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = ["# Evaluation: Qloo taste signals vs. keyword baseline", ""]
    if use_fixtures:
        out += ["> **SYNTHETIC DRY RUN.** Generated from `app/qloo/fixtures.py`, not Qloo. These numbers say nothing "
                "about Qloo; they only show the harness works.", ""]
    out += [f"Run: {when}. Personas are invented test inputs. Each list is the top {rows[0].get('items', 6) if rows else 6} "
            "places, same city/categories/filters/carbon rules; only the ranking signal differs. "
            "Aggregate metrics only (no Qloo response data).", "",
            "## Averages over personas", "", "| Metric | Qloo | Baseline |", "|---|---|---|"]
    labels = {"theme_match_rate": "Share sharing a theme with the Qloo taste portrait (favours Qloo)",
              "keyword_match_rate": "Share whose name/tags contain the user's words (favours baseline)",
              "categories": "Distinct categories", "tag_diversity": "Tag diversity (unique ÷ total)",
              "avg_km": "Average distance from start (km)", "distance_evidence_rate": "Share with distance + CO2e evidence",
              "lower_impact_signal_rate": "Share with a lower-impact Qloo tag", "ms": "Pipeline time per list (ms)"}
    for k in KEYS:
        out.append(f"| {labels[k]} | {agg[k]['qloo']} | {agg[k]['baseline']} |")
    out += ["", "## Per persona", "", "| Persona | Interests matched | Overlap | Theme match Q/B | Keyword match Q/B | "
            "Avg km Q/B | Qloo calls |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            out.append(f"| {r['id']} | error: {r['error']} | | | | | |")
            continue
        q, b = r["qloo"], r["baseline"]
        out.append(f"| {r['id']} | {r['matched']} | {r['overlap']}/{r['items']} | {q['theme_match_rate']}/{b['theme_match_rate']} | "
                   f"{q['keyword_match_rate']}/{b['keyword_match_rate']} | {q['avg_km']}/{b['avg_km']} | {r['calls']} |")
    out += ["", "## How to read this", "",
            "- Neither automatic relevance proxy is neutral, so both are reported. The blind ratings in the comparison "
            "lab are the human test.",
            "- Lower overlap means Qloo's taste signal changes which places surface, not just their order.",
            "- Pipeline time includes Qloo throttling (≤4 req/s) and caching; the baseline reuses cached search results.",
            "- Reproduce with `python scripts/evaluate.py --out docs/EVALUATION.md`.", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", action="store_true", help="synthetic dry run, no Qloo key needed")
    ap.add_argument("--out", help="write markdown here instead of stdout")
    a = ap.parse_args()
    rows, agg = asyncio.run(evaluate(a.fixtures))
    md = render(rows, agg, a.fixtures)
    if a.out:
        Path(a.out).write_text(md)
        print(f"wrote {a.out}")
    else:
        print(md)


if __name__ == "__main__":
    main()
