#!/usr/bin/env python3
"""
Simplified view of the CSU Chico website graph.

This module derives a pruned/simplified graph from the full dataset defined in
``csuchico_graph.py`` without mutating the original source. It focuses on
removing the near-global navigation/footer edges that appear on almost every
page so that downstream analysis can surface meaningful, content-specific
paths.

Design goals:
    * Preserve the underlying URLs/nodes so analysts can still trace back to
      the real site.
    * Remove high-frequency template edges (e.g., links to Contact, Land
      Acknowledgement) that overwhelm path analysis.
    * Surface clusters of pages that share identical content-level outgoing
      links after template removal. This makes repeated page structures easier
      to spot when presenting to stakeholders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Set, Tuple

import networkx as nx

from csuchico_graph import create_csuchico_graph


# Inbound link counts above this threshold are treated as global navigation
# targets. Derived from exploratory analysis: only eight nodes exceed 1,000
# inbound edges and they correspond to footer items.
DEFAULT_NAV_IN_DEGREE_THRESHOLD = 1_000

# Minimum cluster size when reporting pages that share the same content-level
# outgoing links.
DEFAULT_MIN_TEMPLATE_CLUSTER = 5


@dataclass
class SimplifiedGraph:
    """Container returned by :func:`create_simplified_graph`."""

    graph: nx.DiGraph
    nav_nodes: Set[str]
    template_clusters: Dict[Tuple[str, ...], List[str]]

    def get_cluster(self, node: str) -> List[str]:
        """Return all nodes that share the same content-level out-neighbors."""
        for signature, members in self.template_clusters.items():
            if node in members:
                return members
        return []


def identify_nav_targets(
    graph: nx.DiGraph,
    threshold: int = DEFAULT_NAV_IN_DEGREE_THRESHOLD,
    extra_targets: Iterable[str] | None = None,
) -> Set[str]:
    """
    Identify navigation/footer targets that should be removed from analysis.

    Parameters
    ----------
    graph:
        The full CSU Chico graph.
    threshold:
        Minimum in-degree required to classify a node as a navigation target.
        The default of 1,000 isolates the eight globally linked footer pages.
    extra_targets:
        Optional iterable of explicit URLs to include (e.g., if reviewers want
        to mark additional nodes as template items).
    """
    nav_nodes: Set[str] = {
        node for node, degree in graph.in_degree() if degree >= threshold
    }
    if extra_targets:
        nav_nodes.update(extra_targets)
    return nav_nodes


def prune_navigation_edges(
    graph: nx.DiGraph, nav_nodes: Set[str]
) -> nx.DiGraph:
    """
    Build a copy of ``graph`` without edges pointing at ``nav_nodes``.

    Any navigation node that becomes isolated is removed to keep the simplified
    graph compact. All other nodes remain intact, even if they lose the bulk of
    their outgoing edges.
    """
    pruned = graph.copy()
    edges_to_remove = [
        (source, target)
        for source, target in pruned.edges()
        if target in nav_nodes
    ]
    pruned.remove_edges_from(edges_to_remove)

    isolated_nav = [node for node in nav_nodes if pruned.degree(node) == 0]
    pruned.remove_nodes_from(isolated_nav)
    return pruned


def find_template_clusters(
    graph: nx.DiGraph,
    min_cluster_size: int = DEFAULT_MIN_TEMPLATE_CLUSTER,
) -> Dict[Tuple[str, ...], List[str]]:
    """
    Group pages that still share identical outgoing links after pruning.

    Returns
    -------
    dict
        Mapping from the sorted tuple of neighbor URLs to the list of pages
        that share that signature. Only clusters with at least
        ``min_cluster_size`` members are returned to keep the structure compact.
    """
    signature_to_nodes: Dict[Tuple[str, ...], List[str]] = {}
    for node in graph.nodes():
        successors = tuple(sorted(graph.successors(node)))
        signature_to_nodes.setdefault(successors, []).append(node)

    return {
        signature: nodes
        for signature, nodes in signature_to_nodes.items()
        if len(nodes) >= min_cluster_size and signature
    }


def create_simplified_graph(
    nav_in_degree_threshold: int = DEFAULT_NAV_IN_DEGREE_THRESHOLD,
    min_template_cluster: int = DEFAULT_MIN_TEMPLATE_CLUSTER,
    extra_nav_targets: Iterable[str] | None = None,
) -> SimplifiedGraph:
    """
    Produce a simplified CSU Chico graph geared for structural analysis.

    Parameters
    ----------
    nav_in_degree_threshold:
        In-degree cutoff for classifying navigation/footer pages.
    min_template_cluster:
        Minimum number of pages that must share an outgoing-link signature to
        be reported in ``template_clusters``.
    extra_nav_targets:
        Optional explicit URLs to treat as navigation nodes regardless of
        in-degree. Useful for experiments or manual overrides.

    Returns
    -------
    SimplifiedGraph
        Data structure containing the pruned graph, the set of navigation nodes
        that were removed, and clusters of pages that still share identical
        content-level out-links.
    """
    full_graph = create_csuchico_graph()
    nav_nodes = identify_nav_targets(
        full_graph,
        threshold=nav_in_degree_threshold,
        extra_targets=extra_nav_targets,
    )
    pruned_graph = prune_navigation_edges(full_graph, nav_nodes)
    clusters = find_template_clusters(
        pruned_graph, min_cluster_size=min_template_cluster
    )
    return SimplifiedGraph(
        graph=pruned_graph, nav_nodes=nav_nodes, template_clusters=clusters
    )


if __name__ == "__main__":
    simplified = create_simplified_graph()
    G = simplified.graph
    print("=" * 70)
    print("SIMPLIFIED CSU CHICO GRAPH")
    print("=" * 70)
    print(f"Original nodes: {create_csuchico_graph().number_of_nodes():,}")
    print(f"Simplified nodes: {G.number_of_nodes():,}")
    print(f"Simplified edges: {G.number_of_edges():,}")
    print(f"Navigation nodes removed: {len(simplified.nav_nodes)}")
    print(f"Template clusters (>= {DEFAULT_MIN_TEMPLATE_CLUSTER} pages): "
          f"{len(simplified.template_clusters)}")

    sample_clusters = list(simplified.template_clusters.values())[:3]
    for idx, cluster in enumerate(sample_clusters, 1):
        print(f"\nCluster {idx} ({len(cluster)} pages):")
        for node in cluster[:5]:
            label = G.nodes[node].get("label", node)
            print(f"  - {label} ({node})")
        if len(cluster) > 5:
            print("  ...")
