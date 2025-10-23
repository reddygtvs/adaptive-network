from __future__ import annotations

import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from . import ledger
from .agents import critique_answer, run_controller, run_navigation
from .graph import PERSONA_PREFIXES, page_label, persona_scaffold
from .missions import Mission, load_missions

INPUT_RATE = 0.6 / 1_000_000
CACHED_INPUT_RATE = 0.11 / 1_000_000
OUTPUT_RATE = 2.2 / 1_000_000

MAIN_PROMPT = "Main agent disabled; missions are passed directly to the navigator."

BATCH_SIZE = 10
STAGGER_SECONDS = 0.35


@dataclass
class MissionOutcome:
    order: int
    mission: Mission
    success: bool
    total_cost: float
    elapsed_ms: int
    usage: Dict[str, float]
    critique_usage: Dict[str, float]
    chosen_url: str | None
    final_url: str | None
    critique_payload: Dict[str, Any]
    log_entry: ledger.MissionLog
    console_lines: List[str]

def _compute_cost(input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    effective_cached = min(cached_tokens or 0, input_tokens or 0)
    effective_input = max((input_tokens or 0) - effective_cached, 0)
    return (
        effective_input * INPUT_RATE
        + effective_cached * CACHED_INPUT_RATE
        + (output_tokens or 0) * OUTPUT_RATE
    )


def _usage_from_raw(raw: Dict[str, object]) -> Dict[str, float]:
    usage = raw.get("usage") if isinstance(raw, dict) else None
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0, "cache_tokens": 0, "cost": 0.0, "duration_ms": 0}
    input_tokens = usage.get("input_tokens") or 0
    output_tokens = usage.get("output_tokens") or 0
    cache_tokens = usage.get("cache_read_input_tokens") or 0
    duration_ms = raw.get("duration_api_ms") if isinstance(raw.get("duration_api_ms"), (int, float)) else 0
    cost = _compute_cost(int(input_tokens), int(cache_tokens), int(output_tokens))
    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cache_tokens": int(cache_tokens),
        "cost": float(cost),
        "duration_ms": float(duration_ms or 0),
    }


def _aggregate_usage(raw_items: Iterable[Dict[str, object]]) -> Dict[str, float]:
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_tokens": 0, "cost": 0.0, "duration_ms": 0.0}
    for raw in raw_items:
        stats = _usage_from_raw(raw)
        totals["input_tokens"] += stats["input_tokens"]
        totals["output_tokens"] += stats["output_tokens"]
        totals["cache_tokens"] += stats["cache_tokens"]
        totals["cost"] += stats["cost"]
        totals["duration_ms"] += stats["duration_ms"]
    return totals


def _normalize(url: str | None) -> str | None:
    if not url:
        return None
    return url.rstrip("/").lower()


