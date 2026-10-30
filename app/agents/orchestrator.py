"""Orchestrator: a fixed, deterministic 8-stage pipeline (no agent loops).

  1 intent        Taste Intelligence   free text / form -> interests
  2 resolve       Taste Intelligence   interests -> Qloo entities or taste tags
  3 portrait      Taste Intelligence   entities -> taste + ambience tags          (optional)
  4 discovery     Discovery            one Qloo place call per category
  5 evidence      Sustainability       origin, distances, EPA CO2e, low-impact signals
  6 planning      Planning             score, rank, day plan, lighter swaps
  7 verification  Verification         re-check stops, replace failures
  8 explanation   Explanation          grounded "why" per card (AI rewording optional)

Every stage is streamed to the UI as it starts and finishes.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from ..config import Settings
from ..evidence import destination
from ..llm import LLM
from ..models import RunRequest
from ..qloo.client import CallStats, QlooClient
from ..qloo.taxonomy import CATEGORIES
from . import baseline, bridge, discovery, grounding, explanation, planning, sustainability, taste, verification
from .trace import Emit, StageFailed, Trace


@dataclass
class Context:
    req: RunRequest
    seeds: list[dict] = field(default_factory=list)
    portrait: dict = field(default_factory=lambda: {"taste": [], "ambience": []})
    intent_source: str = "form"
    notes: list[str] = field(default_factory=list)
    destination: dict | None = None

    @property
    def center(self) -> dict | None:
        return self.destination if self.destination and self.destination.get("status") == "city" else None

    @property
    def seed_ids(self) -> list[str]:
        return [s["entity_id"] for s in self.seeds if s.get("entity_id")]

    @property
    def seed_tags(self) -> list[str]:
        return [s["tag_id"] for s in self.seeds if s.get("tag_id")]

    def user_words(self) -> set[str]:
        return baseline.words([s["input"] for s in self.seeds] + [self.req.prompt or ""])


async def resolve_destination(ctx: Context, settings: Settings, trace: Trace, geo_transport=None) -> None:
    """Stage 0: the destination must be a city. Runs before any Qloo call."""
    req = ctx.req
    async with trace.stage("destination", "Find your destination", "Geography") as st:
        if settings.fixtures_active and not destination.region_of(req.location):
            ctx.destination = {"status": "synthetic", "input": req.location}
            st.detail = "Synthetic mode: using the synthetic city"
            return
        d = await destination.resolve(req.location, settings.geocode_url, transport=geo_transport)
        ctx.destination = d
        if d["status"] == "region":
            raise StageFailed(
                "needs_city", f"“{d['name']}” is a whole region, and EarthPulse plans walkable city days. "
                              f"Pick a city, for example {', '.join(d['suggestions'][:-1])} or {d['suggestions'][-1]}."
                if len(d["suggestions"]) > 1 else f"“{d['name']}” is a whole region. Pick a city, for example "
                                                  f"{d['suggestions'][0]}.",
                suggestions=[{"label": c, "patch": {"location": c}} for c in d["suggestions"]])
        if d["status"] == "city":
            st.detail = (f"{d['label']} ({d['lat']:.3f}, {d['lon']:.3f}) · searching within {req.radius_km} km "
                         f"of the city centre")
        else:
            st.detail = f"Couldn't confirm “{req.location}” on the map ({d['reason']}); using Qloo's match for the name"
            ctx.notes.append(f"Couldn't confirm “{req.location}” as a city on the map ({d['reason']}). Places come from "
                             f"Qloo's own match for the name and are limited to {req.radius_km} km from Qloo's point "
                             f"for it.")
        st.data = {k: d.get(k) for k in ("status", "name", "admin1", "country", "country_code", "feature_code",
                                          "lat", "lon", "reason")}


async def prepare(req: RunRequest, client: QlooClient, llm: LLM, trace: Trace, stats: CallStats,
                  settings: Settings | None = None, geo_transport=None) -> Context:
    ctx = Context(req=req)
    if settings is not None:
        await resolve_destination(ctx, settings, trace, geo_transport)
    async with trace.stage("intent", "Understand your request", "Taste Intelligence") as st:
        seeds, ctx.intent_source = await taste.parse_intent(req, llm)
        if not seeds:
            raise StageFailed("no_interests", "We couldn't find any interests in that request. Try naming a film, "
                                              "artist, book or place you love.")
        st.detail = f"{len(seeds)} interest{'s' if len(seeds) != 1 else ''} from " + \
            {"form": "your picks", "ai": "your words (AI-parsed)", "rules": "your words"}[ctx.intent_source]
        st.data = {"interests": [s.name for s in seeds], "source": ctx.intent_source}
    ctx.seeds = seeds_dicts = []
    async with trace.stage("resolve", "Match interests to Qloo", "Taste Intelligence") as st:
        seeds_dicts.extend(await taste.resolve_seeds(client, seeds, stats))
        ok = [s for s in seeds_dicts if s["resolved_as"] in ("entity", "tag")]
        missed = [s["input"] for s in seeds_dicts if s["resolved_as"] not in ("entity", "tag")]
        if not ok:
            raise StageFailed("no_match", "Qloo didn't recognise any of those interests. Try a more specific title "
                                          "or name.")
        if missed:
            ctx.notes.append(f"Not matched in Qloo: {', '.join(missed)}.")
        approx = [s["name"] for s in ok if s.get("approximate")]
        if approx:
            ctx.notes.append(f"Closest Qloo match used for: {', '.join(approx)}.")
        st.detail = f"{len(ok)} of {len(seeds_dicts)} matched"
        st.data = {"matched": [{"name": s["name"], "as": s["resolved_as"], "kind": s["kind"]} for s in ok],
                   "missed": missed}
    async with trace.stage("portrait", "Build your taste portrait", "Taste Intelligence", required=False) as st:
        if ctx.seed_ids:
            ctx.portrait = await taste.taste_portrait(client, ctx.seed_ids, stats)
            st.detail = f"{len(ctx.portrait['taste'])} taste themes, {len(ctx.portrait['ambience'])} vibes"
        else:
            st.status = "skipped"
            st.detail = "Only taste tags matched; no entities to profile"
        st.data = {"themes": [t["name"] for t in ctx.portrait["taste"][:8]]}
    return ctx


async def run_mode(ctx: Context, mode: str, client: QlooClient, llm: LLM, settings: Settings, trace: Trace,
                   stats: CallStats, *, use_llm: bool = True, geo_transport=None) -> dict:
    req = ctx.req
    started = time.monotonic()
    tag, sfx = {"qloo": ("", ""), "baseline": (" (baseline)", "_b"), "green": (" (footprint-only)", "_g")}[mode]
    async with trace.stage(f"discovery{sfx}", f"Discover places{tag}", "Discovery") as st:
        found = await discovery.discover(client, req, seed_ids=ctx.seed_ids, seed_tags=ctx.seed_tags,
                                         stats=stats, use_signals=(mode == "qloo"), center=ctx.center)
        if not found.candidates:
            raise StageFailed("no_places", f"Qloo returned no matching places in {req.location} for those categories."
                              + (" The step-free filter may be too strict there." if req.step_free else ""))
        st.detail = f"{len(found.candidates)} places across {len(req.categories)} categories" + \
            (" with your taste signals" if mode == "qloo" else " without taste signals")
        adapted = [v["label"] for v in found.per_category.values() if v.get("adapted")]
        if adapted:
            st.detail += f" · too few {', '.join(a.lower() for a in adapted)} passed your filters, so it searched wider once"
        st.detail += f" · Qloo asked for places within {req.radius_km} km of the city centre" if found.constrained \
            else " · Qloo matched the name itself; far places are filtered next"
        st.data = {"per_category": found.per_category, "constrained": found.constrained}
    notes = list(ctx.notes)
    cands = found.candidates
    async with trace.stage(f"evidence{sfx}", f"Attach sustainability evidence{tag}", "Sustainability") as st:
        origin = await sustainability.resolve_origin(req, found.locality, settings, transport=geo_transport,
                                                     destination=ctx.destination)
        if req.origin and (not origin or origin["kind"] != "geocoded"):
            notes.append(f"Couldn't use “{req.origin}” as a starting point (not found, or over "
                         f"{sustainability.MAX_ORIGIN_KM} km from {req.location}); distances are from the city centre.")
        ev = sustainability.attach_evidence(cands, origin, req)
        radius = req.radius_km
        cands, away = sustainability.gate_by_area(cands, origin, radius)
        for c in away:
            stat = found.per_category[c.category] if c.category in found.per_category else None
            if stat:
                stat["kept"] -= 1
                stat["dropped"] += 1
                stat["why_dropped"]["out_of_area"] = stat["why_dropped"].get("out_of_area", 0) + 1
        ev["out_of_area"] = len(away)
        ev["radius_km"] = radius
        st.detail = (f"Distances from {origin['label']}" if origin else "No reference point; distances unavailable") + \
            f" · {ev['with_signals']} places with lower-impact tags"
        if away:
            st.detail += f" · {len(away)} places more than {radius:g} km away left out"
        st.data = ev
    for key, stat in found.per_category.items():
        if stat.get("error"):
            notes.append(f"{stat['label']}: {stat['error']}")
        elif not stat["kept"]:
            notes.append(empty_note(stat, req.location, radius))
    if not cands:
        raise StageFailed("out_of_area", f"Every place Qloo found for “{req.location}” is more than {radius:g} km "
                          f"from {origin['label'] if origin else 'the destination'}. Search a wider area, or try a "
                          f"different city.", suggestions=wider(req), coverage=coverage(found.per_category))
    async with trace.stage(f"planning{sfx}", f"Plan your days{tag}", "Planning") as st:
        words = ctx.user_words()
        for c in cands:
            base = (c.place.affinity or 0.0) if mode == "qloo" else \
                baseline.footprint_base(c, radius) if mode == "green" else baseline.keyword_base(c, words)
            planning.score(c, req, base)
        pl = planning.plan(req, cands, origin)
        st.detail = f"{sum(len(v) for v in pl['chosen'].values())} stops over {req.days} day" + ("s" if req.days > 1 else "")
    async with trace.stage(f"verification{sfx}", f"Verify every stop{tag}", "Verification") as st:
        ver = verification.verify(req, pl, mode)
        if ver["replaced"]:
            taken = {c.id for lst in pl["chosen"].values() for c in lst}
            pl["swaps"] = {c.id: s for lst in pl["chosen"].values() for c in lst
                           if (s := planning.lighter_swap(c, pl["ranked"].get(c.category, []), taken, req))}
            pl["alternates"] = {k: [c.id for c in pl["ranked"].get(k, []) if c.id not in taken][:3]
                                for k in req.categories}
        pl["days"] = planning.build_days(req, pl["chosen"], origin)
        st.detail = f"{ver['stops_checked']} stops passed" + (f", {len(ver['replaced'])} replaced" if ver["replaced"] else "")
        st.data = {"replaced": ver["replaced"]}
        if not ver["stops_checked"]:
            raise StageFailed("nothing_verified", "None of the places found passed verification.")
    async with trace.stage(f"explanation{sfx}", f"Explain each pick{tag}", "Explanation") as st:
        by_id = {c.id: c for c in cands}
        show = [c.id for lst in pl["chosen"].values() for c in lst]
        show += [i for ids in pl["alternates"].values() for i in ids]
        show += [s["to_id"] for s in pl["swaps"].values()]
        cards = {}
        for cid in dict.fromkeys(show):
            c = by_id[cid]
            facts, meta = explanation.facts_for(c, ctx.seeds, ctx.portrait, origin, mode)
            cards[cid] = explanation.card(c, facts, meta, origin, ver["checks"].get(cid))
        picked_cards = [cards[c.id] for lst in pl["chosen"].values() for c in lst]
        src = await explanation.explain(picked_cards, llm, use_llm and mode == "qloo")
        st.detail = "AI-reworded from grounded facts" if src == "ai" else "Written from grounded facts"
    days = pl["days"]
    requested = sum(planning.picks_per_category(req, k) for k in req.categories)
    planned = sum(len(d["stops"]) for d in days)
    short = [CATEGORIES[k].label for k in req.categories if len(pl["chosen"].get(k, [])) < planning.picks_per_category(req, k)]
    cov = coverage(found.per_category)
    if planned < requested:
        notes.insert(0, f"Partial plan: {planned} of the {requested} stops you asked for. Qloo returned {cov['returned']} "
                        f"places; {cov['kept']} fit your city, area and filters. Short on: {', '.join(short)}.")
    car_total = None if req.car_free else round(sum(d["totals"]["car_kg_co2e"] or 0 for d in days), 2)
    low_total = round(sum(d["totals"]["suggested_kg_co2e"] for d in days), 2)
    return {
        "mode": mode,
        "origin": {k: origin[k] for k in ("label", "lat", "lon", "kind", "source")} if origin else None,
        "locality": found.locality.model_dump() if found.locality else None,
        "days": days,
        "cards": cards,
        "alternates": pl["alternates"],
        "swaps": pl["swaps"],
        "replaced": ver["replaced"],
        "notes": notes,
        "explanation_source": src,
        "summary": {
            "stops": sum(len(d["stops"]) for d in days),
            "km": round(sum(d["totals"]["km"] for d in days), 2),
            "suggested_kg_co2e": low_total,
            "car_kg_co2e": car_total,
            "saved_kg_co2e": round(car_total - low_total, 2) if car_total is not None else None,
            "swaps": len(pl["swaps"]),
            "complete": all(d["totals"]["complete"] for d in days) and planned >= requested,
            "requested_stops": requested,
            "evidence_complete": all(d["totals"]["complete"] for d in days),
            "empty_days": [d["day"] for d in days if not d["stops"]],
        },
        "coverage": cov,
        "suggestions": adjustments(req, cov, thin=any(
            found.per_category[k]["kept"] < planning.picks_per_category(req, k) for k in req.categories
            if k in found.per_category)) if planned < requested else [],
        "destination": ctx.destination,
        "drivers": drivers(ctx, [c for lst in pl["chosen"].values() for c in lst]),
        "ms": int((time.monotonic() - started) * 1000),
        "_planned": [c for lst in pl["chosen"].values() for c in lst],
        "_origin": origin,
    }


def drivers(ctx: Context, planned: list) -> list[dict]:
    """Which of the user's interests Qloo's explainability credits across the planned stops."""
    names = {s["entity_id"]: s["name"] for s in ctx.seeds if s.get("entity_id")}
    agg: dict[str, dict] = {}
    for c in planned:
        for i, x in enumerate(c.place.explainability):
            if x.entity_id not in names:
                continue
            d = agg.setdefault(x.entity_id, {"name": names[x.entity_id], "total": 0.0, "top": 0})
            d["total"] += x.score
            d["top"] += i == 0
    out = sorted(agg.values(), key=lambda d: d["total"], reverse=True)
    for d in out:
        d["total"] = round(d["total"], 3)
    return out


def list_metrics(result: dict, ids: list[str], user_words: set[str]) -> dict:
    """Measured properties of a recommendation list (no judgement of 'quality' built in)."""
    cards = [result["cards"][i] for i in ids]
    n = len(cards) or 1
    tags = [t.lower() for c in cards for t in c["tags"]]
    kw = sum(1 for c in cards if user_words & baseline.words([c["name"], *c["tags"]]))
    km = [c["distance_km"] for c in cards if c["distance_km"] is not None]
    return {
        "items": len(cards),
        "categories": len({c["category"] for c in cards}),
        "tag_diversity": round(len(set(tags)) / len(tags), 2) if tags else None,
        "theme_match_rate": round(sum(1 for c in cards if c["shared_themes"]) / n, 2),
        "keyword_match_rate": round(kw / n, 2),
        "distance_evidence_rate": round(len(km) / n, 2),
        "lower_impact_signal_rate": round(sum(1 for c in cards if c["signals"]) / n, 2),
        "avg_km": round(sum(km) / len(km), 2) if km else None,
        "ms": result["ms"],
    }


def request_summary(req: RunRequest) -> dict:
    return {"location": req.location, "origin": req.origin, "days": req.days, "budget": req.budget,
            "categories": [{"key": k, "label": CATEGORIES[k].label} for k in req.categories],
            "priorities": req.priorities, "car_free": req.car_free, "step_free": req.step_free,
            "travelers": req.travelers, "balance": req.balance, "radius_km": req.radius_km}


async def run(req: RunRequest, *, client: QlooClient, llm: LLM, settings: Settings, emit: Emit | None = None,
              geo_transport=None) -> dict:
    run_id = uuid.uuid4().hex[:12]
    trace = Trace(run_id, emit)
    stats = CallStats()
    ctx = await prepare(req, client, llm, trace, stats, settings, geo_transport)
    out = await run_mode(ctx, req.mode, client, llm, settings, trace, stats, geo_transport=geo_transport)
    planned, origin = out.pop("_planned"), out.pop("_origin")
    out["bridges"] = []
    if req.mode == "qloo" and ctx.seed_ids + ctx.seed_tags:
        async with trace.stage("bridge", "Look for a Taste Bridge", "Taste Bridge", required=False) as st:
            found = await bridge.find_bridges(client, req, seed_ids=ctx.seed_ids, seed_tags=ctx.seed_tags,
                                              planned=planned, origin=origin, stats=stats, center=ctx.center)
            for b in found["bridges"]:
                c = b.pop("candidate")
                facts, meta = explanation.facts_for(c, ctx.seeds, ctx.portrait, origin, "qloo")
                facts.insert(0, f"It is outside the categories you picked, {b['hop']['km']} km "
                                f"({b['hop']['label'].lower()}) from {b['near_name']}.")
                out["cards"][c.id] = explanation.card(c, facts, meta, origin, b.pop("checks"))
                out["bridges"].append({"id": c.id, **b})
            st.detail = (f"{len(found['bridges'])} nearby bridge{'s' if len(found['bridges']) != 1 else ''} "
                         f"from {found.get('considered', 0)} strong matches") if found["bridges"] or \
                found.get("considered") else found.get("reason", "No strong matches near your stops")
            st.data = {"affinity_floor": found.get("affinity_floor"), "categories": found.get("categories")}
    await check_grounding(trace, out, req, stats, ctx.seeds, radius_km=req.radius_km)
    return {"type": "result", "run_id": run_id, "request": request_summary(req), "seeds": ctx.seeds,
            "portrait": ctx.portrait, "intent_source": ctx.intent_source, **out,
            "stats": stats.as_dict(), "trace": trace.as_list(), "fixtures": settings.fixtures_active}


RADII = (25, 40, 60)


def wider(req: RunRequest) -> list[dict]:
    """Offer (never apply) the next search radius; the user decides."""
    nxt = [r for r in RADII if r > req.radius_km]
    return [{"label": f"Search within {nxt[0]} km", "patch": {"radius_km": nxt[0]}}] if nxt else []


def coverage(per_category: dict) -> dict:
    """Totals across categories, straight from the run's own counts."""
    why: dict[str, int] = {}
    for stat in per_category.values():
        for k, n in stat.get("why_dropped", {}).items():
            why[k] = why.get(k, 0) + n
    return {"returned": sum(v["returned"] for v in per_category.values()),
            "kept": sum(v["kept"] for v in per_category.values()),
            "failed_categories": [v["label"] for v in per_category.values() if v.get("error")],
            "why_dropped": why}


