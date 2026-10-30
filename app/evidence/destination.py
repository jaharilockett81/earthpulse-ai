"""Destination resolution: EarthPulse plans walkable city days, so the destination must be a city.

A state, province or country is refused before any Qloo call, with a few example cities to pick from.
Anything else is geocoded (Open-Meteo / GeoNames) and the result is validated: it must be a populated
place (GeoNames feature code PPL*) whose name matches what was typed. A geocoder hit is never used as a
silent substitute: "Florida" geocodes to "Floridablanca, Colombia", which this rejects.
"""

from __future__ import annotations

import re
import unicodedata

import httpx

from .geo import GEOCODE_SOURCE, geocode

# Regions people type as if they were cities -> example cities (well-known, for the picker only).
US_STATES = {
    "alabama": ["Birmingham", "Montgomery", "Mobile"], "alaska": ["Anchorage", "Juneau", "Fairbanks"],
    "arizona": ["Phoenix", "Tucson", "Flagstaff"], "arkansas": ["Little Rock", "Fayetteville", "Hot Springs"],
    "california": ["San Francisco", "Los Angeles", "San Diego", "Sacramento"],
    "colorado": ["Denver", "Boulder", "Colorado Springs"], "connecticut": ["New Haven", "Hartford", "Stamford"],
    "delaware": ["Wilmington", "Dover", "Newark"],
    "florida": ["West Palm Beach", "Orlando", "Tampa", "Miami"],
    "hawaii": ["Honolulu", "Hilo", "Kailua"], "idaho": ["Boise", "Coeur d'Alene", "Idaho Falls"],
    "illinois": ["Chicago", "Springfield", "Evanston"], "indiana": ["Indianapolis", "Bloomington", "Fort Wayne"],
    "iowa": ["Des Moines", "Iowa City", "Cedar Rapids"], "kansas": ["Wichita", "Lawrence", "Kansas City, KS"],
    "kentucky": ["Louisville", "Lexington", "Bowling Green"], "louisiana": ["New Orleans", "Baton Rouge", "Lafayette"],
    "maine": ["Portland, ME", "Bangor", "Bar Harbor"], "maryland": ["Baltimore", "Annapolis", "Frederick"],
    "massachusetts": ["Boston", "Cambridge, MA", "Salem, MA"], "michigan": ["Detroit", "Ann Arbor", "Grand Rapids"],
    "minnesota": ["Minneapolis", "Saint Paul", "Duluth"], "mississippi": ["Jackson, MS", "Oxford, MS", "Biloxi"],
    "missouri": ["St. Louis", "Kansas City, MO", "Springfield, MO"], "montana": ["Missoula", "Bozeman", "Billings"],
    "nebraska": ["Omaha", "Lincoln, NE"], "nevada": ["Las Vegas", "Reno"],
    "new hampshire": ["Portsmouth, NH", "Manchester, NH", "Concord, NH"],
    "new jersey": ["Jersey City", "Newark, NJ", "Princeton"], "new mexico": ["Santa Fe", "Albuquerque", "Taos"],
    "north carolina": ["Asheville", "Raleigh", "Charlotte"], "north dakota": ["Fargo", "Bismarck"],
    "ohio": ["Columbus, OH", "Cleveland", "Cincinnati"], "oklahoma": ["Tulsa", "Oklahoma City"],
    "oregon": ["Portland, OR", "Eugene", "Bend"], "pennsylvania": ["Philadelphia", "Pittsburgh", "Lancaster, PA"],
    "rhode island": ["Providence", "Newport, RI"], "south carolina": ["Charleston, SC", "Greenville, SC", "Columbia, SC"],
    "south dakota": ["Sioux Falls", "Rapid City"], "tennessee": ["Nashville", "Memphis", "Chattanooga"],
    "texas": ["Austin", "Houston", "San Antonio", "Dallas"], "utah": ["Salt Lake City", "Park City", "Moab"],
    "vermont": ["Burlington, VT", "Montpelier"], "virginia": ["Richmond, VA", "Charlottesville", "Norfolk"],
    "west virginia": ["Charleston, WV", "Morgantown"], "wisconsin": ["Milwaukee", "Madison, WI"],
    "wyoming": ["Jackson, WY", "Cheyenne", "Laramie"],
}
OTHER_REGIONS = {
    "ontario": ["Toronto", "Ottawa"], "quebec": ["Montreal", "Quebec City"], "british columbia": ["Vancouver", "Victoria, BC"],
    "alberta": ["Calgary", "Edmonton"], "england": ["London", "Manchester", "Bristol"], "scotland": ["Edinburgh", "Glasgow"],
    "wales": ["Cardiff"], "japan": ["Tokyo", "Kyoto", "Osaka"], "portugal": ["Lisbon", "Porto"],
    "italy": ["Rome", "Florence", "Milan"], "france": ["Paris", "Lyon", "Marseille"], "spain": ["Madrid", "Barcelona", "Seville"],
    "germany": ["Berlin", "Munich", "Hamburg"], "united kingdom": ["London", "Edinburgh"], "uk": ["London", "Edinburgh"],
    "usa": ["New York", "Chicago", "San Francisco"], "united states": ["New York", "Chicago", "San Francisco"],
    "mexico": ["Mexico City", "Oaxaca"], "canada": ["Toronto", "Montreal", "Vancouver"],
    "netherlands": ["Amsterdam", "Rotterdam"], "denmark": ["Copenhagen"], "australia": ["Sydney", "Melbourne"],
}
REGIONS = {**US_STATES, **OTHER_REGIONS}
_SUFFIX = re.compile(r"\s*,?\s*\b(state|usa|us|u\.s\.a?\.?|united states)\.?$", re.I)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def region_of(location: str) -> tuple[str, list[str]] | None:
    """If the input names a state/province/country rather than a city, return (name, example cities)."""
    text = _SUFFIX.sub("", location.strip())
    key = _norm(text)
    key = re.sub(r"\s+", " ", key)
    if key in REGIONS:
        return text.strip(), REGIONS[key]
    return None


def _same_place(typed: str, found: str) -> bool:
    a, b = _norm(typed), _norm(found)
    return bool(a) and (a == b or a.startswith(b + " ") or b.startswith(a + " ") or a.replace(" ", "") == b.replace(" ", ""))


async def resolve(location: str, url: str, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Classify the destination. Returns a dict with `status`:

    - "region":   a state/province/country; `suggestions` lists example cities. Planning must stop.
    - "city":     geocoded populated place matching the input, with coordinates and structured fields.
    - "unconfirmed": the geocoder found nothing usable; planning may continue on Qloo's own resolution,
                  bounded by the area gate, and the user is told.
    """
    region = region_of(location)
    if region:
        name, cities = region
        return {"status": "region", "input": location, "name": name, "suggestions": cities}
    head = location.split(",")[0]
    got = await geocode(location, url, transport=transport)
    if not got:
        return {"status": "unconfirmed", "input": location, "reason": "not found by the geocoder"}
    if not str(got.get("feature_code") or "").startswith("PPL"):
        return {"status": "unconfirmed", "input": location, "reason": f"geocoder returned a {got.get('feature_code')}"}
    if not _same_place(head, got["name"]):
        return {"status": "unconfirmed", "input": location,
                "reason": f"the closest geocoder match was {got['label']}, a different name"}
    return {"status": "city", "input": location, **got, "source": GEOCODE_SOURCE}
