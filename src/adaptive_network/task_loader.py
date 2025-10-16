from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterable, List


@dataclass
class Task:
    id: str
    persona: str
    query: str
    expected_url: str


def _load_default_tasks() -> Iterable[dict]:
    resource = resources.files("adaptive_network.task_data").joinpath("tasks.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def load_tasks(path: Path | str | None = None) -> List[Task]:
    if path is not None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        data = _load_default_tasks()

    return [
        Task(
            id=item["id"],
            persona=item["persona"],
            query=item["query"],
            expected_url=item["expected_url"],
        )
        for item in data
    ]
