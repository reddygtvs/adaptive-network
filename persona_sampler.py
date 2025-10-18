#!/usr/bin/env python3
"""
Persona-weighted trajectory sampler for the pruned CSU Chico graph.

This small utility shows how simple keyword-based weighting keeps random walks
inside persona-specific site neighborhoods (e.g., Computer Science, Nursing,
Kinesiology). It uses the navigation-pruned graph so global footer links do not
dominate the walks.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

import networkx as nx

from csuchico_graph_refined import create_csuchico_graph_refined


@dataclass
class PersonaConfig:
    start_nodes: Sequence[str]
    keywords: Sequence[str]
    avoid_keywords: Sequence[str]
    keyword_boost: float
    avoid_penalty: float
    min_length: int
    max_length: int
    stop_probability: float


PERSONAS: Dict[str, PersonaConfig] = {
    "computer_science": PersonaConfig(
        start_nodes=[
            "https://www.csuchico.edu/academics/college/engineering/departments/computer-science/index.shtml",
            "https://www.csuchico.edu/academics/majors-programs/computer-science-bs.shtml",
        ],
        keywords=(
            "computer-science",
            "csci",
            "cyber",
            "engineering",
            "software",
        ),
        avoid_keywords=("nurs", "kine", "athletic-training"),
        keyword_boost=4.0,
        avoid_penalty=0.3,
        min_length=4,
        max_length=8,
        stop_probability=0.12,
    ),
    "nursing": PersonaConfig(
        start_nodes=[
            "https://www.csuchico.edu/nurs/index.shtml",
            "https://www.csuchico.edu/academics/majors-programs/nursing-bs.shtml",
        ],
        keywords=(
            "nurs",
            "rn-bsn",
            "preceptorship",
            "clinical",
            "health",
        ),
        avoid_keywords=("csci", "kine", "engineering"),
        keyword_boost=4.0,
        avoid_penalty=0.25,
        min_length=5,
        max_length=9,
        stop_probability=0.1,
    ),
    "kinesiology": PersonaConfig(
        start_nodes=[
            "https://www.csuchico.edu/academics/college/communication-education/departments/kinesiology/index.shtml",
            "https://www.csuchico.edu/academics/majors-programs/kinesiology-ba.shtml",
        ],
        keywords=(
            "kine",
            "kinesiology",
            "physical-activity",
            "exercise",
        ),
        avoid_keywords=("nurs", "csci"),
        keyword_boost=4.0,
        avoid_penalty=0.25,
        min_length=4,
        max_length=8,
        stop_probability=0.1,
    ),
}


def _build_transition_matrix(
    graph: nx.DiGraph, config: PersonaConfig
) -> Dict[str, List[Tuple[str, float]]]:
    """Compute weighted transitions for a persona."""
    transitions: Dict[str, List[Tuple[str, float]]] = {}
    for node in graph.nodes():
        successors = list(graph.successors(node))
        if not successors:
            continue

        weights: List[float] = []
        for target in successors:
            weight = 1.0
            target_label = graph.nodes[target].get("label", "")
            url_lower = target.lower()
            label_lower = target_label.lower()

            if any(keyword in url_lower or keyword in label_lower for keyword in config.keywords):
                weight *= config.keyword_boost

            if any(keyword in url_lower or keyword in label_lower for keyword in config.avoid_keywords):
                weight *= config.avoid_penalty

            # Encourage staying within the same directory path.
            if _same_department_path(node, target):
                weight *= 1.6

            weights.append(weight)

        # If all weights collapsed to zero (extreme penalty), fall back to uniform.
        if not any(weight > 0 for weight in weights):
            weights = [1.0 for _ in successors]

        # Normalize to probabilities.
        total = sum(weights)
        transitions[node] = [
            (succ, weight / total) for succ, weight in zip(successors, weights)
        ]
    return transitions


def _same_department_path(source: str, target: str) -> bool:
    """Heuristic: check if source and target share the same department directory."""
    source_parts = source.split("/")
    target_parts = target.split("/")
    if len(source_parts) < 6 or len(target_parts) < 6:
        return False
    return source_parts[:6] == target_parts[:6]


def sample_trajectory(
    persona: str,
    transitions: Dict[str, List[Tuple[str, float]]],
    config: PersonaConfig,
    rng: random.Random,
) -> List[str]:
    """Draw a single trajectory for the persona."""
    current = rng.choice(config.start_nodes)
    trajectory = [current]

    length = rng.randint(config.min_length, config.max_length)
    for _ in range(length - 1):
        if current not in transitions:
            break
        choices, probs = zip(*transitions[current])
        next_node = rng.choices(choices, probs)[0]
        if next_node == current and len(choices) > 1:
            alternatives = [(c, p) for c, p in transitions[current] if c != current]
            if alternatives:
                alt_choices, alt_probs = zip(*alternatives)
                total = sum(alt_probs)
                alt_probs = [p / total for p in alt_probs]
                next_node = rng.choices(alt_choices, alt_probs)[0]
        current = next_node
        trajectory.append(current)

        if rng.random() < config.stop_probability:
            break
    return trajectory


def generate_samples(
    persona: str, steps: int = 5, seed: int = 13
) -> List[List[str]]:
    """Convenience wrapper to generate a handful of sample trajectories."""
    config = PERSONAS[persona]
    graph = create_csuchico_graph_refined()
    transitions = _build_transition_matrix(graph, config)
    rng = random.Random(seed)
    return [
        sample_trajectory(persona, transitions, config, rng)
        for _ in range(steps)
    ]


if __name__ == "__main__":
    for persona in PERSONAS:
        print("=" * 70)
        print(f"Persona: {persona}")
        print("=" * 70)
        samples = generate_samples(persona, steps=5, seed=42)
        for idx, path in enumerate(samples, 1):
            print(f"\nSample {idx}:")
            for node in path:
                print("  -", node)
