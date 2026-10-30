"""Shared test setup. All Qloo traffic is mocked with respx; payloads are hand-written or generated
by app/qloo/fixtures.py — never recorded Qloo responses."""

import pytest
import respx

from app.config import Settings
from app.qloo import fixtures

BASE = "https://hackathon.api.qloo.com"


@pytest.fixture
def settings():
    return Settings(qloo_api_key="test-key", qloo_max_rps=1000, anthropic_api_key="", environment="test",
                    dev_fixtures=False, runs_per_hour_per_ip=50)


@pytest.fixture(autouse=True)
def _no_real_geocoding(monkeypatch):
    """Tests never reach the real geocoder (CI has internet; results would leak between tests)."""
    from app.agents import sustainability
    from app.evidence import destination, geo

    geo._CACHE.clear()

    async def none(*a, **k):
        return None

    monkeypatch.setattr(sustainability, "geocode", none)
    monkeypatch.setattr(destination, "geocode", none)


@pytest.fixture
def qloo_mock():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.route().mock(side_effect=fixtures.handler)
        yield router


def place(eid="P1", name="Fern Park", tags=None, affinity=0.8, lat=38.72, lon=-9.14, **props):
    return {
        "entity_id": eid, "name": name,
        "location": {"lat": lat, "lon": lon},
        "tags": tags if tags is not None else [{"tag_id": "urn:tag:category:place:park", "name": "Park"}],
        "properties": props,
        "query": {"affinity": affinity},
    }
