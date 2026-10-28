"""Optional LLM helper (Anthropic Messages API).

Used for two narrow jobs only, each a single call per run:
  1. Turning a free-text request into a list of interests.
  2. Rewording grounded explanation facts into one friendly sentence per card.
Outputs are strictly validated; on any failure callers fall back to deterministic code.
The LLM never supplies places, numbers, prices or sources.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from .config import Settings

log = logging.getLogger("earthpulse.llm")
API_URL = "https://api.anthropic.com/v1/messages"


class LLM:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings
        self._transport = transport

    @property
    def available(self) -> bool:
        return self.s.llm_configured

    async def _complete(self, system: str, user: str, max_tokens: int) -> str | None:
        if not self.available:
            return None
        try:
            async with httpx.AsyncClient(timeout=self.s.llm_timeout_s, transport=self._transport) as c:
                r = await c.post(
                    API_URL,
                    headers={"x-api-key": self.s.anthropic_api_key, "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={"model": self.s.llm_model, "max_tokens": max_tokens, "system": system,
                          "messages": [{"role": "user", "content": user}]},
                )
            if r.status_code != 200:
                log.warning("llm.http status=%d", r.status_code)
                return None
            blocks = r.json().get("content") or []
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("llm.failed err=%s", type(exc).__name__)
            return None

    @staticmethod
    def _json(text: str | None):
        if not text:
            return None
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except ValueError:
            return None

    async def parse_interests(self, prompt: str) -> list[str] | None:
        out = self._json(await self._complete(
            "Extract the cultural interests (works, artists, brands, places, aesthetics, hobbies) from the "
            "user's request. Return ONLY JSON: {\"interests\": [\"...\"]} with 1-5 short items, copied or "
            "minimally normalised from the text. Do not add interests that are not in the text.",
            prompt[:400], 200))
        if not isinstance(out, dict) or not isinstance(out.get("interests"), list):
            return None
        items = [str(x).strip()[:80] for x in out["interests"] if isinstance(x, str) and x.strip()]
        low = prompt.lower()
        # Validation: every interest must be grounded in the user's words.
        items = [i for i in items if any(w in low for w in re.findall(r"[a-z0-9]{3,}", i.lower()))]
        return items[:5] or None

    async def polish_explanations(self, facts: list[dict]) -> dict[str, str] | None:
        """facts: [{id, name, facts:[str]}] -> {id: sentence}. Rejects outputs with new numbers."""
        out = self._json(await self._complete(
            "You write one warm, specific sentence (max 40 words) per item explaining why a place suits a "
            "person's taste. Use ONLY the facts given for that item. Do not add numbers, prices, awards, "
            "certifications, opening hours or claims about sustainability that are not in the facts. "
            "Return ONLY JSON: {\"items\": [{\"id\": \"...\", \"text\": \"...\"}]}.",
            json.dumps({"items": facts})[:6000], 900))
        if not isinstance(out, dict) or not isinstance(out.get("items"), list):
            return None
        allowed = {f["id"]: " ".join(f["facts"]) + " " + f["name"] for f in facts}
        result: dict[str, str] = {}
        for it in out["items"]:
            if not isinstance(it, dict):
                continue
            pid, text = it.get("id"), str(it.get("text", "")).strip()
            if pid not in allowed or not text or len(text) > 320:
                continue
            nums = re.findall(r"\d+(?:\.\d+)?", text)
            if any(n not in allowed[pid] for n in nums):
                log.info("llm.rejected id=%s reason=ungrounded_number", pid)
                continue
            result[pid] = text
        return result or None