def adjustments(req: RunRequest, cov: dict, thin: bool = False) -> list[dict]:
    """The smallest useful changes, most impactful first, from what actually removed places.

    `thin`: some category has fewer usable places than the plan needs, so a wider search area may
    find more even though nothing was dropped for distance.
    """
    why = cov["why_dropped"]
    opts = []
    if why.get("out_of_area") or thin:
        opts += [(why.get("out_of_area", 0) or 1, o) for o in wider(req)]
    if why.get("over_budget") and req.budget:
        opts.append((why["over_budget"], {"label": "Allow any budget", "patch": {"budget": None}}))
    if why.get("no_step_free_tag") and req.step_free:
        opts.append((why["no_step_free_tag"], {"label": "Include places without a step-free tag",
                                                "patch": {"step_free": False}}))
    out = [o for _, o in sorted(opts, key=lambda x: -x[0])]
    if req.days == 2:
        out.append({"label": "Make it a 1-day plan", "patch": {"days": 1}})
    return out


REASONS = {"out_of_area": "too far away", "other_category": "really a different kind of place",
           "not_an_experience": "not somewhere to visit", "closed": "marked closed",
           "over_budget": "over your budget", "no_step_free_tag": "not tagged step-free",
           "duplicate": "already in another category"}


def empty_note(stat: dict, location: str, radius_km: float) -> str:
    """Explain an empty category with the counts the run actually produced."""
    label = stat["label"].lower()
    if not stat["returned"]:
        return f"Qloo returned no {label} for {location}."
    why = ", ".join(f"{n} {REASONS.get(k, k.replace('_', ' '))}" for k, n in stat["why_dropped"].items() if n)
    far = f" (more than {radius_km:g} km)" if stat["why_dropped"].get("out_of_area") else ""
    return f"Qloo returned {stat['returned']} {label} for {location}, but none fit: {why}{far}."


