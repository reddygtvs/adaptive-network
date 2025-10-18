#!/usr/bin/env python3
"""
Curated view of the CSU Chico website graph.

This module derives a focused academic subgraph from ``csuchico_graph.py`` by:
1. Removing high-frequency navigation/footer pages.
2. Keeping only URLs that live under academic and admissions subtrees.
3. Dropping isolated nodes left after filtering.

The resulting graph is far smaller, department-centric, and suitable for
persona-specific navigation experiments.
"""

from __future__ import annotations

from urllib.parse import urlparse
from typing import Iterable, Set

import networkx as nx

from csuchico_graph import create_csuchico_graph


# Navigation / footer pages to exclude regardless of in-degree.
DEFAULT_EXCLUDE_PREFIXES = (
    "/contact",
    "/land-acknowledgement",
    "/give",
    "/news",
    "/pres/",
    "/vpbf",
    "/advancement",
    "/emergency",
    "/maps",
    "/social-media",
    "/search",
)

# Academic subtrees to keep. Paths are lowercased and compared against the URL path.
DEFAULT_ALLOWED_PREFIXES = (
    "/academics/college/engineering/departments/computer-science",
    "/academics/majors-programs/computer-science",
    "/academics/college/engineering/resources",
    "/academics/college/engineering/index.shtml",
    "/academics/college/engineering/departments/index.shtml",
    "/nurs",
    "/rcnp",
    "/academics/majors-programs/nursing",
    "/academics/college/communication-education/departments/kinesiology",
    "/academics/majors-programs/kinesiology",
    "/admissions",
    "/apply",
    "/cost-aid",
)

# Nodes with extremely high indegree are treated as navigation/menus.
DEFAULT_NAV_IN_DEGREE_THRESHOLD = 800


def _normalize_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return path.rstrip("/") or "/"


def _matches_prefix(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def _collect_allowed_nodes(
    graph: nx.DiGraph,
    allowed_prefixes: Iterable[str],
    exclude_prefixes: Iterable[str],
    nav_threshold: int,
) -> Set[str]:
    allowed = set()
    prefixes = tuple(prefix.lower().rstrip("/") for prefix in allowed_prefixes)
    exclusions = tuple(prefix.lower().rstrip("/") for prefix in exclude_prefixes)

    for node in graph.nodes():
        if "?" in node or "#" in node:
            continue

        path = _normalize_path(node)
        if _matches_prefix(path, exclusions):
            continue
        if graph.in_degree(node) >= nav_threshold:
            continue
        label = graph.nodes[node].get("label", "").lower()
        if "contact" in label or "land acknowledgement" in label:
            continue
        if _matches_prefix(path, prefixes):
            allowed.add(node)

    return allowed


def create_csuchico_graph_curated(
    *,
    allowed_prefixes: Iterable[str] = DEFAULT_ALLOWED_PREFIXES,
    exclude_prefixes: Iterable[str] = DEFAULT_EXCLUDE_PREFIXES,
    nav_in_degree_threshold: int = DEFAULT_NAV_IN_DEGREE_THRESHOLD,
) -> nx.DiGraph:
    """
    Return a department-focused subgraph of the CSU Chico website.

    Parameters
    ----------
    allowed_prefixes:
        URL path prefixes to retain (case-insensitive). Defaults target the
        Computer Science, Nursing, and Kinesiology areas plus admissions/support.
    exclude_prefixes:
        Path prefixes treated as navigation/footer and removed entirely.
    nav_in_degree_threshold:
        Any node with an in-degree equal to or above this threshold is considered
        a navigation hub and removed.
    """
    raw = create_csuchico_graph()
    allowed_nodes = _collect_allowed_nodes(
        raw,
        allowed_prefixes=allowed_prefixes,
        exclude_prefixes=exclude_prefixes,
        nav_threshold=nav_in_degree_threshold,
    )

    curated = raw.subgraph(allowed_nodes).copy()

    # Drop isolated nodes (no edges after filtering).
    isolated = [node for node in curated.nodes() if curated.degree(node) == 0]
    curated.remove_nodes_from(isolated)

    return curated


if __name__ == "__main__":
    G = create_csuchico_graph_curated()
    print("Curated CSU Chico graph")
    print("Nodes:", G.number_of_nodes())
    print("Edges:", G.number_of_edges())

    in_degrees = sorted(G.in_degree(), key=lambda kv: kv[1], reverse=True)[:10]
    print("\nTop inbound nodes:")
    for node, deg in in_degrees:
        print(f"{deg:5d} -> {G.nodes[node].get('label', node)}")
