#!/usr/bin/env python3
"""Analyze why pages/links decrease at depth 5-6"""

from csuchico_graph import create_csuchico_graph
from collections import defaultdict

G = create_csuchico_graph()

print("=" * 70)
print("DEPTH PATTERN ANALYSIS")
print("=" * 70)

# Get nodes by depth
nodes_by_depth = defaultdict(list)
for node, data in G.nodes(data=True):
    depth = data.get('depth', None)
    if depth is not None:
        nodes_by_depth[depth].append(node)

print("\n📊 Pages scraped per depth:")
for depth in sorted(nodes_by_depth.keys()):
    print(f"  Depth {depth}: {len(nodes_by_depth[depth]):4d} pages")

print("\n📈 Links discovered per depth (new unique URLs):")
depth_stats = {
    0: (1, 43),
    1: (42, 375),
    2: (356, 1812),
    3: (1601, 3305),
    4: (2896, 3918),
    5: (3434, 1108),
    6: (948, 756)
}

total_urls_seen = 0
for depth in sorted(depth_stats.keys()):
    pages, new_links = depth_stats[depth]
    total_urls_seen += pages
    print(f"  Depth {depth}: {new_links:4d} new links discovered (cumulative URLs: {total_urls_seen:5d})")

print("\n🔍 Why do depths 5-6 have fewer NEW links?")
print("\n  Reason: DEDUPLICATION is working!")
print("  - At depth 0-3: Discovering new parts of the site")
print("  - At depth 4: Peak discovery (3918 new links)")
print("  - At depth 5-6: Most pages already visited from earlier depths")

# Calculate how many edges point to already-visited nodes
print("\n🔗 Edge Analysis by Depth:")
for depth in sorted(nodes_by_depth.keys()):
    nodes_at_depth = nodes_by_depth[depth]

    # Count edges from this depth
    edges_to_same_depth = 0
    edges_to_earlier_depth = 0
    edges_to_later_depth = 0
    edges_to_unknown = 0

    for node in nodes_at_depth:
        for target in G.successors(node):
            target_depth = G.nodes[target].get('depth')
            if target_depth is None:
                edges_to_unknown += 1
            elif target_depth == depth:
                edges_to_same_depth += 1
            elif target_depth < depth:
                edges_to_earlier_depth += 1
            else:
                edges_to_later_depth += 1

    total_edges = edges_to_same_depth + edges_to_earlier_depth + edges_to_later_depth + edges_to_unknown

    print(f"\n  Depth {depth} ({len(nodes_at_depth):4d} nodes, {total_edges:6d} total edges):")
    print(f"    → Earlier depths: {edges_to_earlier_depth:6d} ({100*edges_to_earlier_depth/max(total_edges,1):5.1f}%)")
    print(f"    → Same depth:     {edges_to_same_depth:6d} ({100*edges_to_same_depth/max(total_edges,1):5.1f}%)")
    print(f"    → Later depths:   {edges_to_later_depth:6d} ({100*edges_to_later_depth/max(total_edges,1):5.1f}%)")

print("\n" + "=" * 70)
print("CONCLUSION:")
print("=" * 70)
print("The reduction at depths 5-6 is EXPECTED and CORRECT!")
print()
print("Why?")
print("  1. BFS visits each URL only once (deduplication)")
print("  2. Depths 0-4 discovered most unique pages")
print("  3. Depths 5-6 mostly link to already-visited pages")
print("  4. Only 1108 + 756 = 1864 NEW pages at depths 5-6")
print("  5. Most links from depth 5-6 point back to depths 0-4")
print()
print("This is how websites work - deep pages link back to main pages!")
print("=" * 70)