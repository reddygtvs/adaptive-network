#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from csuchico_graph import create_csuchico_graph


def load_graph(use_refined: bool = False) -> nx.DiGraph:
    if use_refined:
        from csuchico_graph_refined import create_csuchico_graph_refined

        return create_csuchico_graph_refined()
    return create_csuchico_graph()


def load_missions(graph: nx.DiGraph, missions_path: Path, limit: int, seed: int) -> List[Dict[str, object]]:
    data = json.loads(missions_path.read_text(encoding="utf-8"))
    rng = random.Random(seed)
    rng.shuffle(data)

    missions: List[Dict[str, object]] = []
    for item in data:
        if limit and len(missions) >= limit:
            break
        start = item["start_url"]
        target = item["target_url"]
        if start not in graph or target not in graph:
            continue
        try:
            path = nx.shortest_path(graph, start, target)
        except nx.NetworkXNoPath:
            continue
        if len(path) < 2:
            continue
        missions.append(
            {
                "persona": item["persona"],
                "start": start,
                "target": target,
                "path": path,
            }
        )
    return missions


def trajectory_cost(graph: nx.DiGraph, start: str, target: str) -> float:
    try:
        path = nx.shortest_path(graph, start, target)
    except nx.NetworkXNoPath:
        return 100.0
    cost = 0.0
    for i in range(len(path) - 1):
        u = path[i]
        cost += 1.0
        out_deg = graph.out_degree(u)
        cost += 0.1 * math.log2(1 + out_deg)
    return cost


def calculate_f(graph: nx.DiGraph, missions: Sequence[Dict[str, object]]) -> float:
    total = 0.0
    for mission in missions:
        total += trajectory_cost(graph, mission["start"], mission["target"])
    return -total


def shortlist_shortcut_edges(graph: nx.DiGraph, missions: Sequence[Dict[str, object]]) -> Counter:
    counter: Counter = Counter()
    for mission in missions:
        path = mission["path"]
        for i in range(len(path) - 2):
            u = path[i]
            for j in range(i + 2, len(path)):
                v = path[j]
                if not graph.has_edge(u, v):
                    counter[(u, v)] += 1
    return counter


def baseline_greedy(graph: nx.DiGraph, missions: Sequence[Dict[str, object]], budget: int, verbose: bool = False) -> nx.DiGraph:
    if verbose:
        print("\n=== Greedy baseline ===")
    G = graph.copy()
    candidates = shortlist_shortcut_edges(graph, missions)
    added = 0
    for (u, v), count in candidates.most_common():
        if added >= budget:
            break
        if not G.has_edge(u, v):
            G.add_edge(u, v)
            added += 1
            if verbose:
                print(f"  Added {u} -> {v} (needed {count} trajectories)")
    return G


def baseline_markov(
    graph: nx.DiGraph,
    missions: Sequence[Dict[str, object]],
    budget: int,
    skip: int,
    verbose: bool = False,
) -> nx.DiGraph:
    if verbose:
        print("\n=== Markov baseline ===")
    transitions: Dict[Tuple[str, str], float] = defaultdict(float)
    max_skip = max(skip, 1)
    for mission in missions:
        path = mission["path"]
        for step in range(1, max_skip + 1):
            for i in range(len(path) - step):
                u, v = path[i], path[i + step]
                if not graph.has_edge(u, v):
                    transitions[(u, v)] += 1.0 / step

    if not transitions:
        if verbose:
            print("  No new edges proposed")
        return graph.copy()

    scored: List[Tuple[float, str, str]] = [
        (weight, u, v) for (u, v), weight in transitions.items()
    ]
    scored.sort(reverse=True)
    G = graph.copy()
    added = 0
    for weight, u, v in scored:
        if added >= budget:
            break
        if not G.has_edge(u, v):
            G.add_edge(u, v)
            added += 1
            if verbose:
                print(f"  Added {u} -> {v} (score={weight:.3f})")
    if added == 0 and verbose:
        print("  No new edges proposed")
    return G


def baseline_random(graph: nx.DiGraph, budget: int, seed: int, verbose: bool = False) -> nx.DiGraph:
    if verbose:
        print("\n=== Random rewiring baseline ===")
    rng = random.Random(seed)
    G = graph.copy()
    edges = list(G.edges())
    rng.shuffle(edges)
    removed = edges[: min(budget, len(edges))]
    for u, v in removed:
        G.remove_edge(u, v)
        if verbose:
            print(f"  Removed edge {u} -> {v}")

    nodes = list(G.nodes())
    attempts = 0
    added = 0
    while added < budget and attempts < budget * 50:
        u = rng.choice(nodes)
        v = rng.choice(nodes)
        if u != v and not G.has_edge(u, v):
            G.add_edge(u, v)
            if verbose:
                print(f"  Added random edge {u} -> {v}")
            added += 1
        attempts += 1
    if added == 0 and verbose:
        print("  No random edges added")
    return G


