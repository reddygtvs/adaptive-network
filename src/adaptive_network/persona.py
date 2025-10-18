from __future__ import annotations

from functools import lru_cache
from typing import Dict, List
from urllib.parse import urlparse

from csuchico_graph_refined import create_csuchico_graph_refined

PERSONA_PREFIXES: Dict[str, List[str]] = {
    "computer_science": [
        "/academics/college/engineering/departments/computer-science",
        "/academics/majors-programs/computer-science",
        "/academics/college/engineering/resources",
    ],
    "nursing": [
        "/nurs",
        "/rcnp",
        "/academics/majors-programs/nursing",
    ],
    "kinesiology": [
        "/academics/college/communication-education/departments/kinesiology",
        "/academics/majors-programs/kinesiology",
    ],
}

GLOBAL_SUPPORT_PREFIXES = ("/admissions", "/apply", "/cost-aid")


def _normalize_path(url: str) -> str:
    return urlparse(url).path.lower().rstrip('/') or '/'


def _matches_prefix(url: str, prefixes: List[str]) -> bool:
    path = _normalize_path(url)
    return any(path.startswith(prefix.rstrip('/')) for prefix in prefixes)


@lru_cache(maxsize=None)
def get_refined_graph():
    return create_csuchico_graph_refined()


@lru_cache(maxsize=None)
def get_persona_context(persona: str, limit: int = 60) -> List[Dict[str, str]]:
    if persona not in PERSONA_PREFIXES:
        raise ValueError(f"Unknown persona '{persona}'")

    graph = get_refined_graph()
    prefixes = PERSONA_PREFIXES[persona]

    context = []
    for node, data in graph.nodes(data=True):
        if _matches_prefix(node, prefixes):
            context.append({
                "url": node,
                "label": data.get("label", node),
            })

    support_pages = [
        {
            "url": node,
            "label": data.get("label", node),
        }
        for node, data in graph.nodes(data=True)
        if _matches_prefix(node, list(GLOBAL_SUPPORT_PREFIXES))
    ]
    context.extend(sorted(support_pages, key=lambda item: item["label"])[:20])

    seen = set()
    deduped = []
    for item in context:
        key = _normalize_path(item["url"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= limit:
            break

    return deduped


PERSONA_CONFIG = PERSONA_PREFIXES
