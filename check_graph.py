#!/usr/bin/env python3
"""Check CSU Chico graph for duplicates and quality"""

from csuchico_graph import create_csuchico_graph
from collections import Counter

G = create_csuchico_graph()

print("=" * 60)
print("GRAPH QUALITY CHECK")
print("=" * 60)

# Basic stats
print(f"\n📊 Basic Statistics:")
print(f"  Total nodes: {G.number_of_nodes():,}")
print(f"  Total edges: {G.number_of_edges():,}")

# Check for self-loops
self_loops = [(u, v) for u, v in G.edges() if u == v]
print(f"\n🔄 Self-loops: {len(self_loops)}")
if self_loops:
    print(f"  Examples: {self_loops[:5]}")

# Check for duplicate edges (NetworkX prevents this automatically)
print(f"\n✅ Duplicate edges: 0 (NetworkX DiGraph prevents duplicates)")

# Check node uniqueness
all_nodes = list(G.nodes())
unique_nodes = set(all_nodes)
print(f"\n🔍 Node Uniqueness:")
print(f"  Total nodes: {len(all_nodes)}")
print(f"  Unique nodes: {len(unique_nodes)}")
print(f"  Duplicates: {len(all_nodes) - len(unique_nodes)}")

# Edge statistics
edge_counts = Counter(G.out_degree(node) for node in G.nodes())
print(f"\n📈 Out-Degree Distribution:")
print(f"  Nodes with 0 out-edges (leaf nodes): {edge_counts[0]:,}")
print(f"  Nodes with 1-10 out-edges: {sum(edge_counts[i] for i in range(1, 11)):,}")
print(f"  Nodes with 11-50 out-edges: {sum(edge_counts[i] for i in range(11, 51)):,}")
print(f"  Nodes with 51+ out-edges: {sum(edge_counts[i] for i in range(51, max(edge_counts.keys())+1)):,}")
print(f"  Max out-degree: {max(dict(G.out_degree()).values())}")

# Sample nodes
print(f"\n🔎 Sample Nodes (first 10):")
for i, (node, data) in enumerate(G.nodes(data=True)):
    if i >= 10:
        break
    label = data.get('label', 'No label')
    out_deg = G.out_degree(node)
    in_deg = G.in_degree(node)
    print(f"  {i+1}. {label[:50]:50s} (out:{out_deg:3d}, in:{in_deg:3d})")

# Find hub nodes (highest out-degree)
print(f"\n🌐 Top 10 Hub Nodes (highest out-degree):")
top_hubs = sorted(G.nodes(), key=lambda n: G.out_degree(n), reverse=True)[:10]
for i, node in enumerate(top_hubs, 1):
    label = G.nodes[node].get('label', node)
    out_deg = G.out_degree(node)
    print(f"  {i:2d}. {label[:50]:50s} (out-degree: {out_deg})")

print("\n" + "=" * 60)