def _print_summary(base_score: float, comparisons: Sequence[Dict[str, object]]) -> None:
    print("\n=== Benchmark summary ===")
    print(f"{'baseline':>12}: score={base_score:.2f}")
    for comp in comparisons:
        method = comp["method"]
        score = comp["score"]
        delta = comp["delta"]
        pct_change = comp["pct_change"]
        pct_str = f"{pct_change:+.2f}%" if pct_change is not None else "n/a"
        print(f"{method:>12}: score={score:.2f} delta={delta:+.2f} ({pct_str})")


def run_benchmarks(
    *,
    missions_path: Path,
    use_refined: bool,
    mission_limit: int,
    budget: int,
    markov_skip: int,
    seed: int,
    verbose: bool = False,
) -> Dict[str, object]:
    base_graph = load_graph(use_refined=use_refined)
    missions = load_missions(base_graph, missions_path, mission_limit, seed)
    if not missions:
        raise RuntimeError("No usable missions found; check mission_limit and graph availability.")

    print(f"Loaded graph: {base_graph.number_of_nodes()} nodes, {base_graph.number_of_edges()} edges")
    print(f"Using {len(missions)} missions (seed={seed})")

    base_score = calculate_f(base_graph, missions)
    print(f"\nBaseline f(G|T): {base_score:.2f}")

    results = {
        "graph": {
            "nodes": base_graph.number_of_nodes(),
            "edges": base_graph.number_of_edges(),
            "refined": use_refined,
        },
        "missions": {
            "count": len(missions),
            "limit": mission_limit,
        },
        "scores": {
            "baseline": base_score,
        },
        "comparisons": [],
    }

    comparisons: List[Dict[str, object]] = results["comparisons"]

    def record(method: str, graph: nx.DiGraph) -> None:
        score = calculate_f(graph, missions)
        results["scores"][method] = score
        delta = score - base_score
        pct_change = (delta / abs(base_score) * 100) if base_score else None
        comparisons.append(
            {
                "method": method,
                "score": score,
                "delta": delta,
                "pct_change": pct_change,
            }
        )

    greedy_graph = baseline_greedy(base_graph, missions, budget, verbose=verbose)
    record("greedy", greedy_graph)

    max_markov_skip = max(1, markov_skip)
    markov_scores: Dict[int, float] = {}
    for skip in range(1, max_markov_skip + 1):
        method_key = f"markov_skip{skip}"
        graph = baseline_markov(base_graph, missions, budget, skip, verbose=verbose)
        record(method_key, graph)
        markov_scores[skip] = results["scores"][method_key]
    if markov_scores:
        results["scores"]["markov"] = markov_scores.get(1)
        results["scores"]["markov_best_skip"] = max(markov_scores, key=lambda k: markov_scores[k])
        results["scores"]["markov_best_score"] = markov_scores[results["scores"]["markov_best_skip"]]

    random_budgets = sorted({budget, 80, 160, 320, 640, 1280, 2560, 5120})
    random_scores: Dict[int, float] = {}
    for random_budget in random_budgets:
        method_key = f"random_budget_{random_budget}"
        graph = baseline_random(base_graph, random_budget, seed, verbose=verbose)
        record(method_key, graph)
        random_scores[random_budget] = results["scores"][method_key]
        if random_budget == budget:
            results["scores"]["random"] = random_scores[random_budget]
    if random_scores:
        results["scores"]["random_best_budget"] = max(random_scores, key=lambda k: random_scores[k])
        results["scores"]["random_best_score"] = random_scores[results["scores"]["random_best_budget"]]

    _print_summary(base_score, comparisons)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run baseline benchmarks on the CSU Chico graph.")
    parser.add_argument("--missions", type=Path, default=Path("data/missions.json"))
    parser.add_argument("--use-refined", action="store_true", help="Use the refined graph instead of the full scrape.")
    parser.add_argument("--mission-limit", type=int, default=60, help="Maximum number of missions to use (0 = all).")
    parser.add_argument("--budget", type=int, default=10, help="Number of edges to add/rewire for each baseline.")
    parser.add_argument(
        "--markov-skip",
        type=int,
        default=4,
        help="Evaluate Markov shortcuts for all hop lengths up to this value.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("benchmark_results.json"))
    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed decisions for each baseline.")
    args = parser.parse_args()

    results = run_benchmarks(
        missions_path=args.missions,
        use_refined=args.use_refined,
        mission_limit=args.mission_limit,
        budget=args.budget,
        markov_skip=args.markov_skip,
        seed=args.seed,
        verbose=args.verbose,
    )

    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\nSaved results to", args.output)


if __name__ == "__main__":
    main()