async def check_grounding(trace: Trace, out: dict, req: RunRequest, stats: CallStats, seeds: list[dict],
                          suffix: str = "", radius_km: float = 25.0) -> None:
    sid = {"": "", " (baseline)": "_b", " (footprint-only)": "_g"}.get(suffix, "_x")
    async with trace.stage(f"grounding{sid}", f"Check every claim is grounded{suffix}", "Grounding") as st:
        g = grounding.validate(out, req, stats.place_names, seeds, radius_km=radius_km)
        out["grounding"] = g
        st.data = {"checks": [{k: c[k] for k in ("id", "passed")} for c in g["checks"]]}
        if not g["passed"]:
            failed = [c for c in g["checks"] if not c["passed"]]
            st.detail = "Failed: " + "; ".join(f"{c['id']} ({', '.join(c['failures'][:2])})" for c in failed)
            raise StageFailed("grounding_failed", "A result failed our grounding checks, so we're not showing it. "
                                                  "Please try again or adjust your request.")
        st.detail = f"{len(g['checks'])} checks passed" + (f", {g['repaired']} AI sentence(s) repaired" if g["repaired"] else "")


def top_list(result: dict, n: int = 6) -> list[dict]:
    """Flatten a run into the top-n picks for the blind comparison (round-robin across categories)."""
    by_cat: dict[str, list[str]] = {}
    for d in result["days"]:
        for s in d["stops"]:
            by_cat.setdefault(s["category"], []).append(s["id"])
    for k, ids in result["alternates"].items():
        by_cat.setdefault(k, []).extend(ids)
    out, i = [], 0
    while len(out) < n and any(i < len(v) for v in by_cat.values()):
        for ids in by_cat.values():
            if i < len(ids) and len(out) < n:
                c = result["cards"][ids[i]]
                out.append({"id": c["id"], "name": c["name"], "category_label": c["category_label"],
                            "image_url": c["image_url"], "tags": c["tags"][:4], "distance_km": c["distance_km"],
                            "price_text": c["price_text"], "why": c["why"]["text"]})
        i += 1
    return out


