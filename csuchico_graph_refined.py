#!/usr/bin/env python3
"""
Refined CSU Chico website graph.

Starting from the full scrape in ``csuchico_graph.py``, this module removes the
most problematic navigation edges that cause endless loops (e.g. links back to
the homepage, breadcrumbs to parent sections, or global footer targets).

All nodes are retained so higher-level contexts remain available, but the edge
set is filtered to emphasise forward navigation through academic content.
"""

from __future__ import annotations

from typing import Iterable, Set
from urllib.parse import urlparse

import networkx as nx

from csuchico_graph import create_csuchico_graph


DEFAULT_NAV_KEYWORDS = (
    "contact",
    "land acknowledgement",
    "give to chico state",
    "social media",
    "emergency alerts",
    "privacy policy",
)

DEFAULT_NAV_PATH_PREFIXES = (
    "/contact",
    "/give",
    "/land-acknowledgement",
    "/maps",
    "/social-media",
    "/news",
    "/emergency",
    "/pres/",
)

DEFAULT_NAV_IN_DEGREE_THRESHOLD = 500


def _normalize_path(url: str) -> str:
    path = urlparse(url).path or "/"

    if path.endswith(("index.shtml", "index.html", "index.htm", "index.php")):
        path = path[: path.rfind("/")]
        if not path:
            path = "/"

    path = path.rstrip("/")
    if not path:
        path = "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def _is_ancestor(target: str, source: str) -> bool:
    if target == "/":
        return True
    if target == source:
        return True
    return source.startswith(target + "/")


def _is_nav_target(
    node: str,
    label: str,
    nav_nodes: Set[str],
    nav_keywords: Iterable[str],
    nav_prefixes: Iterable[str],
) -> bool:
    if node in nav_nodes:
        return True
    path = _normalize_path(node).lower()
    if any(path.startswith(prefix.rstrip("/")) for prefix in nav_prefixes):
        return True
    label_lower = label.lower()
    return any(keyword in label_lower for keyword in nav_keywords)


def create_csuchico_graph_refined(
    *,
    nav_in_degree_threshold: int = DEFAULT_NAV_IN_DEGREE_THRESHOLD,
    nav_keywords: Iterable[str] = DEFAULT_NAV_KEYWORDS,
    nav_prefixes: Iterable[str] = DEFAULT_NAV_PATH_PREFIXES,
) -> nx.DiGraph:
    raw = create_csuchico_graph()
    refined = nx.DiGraph()
    refined.add_nodes_from(raw.nodes(data=True))

    candidate_nav_nodes = {
        node
        for node, deg in raw.in_degree()
        if deg >= nav_in_degree_threshold
    }

    edges_to_keep = []
    for source, target in raw.edges():
        source_path = _normalize_path(source)
        target_path = _normalize_path(target)
        label = raw.nodes[target].get("label", "")

        if "?" in target or "#" in target:
            continue
        if _is_ancestor(target_path, source_path):
            continue
        if _is_nav_target(target, label, candidate_nav_nodes, nav_keywords, nav_prefixes):
            continue

        edges_to_keep.append((source, target))

    refined.add_edges_from(edges_to_keep)
    isolated = [node for node in refined.nodes() if refined.degree(node) == 0]
    refined.remove_nodes_from(isolated)
    return refined


if __name__ == "__main__":
    G = create_csuchico_graph_refined()
    print("Refined CSU Chico graph")
    print("Nodes:", G.number_of_nodes())
    print("Edges:", G.number_of_edges())
    in_degrees = sorted(G.in_degree(), key=lambda kv: kv[1], reverse=True)[:10]
    print("\nTop inbound nodes:")
    for node, deg in in_degrees:
        print(f"{deg:5d} -> {G.nodes[node].get('label', node)}")
