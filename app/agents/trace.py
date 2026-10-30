"""Execution trace for the agent pipeline.

Each stage records which agent ran it, status, timing and a short human-readable detail.
Stages are streamed to the UI as they start and finish so the timeline is live, not replayed.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

log = logging.getLogger("earthpulse.agents")

Emit = Callable[[dict], Awaitable[None]]


class StageFailed(Exception):
    """Raised when a required stage cannot complete; the run stops with an honest error."""

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


class Stage:
    def __init__(self, sid: str, name: str, agent: str):
        self.id, self.name, self.agent = sid, name, agent
        self.status = "running"
        self.detail = ""
        self.data: dict[str, Any] = {}
        self.started = time.monotonic()
        self.ms = 0

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "agent": self.agent, "status": self.status,
                "detail": self.detail, "ms": self.ms, "data": self.data}


class Trace:
    def __init__(self, run_id: str, emit: Emit | None = None):
        self.run_id = run_id
        self.stages: list[Stage] = []
        self._emit = emit

    async def _send(self, stage: Stage) -> None:
        if self._emit:
            await self._emit({"type": "stage", "stage": stage.as_dict()})

    @asynccontextmanager
    async def stage(self, sid: str, name: str, agent: str, required: bool = True):
        st = Stage(sid, name, agent)
        self.stages.append(st)
        await self._send(st)
        try:
            yield st
            if st.status == "running":
                st.status = "done"
        except StageFailed:
            st.status = "failed"
            raise
        except Exception as exc:  # noqa: BLE001
            st.status = "failed" if required else "skipped"
            st.detail = st.detail or f"{type(exc).__name__}"
            log.exception("stage.error run=%s stage=%s", self.run_id, sid)
            if required:
                raise
        finally:
            st.ms = int((time.monotonic() - st.started) * 1000)
            log.info("stage run=%s id=%s status=%s ms=%d detail=%s", self.run_id, sid, st.status, st.ms, st.detail)
            await self._send(st)

    def as_list(self) -> list[dict]:
        return [s.as_dict() for s in self.stages]
