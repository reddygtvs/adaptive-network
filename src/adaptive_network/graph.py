from __future__ import annotations

from functools import lru_cache
from typing import Dict, Iterable, List
from urllib.parse import urlparse

import networkx as nx

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

GLOBAL_SUPPORT_PREFIXES: Iterable[str] = (
    "/admissions",
    "/apply",
    "/cost-aid",
    "/student-life",
)


def _normalize_path(url: str) -> str:
    parsed = urlparse(url)
    path = (parsed.path or "/").lower()
    if path.endswith(("index.shtml", "index.html", "index.htm", "index.php")):
        path = path[: path.rfind("/")] or "/"
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


@lru_cache(maxsize=1)
def refined_graph() -> nx.DiGraph:
    return create_csuchico_graph_refined()


def page_label(url: str) -> str:
    graph = refined_graph()
    data = graph.nodes.get(url, {})
    return data.get("label") or url


def neighbors(url: str, *, limit: int = 12) -> List[Dict[str, str]]:
    graph = refined_graph()
    if url not in graph:
        return []
    seen = set()
    results = []
    for target in graph.successors(url):
        norm = _normalize_path(target)
        if norm in seen:
            continue
        seen.add(norm)
        results.append({"url": target, "label": page_label(target)})
        if len(results) >= limit:
            break
    return results


def persona_scaffold(persona: str, *, limit: int = 40) -> List[Dict[str, str]]:
    if persona not in PERSONA_PREFIXES:
        return []
    graph = refined_graph()
    prefixes = PERSONA_PREFIXES[persona]
    candidates: List[Dict[str, str]] = []

    def matches(url: str, search: Iterable[str]) -> bool:
        path = _normalize_path(url)
        return any(path.startswith(prefix.rstrip("/")) for prefix in search)

    for node, data in graph.nodes(data=True):
        if matches(node, prefixes):
            candidates.append({"url": node, "label": data.get("label", node)})

    support = [
        {"url": node, "label": data.get("label", node)}
        for node, data in graph.nodes(data=True)
        if matches(node, GLOBAL_SUPPORT_PREFIXES)
    ]
    candidates.extend(sorted(support, key=lambda item: item["label"]))

    seen = set()
    ordered: List[Dict[str, str]] = []
    for item in candidates:
        key = _normalize_path(item["url"])
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
        if len(ordered) >= limit:
            break
    return ordered


__all__ = [
    "PERSONA_PREFIXES",
    "persona_scaffold",
    "refined_graph",
    "page_label",
    "neighbors",
]
