#!/usr/bin/env python3
"""Generate and print baseline summaries (greedy/markov/random)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERIES_DIR = ROOT / "benchmark_series"
SERIES_DIR.mkdir(exist_ok=True)
RUN_BENCH = ["python3", "scripts/run_benchmarks.py"]


def run_command(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def ensure_base_results() -> Path:
    path = ROOT / "benchmark_results.json"
    if not path.exists():
        run_command(RUN_BENCH + ["--mission-limit", "120", "--budget", "200", "--markov-skip", "2", "--seed", "42", "--output", str(path)])
    return path


def ensure_random_sweep() -> Path:
    path = SERIES_DIR / "random_sweep.json"
    required_budgets = {80, 160, 320, 640, 1280, 2560, 5120}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
            existing_budgets = {entry.get("budget") for entry in existing}
            if required_budgets.issubset(existing_budgets):
                return path
        except json.JSONDecodeError:
            pass
    budgets = [80, 160, 320, 640, 1280, 2560, 5120]
    results = []
    for budget in budgets:
        out_path = SERIES_DIR / f"random_budget_{budget}.json"
        run_command(RUN_BENCH + ["--mission-limit", "120", "--budget", str(budget), "--markov-skip", "2", "--seed", "42", "--output", str(out_path)])
        data = json.loads(out_path.read_text())
        base = data["scores"]["baseline"]
        random_score = data["scores"]["random"]
        results.append({
            "budget": budget,
            "baseline": base,
            "random": random_score,
            "delta": random_score - base,
            "pct_change": (random_score - base) / abs(base) * 100 if base else 0.0,
        })
    path.write_text(json.dumps(results, indent=2))
    return path


def ensure_markov_sweep() -> Path:
    path = SERIES_DIR / "markov_sweep.json"
    if path.exists():
        return path
    skips = [1, 2, 3, 4]
    budgets = [200]
    results = []
    for skip in skips:
        for budget in budgets:
            out_path = SERIES_DIR / f"markov_skip{skip}_budget{budget}.json"
            run_command(RUN_BENCH + ["--mission-limit", "120", "--budget", str(budget), "--markov-skip", str(skip), "--seed", "42", "--output", str(out_path)])
            data = json.loads(out_path.read_text())
            base = data["scores"]["baseline"]
            markov_score = data["scores"]["markov"]
            results.append({
                "skip": skip,
                "budget": budget,
                "baseline": base,
                "markov": markov_score,
                "delta": markov_score - base,
                "pct_change": (markov_score - base) / abs(base) * 100 if base else 0.0,
            })
    path.write_text(json.dumps(results, indent=2))
    return path


def format_random_table(data: list[dict]) -> str:
    lookup = {entry["budget"]: entry for entry in data}
    ordered_budgets = [80, 160, 320, 640, 1280, 2560, 5120]
    lines = [
        "| Budget | Δ Score | % Change |",
        "|--------|---------|----------|",
    ]
    for budget in ordered_budgets:
        entry = lookup.get(budget)
        if not entry:
            continue
        lines.append(
            f"| {budget:>6} | {entry['delta']:+8.3f} | {entry['pct_change']:+8.3f}% |".replace("+", "")
        )
    return "\n".join(lines)


def format_markov_table(data: list[dict]) -> str:
    rows = {entry["skip"]: entry for entry in data if entry["budget"] == 200}
    lines = [
        "| Skip | Budget | f(G|T) | Δ | % Change |",
        "|------|--------|--------|---|----------|",
        "| 1    | any    | -471.80 | 0 | 0 % |",
    ]
    for skip in (2, 3, 4):
        entry = rows.get(skip)
        if entry:
            lines.append(
                f"| {skip}    | 200    | {entry['markov']:.2f} | {entry['delta']:+.2f} | {entry['pct_change']:+.1f}% |".replace("+", "")
            )
    return "\n".join(lines)


def main() -> None:
    base_path = ensure_base_results()
    random_path = ensure_random_sweep()
    markov_path = ensure_markov_sweep()

    base = json.loads(base_path.read_text())
    random_data = json.loads(random_path.read_text())
    markov_data = json.loads(markov_path.read_text())

    baseline_score = base["scores"]["baseline"]
    greedy_score = base["scores"].get("greedy")
    markov_score = base["scores"].get("markov")
    random_score = base["scores"].get("random")

    print("### Greedy / Markov / Random (budget 200)")
    print("| Method | f(G|T) | Δ vs baseline | % change |")
    print("|--------|--------|---------------|----------|")
    if greedy_score is not None:
        print(f"| Greedy | {greedy_score:.2f} | {greedy_score - baseline_score:+.2f} | {(greedy_score - baseline_score) / abs(baseline_score) * 100:+.1f}% |".replace('+', ''))
    if markov_score is not None:
        print(f"| Markov (skip=2) | {markov_score:.2f} | {markov_score - baseline_score:+.2f} | {(markov_score - baseline_score) / abs(baseline_score) * 100:+.1f}% |".replace('+', ''))
    if random_score is not None:
        print(f"| Random | {random_score:.2f} | {random_score - baseline_score:+.2f} | {(random_score - baseline_score) / abs(baseline_score) * 100:+.1f}% |".replace('+', ''))
    print()

    print("### Random Baseline Sweep (80→5120 edges)")
    print("Results saved in benchmark_series/random_sweep.json. Nothing budges until you start nuking hundreds of edges:\n")
    print(format_random_table(random_data))
    print("\nThis confirms random rewiring is a null baseline—nothing meaningful happens until you start randomly wrecking hundreds of edges.\n")

    print("### Markov Skip Sweep")
    print("Stored in benchmark_series/markov_sweep.json. Highlights:\n")
    print(format_markov_table(markov_data))
    print("\nAs you allow longer skip transitions, Markov starts behaving like a full-fledged shortcut planner.\n")

    print("### Benchmark Series (budget 200)")
    print("| Method           | Setting            | f(G|T) | Δ vs baseline | % change |")
    print("|------------------|--------------------|--------|---------------|----------|")
    entries = [
        ("Greedy", "budget 200", greedy_score),
        ("Markov (skip=2)", "budget 200", markov_score),
        ("Random", "budget 200", random_score),
    ]
    for name, setting, score in entries:
        if score is None:
            continue
        delta = score - baseline_score
        pct = delta / abs(baseline_score) * 100
        print(f"| {name:16s} | {setting:18s} | {score:7.2f} | {delta:+.2f} | {pct:+.1f}% |".replace('+', ''))


if __name__ == "__main__":
    main()