async def compare(req: RunRequest, *, client: QlooClient, llm: LLM, settings: Settings, emit: Emit | None = None,
                  geo_transport=None, n: int = 6) -> dict:
    run_id = uuid.uuid4().hex[:12]
    trace = Trace(run_id, emit)
    stats = CallStats()
    ctx = await prepare(req, client, llm, trace, stats, settings, geo_transport)
    q = await run_mode(ctx, "qloo", client, llm, settings, trace, stats, use_llm=False, geo_transport=geo_transport)
    b = await run_mode(ctx, "baseline", client, llm, settings, trace, stats, use_llm=False, geo_transport=geo_transport)
    # Ablation arm C: same candidate pool as the baseline (cached Qloo calls), ranked by footprint only.
    g = await run_mode(ctx, "green", client, llm, settings, trace, stats, use_llm=False, geo_transport=geo_transport)
    for x in (q, b, g):
        x.pop("_planned"), x.pop("_origin")
        x["bridges"] = []
    await check_grounding(trace, q, req, stats, ctx.seeds, radius_km=req.radius_km)
    await check_grounding(trace, b, req, stats, ctx.seeds, " (baseline)", radius_km=req.radius_km)
    await check_grounding(trace, g, req, stats, ctx.seeds, " (footprint-only)", radius_km=req.radius_km)
    ql, bl, gl = top_list(q, n), top_list(b, n), top_list(g, n)
    words = ctx.user_words()
    q_ids, b_ids = {x["id"] for x in ql}, {x["id"] for x in bl}
    flip = uuid.uuid4().int % 2 == 1
    lists = {"A": bl if flip else ql, "B": ql if flip else bl}
    return {
        "type": "compare", "run_id": run_id, "request": request_summary(req), "seeds": ctx.seeds,
        "lists": lists,
        "reveal": {"A": "baseline" if flip else "qloo", "B": "qloo" if flip else "baseline"},
        "overlap": len(q_ids & b_ids),
        "metrics": {
            "qloo": {**list_metrics(q, [x["id"] for x in ql], words),
                     **{k: q["summary"][k] for k in ("km", "suggested_kg_co2e")}},
            "baseline": {**list_metrics(b, [x["id"] for x in bl], words),
                         **{k: b["summary"][k] for k in ("km", "suggested_kg_co2e")}},
            "footprint": {**list_metrics(g, [x["id"] for x in gl], words),
                          **{k: g["summary"][k] for k in ("km", "suggested_kg_co2e")}},
        },
        "overlap_footprint": len(q_ids & {x["id"] for x in gl}),
        "grounding": {"qloo": q["grounding"]["passed"], "baseline": b["grounding"]["passed"],
                      "footprint": g["grounding"]["passed"]},
        "stats": stats.as_dict(), "trace": trace.as_list(), "fixtures": settings.fixtures_active,
    }

