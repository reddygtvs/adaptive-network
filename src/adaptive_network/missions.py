from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List

from pydantic import BaseModel, Field, ValidationError, field_validator


@dataclass
class Mission:
    persona: str
    start_url: str
    target_url: str
    target_label: str
    question: str
    shortest_hops: int
    id: int | None = field(default=None, init=False)


class MissionRecord(BaseModel):
    persona: str = Field(min_length=1)
    start_url: str = Field(min_length=1)
    target_url: str = Field(min_length=1)
    question: str = Field(min_length=1)
    target_label: str = ""
    shortest_hops: int = 0

    @field_validator("start_url", "target_url")
    @classmethod
    def ensure_absolute(cls, value: str) -> str:
        if not value.startswith("http"):
            raise ValueError("URLs must be absolute (start with http/https).")
        return value

    @field_validator("shortest_hops")
    @classmethod
    def non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("shortest_hops must be >= 0")
        return value


def load_missions(path: Path | str = Path("data/missions.json")) -> List[Mission]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    missions: List[Mission] = []
    for raw in data:
        try:
            record = MissionRecord.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid mission payload: {raw}") from exc
        missions.append(
            Mission(
                persona=record.persona,
                start_url=record.start_url,
                target_url=record.target_url,
                target_label=record.target_label,
                question=record.question,
                shortest_hops=record.shortest_hops,
            )
        )
    return missions
