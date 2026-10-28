import httpx
import pytest
import respx

from app.config import Settings
from app.llm import LLM
from app.qloo.client import QlooAuthError, QlooClient, QlooNotConfigured, QlooRateLimited, CallStats

from .conftest import BASE


async def test_retries_429_then_succeeds(settings):
    with respx.mock(base_url=BASE) as r:
        r.get("/search").mock(side_effect=[httpx.Response(429, headers={"retry-after": "0"}),
                                           httpx.Response(200, json={"results": [{"entity_id": "E", "name": "X"}]})])
        c = QlooClient(settings)
        hits = await c.search("xx")
        assert hits[0].entity_id == "E"


async def test_persistent_429_is_an_error_not_empty(settings):
    with respx.mock(base_url=BASE) as r:
        r.get("/search").mock(return_value=httpx.Response(429, headers={"retry-after": "0"}))
        with pytest.raises(QlooRateLimited):
            await QlooClient(settings).search("xx")


async def test_auth_error_and_header(settings):
    with respx.mock(base_url=BASE) as r:
        route = r.get("/search").mock(return_value=httpx.Response(401))
        with pytest.raises(QlooAuthError):
            await QlooClient(settings).search("xx")
        assert route.calls[0].request.headers["X-Api-Key"] == "test-key"


async def test_cache_hit_counts(settings):
    with respx.mock(base_url=BASE) as r:
        route = r.get("/search").mock(return_value=httpx.Response(200, json={"results": []}))
        c, stats = QlooClient(settings), CallStats()
        await c.search("abc", stats=stats)
        await c.search("abc", stats=stats)
        assert route.call_count == 1 and stats.as_dict() == {"network_calls": 1, "cache_hits": 1}


async def test_not_configured():
    with pytest.raises(QlooNotConfigured):
        await QlooClient(Settings(qloo_api_key="")).search("abc")


async def test_llm_rejects_ungrounded_numbers():
    s = Settings(anthropic_api_key="k")
    text = '{"items": [{"id": "a", "text": "Lovely, rated 4.9 stars."}, {"id": "b", "text": "A calm park 2 km away."}]}'
    with respx.mock() as r:
        r.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json={"content": [{"type": "text", "text": text}]}))
        out = await LLM(s).polish_explanations([
            {"id": "a", "name": "A", "facts": ["A cafe."]},
            {"id": "b", "name": "B", "facts": ["It is 2 km away."]},
        ])
    assert out == {"b": "A calm park 2 km away."}