def _build_initial_pages(
    mission: Mission,
    persona_bases: Dict[str, List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    base_context = persona_bases.get(mission.persona, [])
    target_norm = _normalize(mission.target_url)
    start_norm = _normalize(mission.start_url)
    return [
        item
        for item in base_context
        if _normalize(item["url"]) not in {target_norm, start_norm}
    ]


def _mission_worker(
    *,
    cycle: int,
    order: int,
    mission: Mission,
    persona_bases: Dict[str, List[Dict[str, str]]],
    prompt_id: int,
    scaffold_id: int,
    delay: float,
) -> MissionOutcome:
    time.sleep(max(delay, 0))
    start_label = page_label(mission.start_url)
    initial_pages = _build_initial_pages(mission, persona_bases)

    t_start = time.time()
    payload, call_log, _known = run_navigation(
        persona=mission.persona,
        question=mission.question,
        start_url=mission.start_url,
        initial_pages=initial_pages,
        max_expansions=max(6, mission.shortest_hops + 2),
    )
    elapsed_ms = int((time.time() - t_start) * 1000)

    raw_records = [entry["raw"] for entry in call_log]
    usage = _aggregate_usage(raw_records)

    chosen_url = payload.get("chosen_url")
    confidence = payload.get("confidence")

    critique_payload, critique_raw = critique_answer(
        persona=mission.persona,
        question=mission.question,
        expected_url=mission.target_url,
        assistant_output=payload,
    )
    critique_usage = _usage_from_raw(critique_raw)

    final_url = critique_payload.get("revised_url") or chosen_url
    success = _normalize(final_url) == _normalize(mission.target_url)
    if critique_payload.get("state") == "fail":
        success = False
    elif critique_payload.get("state") == "retry" and success:
        success = True

    task_cost = float(usage["cost"] + critique_usage["cost"])

    console_lines = [
        f"\n=== Cycle {cycle} :: Mission ({mission.persona}) ===",
        mission.question,
        f"[Start] {start_label} — {mission.start_url}",
        f"[Navigator] action={payload.get('action')} url={chosen_url} confidence={confidence}",
        f"[Critique] state={critique_payload.get('state')} -> final={final_url}",
        (
            f"[Metrics] success={success} | tokens_in={usage['input_tokens']} "
            f"| tokens_out={usage['output_tokens']} | cost=${task_cost:.4f} | elapsed={elapsed_ms}ms"
        ),
    ]

    log_entry = ledger.MissionLog(
        cycle=cycle,
        mission_id=mission.id or 0,
        persona=mission.persona,
        success=success,
        start_url=mission.start_url,
        target_url=mission.target_url,
        predicted_url=final_url,
        prompt_id=prompt_id,
        scaffold_id=scaffold_id,
        shortest_hops=mission.shortest_hops,
        subagent_tokens_in=int(usage["input_tokens"]),
        subagent_tokens_out=int(usage["output_tokens"]),
        subagent_cost=float(usage["cost"]),
        critique_tokens_in=int(critique_usage["input_tokens"]),
        critique_tokens_out=int(critique_usage["output_tokens"]),
        critique_cost=float(critique_usage["cost"]),
        total_cost=task_cost,
        wall_time_ms=elapsed_ms,
        critique_state=critique_payload.get("state"),
        critique_justification=critique_payload.get("justification"),
        raw_response=call_log,
        raw_critique=critique_raw,
    )

    return MissionOutcome(
        order=order,
        mission=mission,
        success=success,
        total_cost=task_cost,
        elapsed_ms=elapsed_ms,
        usage=usage,
        critique_usage=critique_usage,
        chosen_url=chosen_url,
        final_url=final_url,
        critique_payload=critique_payload,
        log_entry=log_entry,
        console_lines=console_lines,
    )


def run_cycle(
    *,
    cycle: int,
    missions: Iterable[Mission],
    persona_bases: Dict[str, List[Dict[str, str]]],
    prompt_id: int,
    scaffold_id: int,
) -> Dict[str, Any]:
    mission_list = list(missions)
    outcomes: List[MissionOutcome] = []
    successes = 0
    total_cost = 0.0

    for batch_start in range(0, len(mission_list), BATCH_SIZE):
        batch = mission_list[batch_start : batch_start + BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = [
                executor.submit(
                    _mission_worker,
                    cycle=cycle,
                    order=batch_start + offset,
                    mission=mission,
                    persona_bases=persona_bases,
                    prompt_id=prompt_id,
                    scaffold_id=scaffold_id,
                    delay=offset * STAGGER_SECONDS,
                )
                for offset, mission in enumerate(batch)
            ]

            batch_outcomes = [future.result() for future in futures]
            batch_outcomes.sort(key=lambda outcome: outcome.order)

        for outcome in batch_outcomes:
            for line in outcome.console_lines:
                print(line)
            ledger.log_task(outcome.log_entry)
            if outcome.success:
                successes += 1
            total_cost += outcome.total_cost
        outcomes.extend(batch_outcomes)

    print(f"\nCycle {cycle} complete :: {successes}/{len(mission_list)} successes | cost=${total_cost:.4f}")
    return {
        "successes": successes,
        "total_cost": total_cost,
        "tasks": len(mission_list),
        "outcomes": outcomes,
    }


def _summarize_outcomes(cycle: int, outcomes: List[MissionOutcome]) -> Dict[str, Any]:
    persona_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"missions": 0, "successes": 0, "failures": 0, "cost": 0.0})
    hardness_stats: Dict[int, Dict[str, Any]] = defaultdict(lambda: {"missions": 0, "successes": 0, "failures": 0})
    failures: List[Dict[str, Any]] = []

    total_cost = 0.0
    total_successes = 0

    for outcome in outcomes:
        persona = outcome.mission.persona
        persona_stats[persona]["missions"] += 1
        persona_stats[persona]["cost"] += outcome.total_cost
        total_cost += outcome.total_cost

        hops = outcome.mission.shortest_hops
        hardness_stats[hops]["missions"] += 1

        if outcome.success:
            persona_stats[persona]["successes"] += 1
            hardness_stats[hops]["successes"] += 1
            total_successes += 1
        else:
            persona_stats[persona]["failures"] += 1
            hardness_stats[hops]["failures"] += 1
            failures.append(
                {
                    "mission_id": outcome.mission.id,
                    "persona": persona,
                    "question": outcome.mission.question,
                    "start_url": outcome.mission.start_url,
                    "target_url": outcome.mission.target_url,
                    "final_url": outcome.final_url,
                    "critique_state": outcome.critique_payload.get("state"),
                    "shortest_hops": hops,
                }
            )

    total_missions = len(outcomes)
    failure_count = total_missions - total_successes
    success_rate = total_successes / total_missions if total_missions else 0.0

    persona_view = {}
    for persona, stats in persona_stats.items():
        missions = stats["missions"] or 1
        persona_view[persona] = {
            "missions": stats["missions"],
            "successes": stats["successes"],
            "failures": stats["failures"],
            "success_rate": stats["successes"] / missions,
            "avg_cost": stats["cost"] / missions,
        }

    hardness_view = {}
    for hops, stats in sorted(hardness_stats.items()):
        missions = stats["missions"] or 1
        hardness_view[hops] = {
            "missions": stats["missions"],
            "successes": stats["successes"],
            "failures": stats["failures"],
            "success_rate": stats["successes"] / missions,
        }

    summary = {
        "cycle": cycle,
        "missions": total_missions,
        "successes": total_successes,
        "failures": failure_count,
        "success_rate": success_rate,
        "total_cost": total_cost,
        "avg_cost": total_cost / total_missions if total_missions else 0.0,
        "persona_stats": persona_view,
        "hardness_stats": hardness_view,
        "notable_failures": failures[:15],
    }
    return summary


def main(*, cycles: int = 1, missions_path: Path | str = Path("data/missions.json")) -> None:
    ledger.init_db()
    missions = load_missions(missions_path)
    ledger.register_missions(missions)

    persona_bases = {persona: persona_scaffold(persona, limit=30) for persona in PERSONA_PREFIXES}
    prompt_id = ledger.save_prompt(MAIN_PROMPT)
    scaffold_body = json.dumps(persona_bases, ensure_ascii=False, indent=2)
    scaffold_id = ledger.save_scaffold(scaffold_body)

    for cycle in range(1, cycles + 1):
        results = run_cycle(
            cycle=cycle,
            missions=missions,
            persona_bases=persona_bases,
            prompt_id=prompt_id,
            scaffold_id=scaffold_id,
        )
        outcomes: List[MissionOutcome] = results.get("outcomes", [])
        summary = _summarize_outcomes(cycle, outcomes)

        successes = results.get("successes", 0)
        tasks = results.get("tasks", len(outcomes))
        failures = tasks - successes
        total_cost = float(results.get("total_cost", 0.0))

        ledger.record_cycle_metrics(
            cycle=cycle,
            successes=successes,
            failures=failures,
            total_cost=total_cost,
            payload=summary,
        )

        controller_payload, controller_raw = run_controller(
            summary=summary,
            controller_prompt=MAIN_PROMPT,
            scaffolding=persona_bases,
        )
        action = str(controller_payload.get("action", "no_change"))
        suggestion = controller_payload.get("suggestion")
        rationale = controller_payload.get("rationale")
        ledger.log_revision(
            cycle=cycle,
            target=action,
            suggestion=suggestion if isinstance(suggestion, str) else None,
            rationale=rationale if isinstance(rationale, str) else None,
            payload=controller_payload if isinstance(controller_payload, dict) else {"raw": controller_payload},
            prompt_id=prompt_id,
            scaffold_id=scaffold_id,
            raw_response=controller_raw,
        )

        print(f"[Controller] action={action} | confidence={controller_payload.get('confidence')}")


__all__ = ["main", "run_cycle"]
