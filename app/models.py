"""Request contracts. Responses are plain JSON-ready dicts built by the agents."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .qloo.taxonomy import CATEGORIES, DEFAULT_CATEGORIES

_CLEAN = re.compile(r"[\x00-\x1f\x7f<>]")
PRIORITIES = {"low_carbon_travel", "nature_time", "plant_forward", "secondhand"}


def _clean(s: str, n: int) -> str:
    return _CLEAN.sub("", s).strip()[:n]


class Seed(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    entity_id: str | None = Field(default=None, max_length=80)
    kind: str | None = Field(default=None, max_length=40)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = _clean(v, 120)
        if not v:
            raise ValueError("interest name is empty")
        return v

    @field_validator("entity_id")
    @classmethod
    def _eid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not re.fullmatch(r"[A-Za-z0-9\-_:]{4,80}", v):
            raise ValueError("invalid entity id")
        return v


class RunRequest(BaseModel):
    seeds: list[Seed] = Field(default_factory=list, max_length=5)
    prompt: str | None = Field(default=None, max_length=400)
    location: str = Field(min_length=2, max_length=120)
    origin: str | None = Field(default=None, max_length=120)
    categories: list[str] = Field(default_factory=lambda: list(DEFAULT_CATEGORIES), max_length=6)
    budget: int | None = Field(default=None, ge=1, le=4)
    priorities: list[str] = Field(default_factory=lambda: ["low_carbon_travel"], max_length=4)
    car_free: bool = False
    step_free: bool = False
    travelers: int = Field(default=1, ge=1, le=8)
    days: Literal[1, 2] = 2
    mode: Literal["qloo", "baseline", "green"] = "qloo"

    @field_validator("location", "origin", "prompt")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _clean(v, 400) if v else v

    @field_validator("categories")
    @classmethod
    def _cats(cls, v: list[str]) -> list[str]:
        out = [c for c in dict.fromkeys(v) if c in CATEGORIES]
        if not out:
            raise ValueError("choose at least one supported experience category")
        return out

    @field_validator("priorities")
    @classmethod
    def _prio(cls, v: list[str]) -> list[str]:
        return [p for p in dict.fromkeys(v) if p in PRIORITIES]

    @model_validator(mode="after")
    def _need_taste(self) -> "RunRequest":
        if not self.seeds and not (self.prompt and len(self.prompt.strip()) >= 3):
            raise ValueError("add at least one favourite (film, artist, brand, place…) or describe your taste")
        return self


class CompareRequest(RunRequest):
    """Same inputs run twice: Qloo-enhanced vs. baseline."""
