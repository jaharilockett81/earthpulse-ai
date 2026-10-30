"""Baseline Agent (the ablation in the comparison lab).

Uses the SAME Qloo place directory for the same city and categories, but sends no taste
signals. Places are ranked by plain keyword overlap between the user's own words and the
place's name, tags and keywords — what a conventional keyword search would do. Everything
else (filters, distance penalty, boosts, verification) is identical, so the difference
between the two lists is what Qloo's taste graph adds.
"""

from __future__ import annotations

import re

from .discovery import Candidate

STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "love", "like", "likes", "loves", "enjoy",
    "plan", "trip", "weekend", "day", "days", "someone", "who", "inspired", "based", "around", "want",
    "make", "find", "give", "please", "some", "things", "place", "places", "city", "visit", "our", "my",
}


def words(texts: list[str]) -> set[str]:
    out = set()
    for t in texts:
        for w in re.findall(r"[a-z0-9]{3,}", (t or "").lower()):
            if w not in STOP:
                out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def keyword_base(c: Candidate, user_words: set[str]) -> float:
    """Share of the user's words found in the place's own listing, 0–1."""
    if not user_words:
        c.keyword_hits = []
        return 0.0
    p = c.place
    hay = words([p.name, p.description or "", *p.tag_names(), *p.keywords, p.primary_genre or ""])
    hits = sorted(user_words & hay)
    c.keyword_hits = hits
    return round(len(hits) / len(user_words), 3)


def footprint_base(c, radius_km: float) -> float:
    """Ablation arm C: no taste at all. Nearer is better, plus a small bonus for a lower-impact tag.

    Unknown distance scores lowest, so the arm never rewards missing evidence.
    """
    near = 0.0 if c.distance_km is None else 1 - min(c.distance_km, radius_km) / radius_km
    return round(near + (0.05 if c.signals else 0.0), 4)
