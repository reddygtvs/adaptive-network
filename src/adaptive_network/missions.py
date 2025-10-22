from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List


@dataclass
class Mission:
    persona: str
    start_url: str
    target_url: str
    target_label: str
    question: str
    shortest_hops: int
    id: int | None = field(default=None, init=False)


def load_missions(path: Path | str = Path("data/missions.json")) -> List[Mission]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    missions = [
        Mission(
            persona=item["persona"],
            start_url=item["start_url"],
            target_url=item["target_url"],
            target_label=item.get("target_label", ""),
            question=item["question"],
            shortest_hops=item.get("shortest_hops", 0),
        )
        for item in data
    ]
    return missions
