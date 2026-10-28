"""Server-side Qloo client.

- Authenticates with the `X-Api-Key` header against the hackathon host.
- Throttles to stay under the key's 5 requests/second limit.
- Retries 429 and 5xx with bounded backoff; a 429 is never reported as "no results".
- Caches successful GET responses in memory (24h default) to conserve the monthly quota.
- Raises typed errors so callers can show an honest message instead of fake data.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any

import httpx

from ..config import Settings
from .schemas import Locality, Place, SearchHit, TagInsight, parse_places, parse_search, parse_tag_insights

log = logging.getLogger("earthpulse.qloo")

SEARCH_PATH = "/search"
INSIGHTS_PATH = "/v2/insights"
TAGS_PATH = "/v2/tags"


class QlooError(Exception):
    code = "qloo_error"
    user_message = "Qloo returned an unexpected error."

    def __init__(self, detail: str = "", status: int | None = None):
        super().__init__(detail or self.user_message)
        self.status = status


class QlooNotConfigured(QlooError):
    code = "qloo_not_configured"
    user_message = "Live taste data isn't configured on this server (QLOO_API_KEY is missing)."


class QlooAuthError(QlooError):
    code = "qloo_auth"
    user_message = "Qloo rejected this server's API key."


class QlooRateLimited(QlooError):
    code = "qloo_rate_limited"
    user_message = "Qloo is rate-limiting requests right now. Please try again in a minute."


class QlooTimeout(QlooError):
    code = "qloo_timeout"
    user_message = "Qloo took too long to respond. Please try again."


class QlooUnavailable(QlooError):
    code = "qloo_unavailable"
    user_message = "Qloo is temporarily unavailable."


class QlooBadRequest(QlooError):
    code = "qloo_bad_request"
    user_message = "Qloo couldn't process that request."


class _Throttle:
    """Simple spacing throttle shared by all calls in this process."""

    def __init__(self, rps: float):
        self.interval = 1.0 / max(rps, 0.1)
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            await asyncio.sleep(delay)


class _TTLCache:
    def __init__(self, ttl: float, max_items: int = 2000):
        self.ttl, self.max = ttl, max_items
        self._d: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        hit = self._d.get(key)
        if not hit:
            return None
        if time.monotonic() - hit[0] > self.ttl:
            self._d.pop(key, None)
            return None
        self._d.move_to_end(key)
        return hit[1]

    def set(self, key: str, value: Any) -> None:
        self._d[key] = (time.monotonic(), value)
        self._d.move_to_end(key)
        while len(self._d) > self.max:
            self._d.popitem(last=False)


class CallStats:
    """Per-run accounting surfaced in the agent timeline."""

    def __init__(self) -> None:
        self.network_calls = 0
        self.cache_hits = 0

    def as_dict(self) -> dict[str, int]:
        return {"network_calls": self.network_calls, "cache_hits": self.cache_hits}


class QlooClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._throttle = _Throttle(settings.qloo_max_rps)
        self._cache = _TTLCache(settings.qloo_cache_ttl_s)
        self._client = httpx.AsyncClient(
            base_url=settings.qloo_base_url,
            timeout=httpx.Timeout(settings.qloo_timeout_s),
            transport=transport,
            headers={"accept": "application/json"},
        )
        self.max_retries = 2

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def configured(self) -> bool:
        return self.settings.qloo_configured

    # ------------------------------------------------------------------ core

    async def _get(self, path: str, params: dict[str, Any], stats: CallStats | None = None) -> Any:
        if not self.configured:
            raise QlooNotConfigured()
        clean = {k: str(v) for k, v in sorted(params.items()) if v not in (None, "", [])}
        key = hashlib.sha256(f"{path}?{clean}".encode()).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            if stats:
                stats.cache_hits += 1
            return cached

        last_exc: QlooError | None = None
        for attempt in range(self.max_retries + 1):
            await self._throttle.wait()
            started = time.monotonic()
            try:
                resp = await self._client.get(path, params=clean, headers={"X-Api-Key": self.settings.qloo_api_key})
            except httpx.TimeoutException:
                last_exc = QlooTimeout()
                log.warning("qloo.timeout path=%s attempt=%d", path, attempt)
                continue
            except httpx.HTTPError as exc:
                last_exc = QlooUnavailable(type(exc).__name__)
                log.warning("qloo.transport_error path=%s err=%s attempt=%d", path, type(exc).__name__, attempt)
                continue
            finally:
                if stats:
                    stats.network_calls += 1
            ms = int((time.monotonic() - started) * 1000)
            log.info("qloo.call path=%s status=%d ms=%d attempt=%d", path, resp.status_code, ms, attempt)

            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError:
                    raise QlooUnavailable("non-JSON response", 200) from None
                self._cache.set(key, body)
                return body
            if resp.status_code in (401, 403):
                raise QlooAuthError(status=resp.status_code)
            if resp.status_code == 429:
                last_exc = QlooRateLimited(status=429)
                retry_after = resp.headers.get("retry-after")
                try:
                    wait = min(float(retry_after), 4.0) if retry_after else 0.6 * (2**attempt)
                except ValueError:
                    wait = 0.6 * (2**attempt)
                await asyncio.sleep(wait)
                continue
            if resp.status_code >= 500:
                last_exc = QlooUnavailable(status=resp.status_code)
                await asyncio.sleep(0.4 * (2**attempt))
                continue
            # Other 4xx: not retryable. Keep Qloo's reason (no secrets in it) for logs only.
            log.warning("qloo.bad_request path=%s status=%d body=%s", path, resp.status_code, resp.text[:300])
            raise QlooBadRequest(status=resp.status_code)
        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------ endpoints

    async def search(self, query: str, types: list[str] | None = None, take: int = 6,
                     stats: CallStats | None = None) -> list[SearchHit]:
        query = query.strip()[:120]
        if len(query) < 2:
            return []
        params: dict[str, Any] = {"query": query, "take": max(1, min(take, 10))}
        if types:
            params["types"] = ",".join(types)
        return parse_search(await self._get(SEARCH_PATH, params, stats))

    async def search_tags(self, query: str, take: int = 5, stats: CallStats | None = None) -> list[TagInsight]:
        """/v2/tags?filter.query= — resolves a concept ("slow living") to Qloo taste tags."""
        query = query.strip()[:80]
        if len(query) < 2:
            return []
        return parse_tag_insights(await self._get(TAGS_PATH, {"filter.query": query, "take": take}, stats))

    async def place_insights(
        self,
        *,
        location_query: str,
        seed_ids: list[str] | None = None,
        seed_tags: list[str] | None = None,
        tags: list[str] | None = None,
        price_max: int | None = None,
        exclude_ids: list[str] | None = None,
        take: int = 15,
        explain: bool = True,
        stats: CallStats | None = None,
    ) -> tuple[list[Place], Locality | None]:
        params: dict[str, Any] = {
            "filter.type": "urn:entity:place",
            "filter.location.query": location_query.strip()[:120],
            "take": max(1, min(take, 50)),
        }
        if seed_ids:
            params["signal.interests.entities"] = ",".join(seed_ids)
            if explain:
                params["feature.explainability"] = "true"
        if seed_tags:
            params["signal.interests.tags"] = ",".join(seed_tags)
        if tags:
            params["filter.tags"] = ",".join(tags)
        if price_max:
            params["filter.price_level.max"] = int(price_max)
        if exclude_ids:
            params["filter.exclude.entities"] = ",".join(exclude_ids[:50])
        return parse_places(await self._get(INSIGHTS_PATH, params, stats))

    async def taste_tags(self, seed_ids: list[str], tag_types: list[str], take: int = 12,
                         stats: CallStats | None = None) -> list[TagInsight]:
        params = {
            "filter.type": "urn:tag",
            "filter.tag.types": ",".join(tag_types),
            "signal.interests.entities": ",".join(seed_ids),
            "take": take,
        }
        return parse_tag_insights(await self._get(INSIGHTS_PATH, params, stats))
