from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict, Iterable, List

from csuchico_graph_pruned import create_csuchico_graph_pruned

PERSONA_CONFIG: Dict[str, Dict[str, Iterable[str]]] = {
    "computer_science": {
        "keywords": (r"computer[- ]science", r"\bcsci\b", r"software", r"cyber"),
        "avoid": (r"\bnurs", r"kine"),
    },
    "nursing": {
        "keywords": (r"\bnurs", r"rn-bsn", r"clinical", r"health"),
        "avoid": (r"\bcsci", r"kine"),
    },
    "kinesiology": {
        "keywords": (r"kinesiology", r"\bkine", r"exercise"),
        "avoid": (r"\bnurs", r"\bcsci"),
    },
}


@lru_cache(maxsize=None)
def get_persona_context(persona: str, limit: int = 18) -> List[Dict[str, str]]:
    if persona not in PERSONA_CONFIG:
        raise ValueError(f"Unknown persona '{persona}'")

    graph = create_csuchico_graph_pruned()
    config = PERSONA_CONFIG[persona]

    def matches(url: str, label: str) -> bool:
        return any(
            re.search(pattern, url, re.IGNORECASE) or re.search(pattern, label, re.IGNORECASE)
            for pattern in config["keywords"]
        )

    def should_avoid(url: str, label: str) -> bool:
        return any(
            re.search(pattern, url, re.IGNORECASE) or re.search(pattern, label, re.IGNORECASE)
            for pattern in config["avoid"]
        )

    candidate_nodes = []
    for node, data in graph.nodes(data=True):
        label = data.get("label", node)
        if matches(node, label):
            candidate_nodes.append((node, label))

    if len(candidate_nodes) < limit:
        expansion = []
        for node, label in candidate_nodes:
            for succ in graph.successors(node):
                succ_label = graph.nodes[succ].get("label", succ)
                if not should_avoid(succ, succ_label):
                    expansion.append((succ, succ_label))
        candidate_nodes.extend(expansion)

    seen = set()
    context = []
    for url, label in candidate_nodes:
        if url in seen:
            continue
        seen.add(url)
        context.append({"url": url, "label": label})
        if len(context) >= limit:
            break

    return context
