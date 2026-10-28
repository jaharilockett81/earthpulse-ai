"""Experience categories and how they map onto Qloo place tags.

Only tag IDs observed in live hackathon responses are used as filters
(`urn:tag:category:place:*`, plus the `urn:tag:genre:place:restaurant` / `hotel` genres).
Qloo's `filter.tags` is a soft filter and multi-tag filters are a union, so every
returned place is re-classified from its OWN tags before it is shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import Place

CAT = "urn:tag:category:place:"
GENRE = "urn:tag:genre:place:"


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    tags: tuple[str, ...]  # filter tags sent to Qloo
    match: tuple[str, ...]  # leaf names that count as membership when re-classifying
    daypart: str  # morning | midday | afternoon | evening — used by the planner


CATEGORIES: dict[str, Category] = {
    c.key: c
    for c in [
        Category("nature", "Parks & gardens", (CAT + "park", CAT + "botanical_garden", CAT + "community_garden"),
                 ("park", "city_park", "botanical_garden", "community_garden", "garden", "nature_preserve", "state_park", "national_park"), "midday"),
        Category("culture", "Museums & culture", (CAT + "museum", CAT + "cultural_center"),
                 ("museum", "art_museum", "cultural_center", "history_museum", "science_museum", "art_gallery"), "afternoon"),
        Category("coffee", "Cafés & coffee", (CAT + "cafe", CAT + "coffee_shop"),
                 ("cafe", "coffee_shop", "tea_house", "bakery"), "morning"),
        Category("books_music", "Books & records", (CAT + "book_store", CAT + "record_store"),
                 ("book_store", "used_book_store", "record_store", "comic_book_store", "library"), "afternoon"),
        Category("live_music", "Live music", (CAT + "live_music_venue", CAT + "jazz_club"),
                 ("live_music_venue", "jazz_club", "concert_hall"), "evening"),
        Category("makers", "Studios & workshops", (CAT + "art_studio", CAT + "pottery_classes"),
                 ("art_studio", "pottery_classes", "craft_store", "art_school"), "afternoon"),
        Category("dining", "Restaurants", (GENRE + "restaurant",),
                 ("restaurant",), "evening"),
        Category("stay", "Places to stay", (GENRE + "hotel",),
                 ("hotel", "bed_and_breakfast", "inn", "lodge", "hostel", "resort"), "evening"),
    ]
}

DEFAULT_CATEGORIES = ["nature", "culture", "coffee", "dining"]

# Places Qloo's affinity ranking sometimes surfaces that are never "experiences".
_BLOCK_LEAVES = {
    "bank", "atm", "radio_station", "pharmacy", "hospital", "medical_clinic", "school", "university",
    "gas_station", "car_dealer", "car_repair", "insurance_agency", "real_estate_agency", "storage",
    "post_office", "laundromat", "dentist", "doctor", "lawyer", "government_office", "parking",
}
_BLOCK_NAME = re.compile(r"\b(bank|atm|radio|pharmacy|hospital|clinic|school|university|storage|parking)\b|\bfm\b", re.I)

# Words in Qloo place tags/keywords that relate to lower-impact choices. These are taste
# signals Qloo returns about a place — NOT certifications — and are labelled as such.
LOW_IMPACT_SIGNALS = re.compile(
    r"\b(vegan|vegetarian|plant[- ]based|organic|farm[- ]to[- ]table|local(ly)? sourced|sustainab\w*|"
    r"eco[- ]?friendly|zero[- ]waste|thrift|vintage|second[- ]?hand|bike|bicycle|walkable|garden|"
    r"native plants?|conservation|wildlife|nature preserve|recycl\w*|compost\w*|solar|seasonal)\b",
    re.I,
)
STEP_FREE_TAG = "urn:tag:accessibility:place:wheelchair_accessible_entrance"


def _leaves(place: Place) -> set[str]:
    out = set()
    for t in place.tags:
        if t.id.startswith(CAT) or t.id.startswith(GENRE):
            out.add(t.id.split(":")[-1])
    if place.primary_genre_id and place.primary_genre_id.startswith(GENRE):
        out.add(place.primary_genre_id.split(":")[-1])
    return out


def is_blocked(place: Place) -> bool:
    leaves = _leaves(place)
    if leaves and leaves <= _BLOCK_LEAVES:
        return True
    return bool(_BLOCK_NAME.search(place.name)) and not (leaves - _BLOCK_LEAVES)


def classify(place: Place, wanted: list[str] | None = None) -> str | None:
    """Return the first wanted category this place belongs to, judged by its own tags."""
    leaves = _leaves(place)
    genre_text = (place.primary_genre or "").lower().replace(" ", "_")
    keys = wanted or list(CATEGORIES)
    for key in keys:
        cat = CATEGORIES.get(key)
        if not cat:
            continue
        for leaf in leaves:
            if leaf in cat.match or any(leaf.endswith("_" + m) or leaf.startswith(m + "_") for m in cat.match):
                return key
        if genre_text and any(m in genre_text for m in cat.match):
            return key
    return None


def low_impact_signals(place: Place) -> list[str]:
    """Distinct Qloo tag/keyword phrases on this place that mention lower-impact themes."""
    seen: dict[str, str] = {}
    for text in [*place.tag_names(), *place.keywords]:
        if LOW_IMPACT_SIGNALS.search(text):
            seen.setdefault(text.lower(), text)
    return list(seen.values())[:6]


def has_step_free_tag(place: Place) -> bool:
    return STEP_FREE_TAG in place.tag_ids()
