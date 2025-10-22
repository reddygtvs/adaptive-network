from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from . import ledger
from .agents import critique_answer, run_navigation
from .graph import PERSONA_PREFIXES, page_label, persona_scaffold
from .missions import Mission, load_missions

INPUT_RATE = 0.6 / 1_000_000
CACHED_INPUT_RATE = 0.11 / 1_000_000
OUTPUT_RATE = 2.2 / 1_000_000

MAIN_PROMPT = "Main agent disabled; missions are passed directly to the navigator."


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


def _print_header(cycle: int, mission: Mission) -> None:
    print(f"\n=== Cycle {cycle} :: Mission ({mission.persona}) ===")
    print(mission.question)
    print(f"[Start] {page_label(mission.start_url)} — {mission.start_url}")


def run_cycle(
    *,
    cycle: int,
    missions: Iterable[Mission],
    persona_bases: Dict[str, List[Dict[str, str]]],
    prompt_id: int,
    scaffold_id: int,
) -> Dict[str, float]:
    successes = 0
    total_cost = 0.0
    mission_list = list(missions)

    for mission in mission_list:
        _print_header(cycle, mission)
        base_context = persona_bases.get(mission.persona, [])
        initial_pages = [
            page for page in base_context
            if _normalize(page["url"]) not in {_normalize(mission.target_url), _normalize(mission.start_url)}
        ]

        t_start = time.time()
        payload, call_log, known_pages = run_navigation(
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
        print(f"[Navigator] action={payload.get('action')} url={chosen_url} confidence={confidence}")

        critique_payload, critique_raw = critique_answer(
            persona=mission.persona,
            question=mission.question,
            expected_url=mission.target_url,
            assistant_output=payload,
        )
        print(f"[Critique] state={critique_payload.get('state')} -> final={critique_payload.get('revised_url') or chosen_url}")

        critique_usage = _usage_from_raw(critique_raw)
        task_cost = float(usage["cost"] + critique_usage["cost"])
        total_cost += task_cost

        final_url = critique_payload.get("revised_url") or chosen_url
        success = _normalize(final_url) == _normalize(mission.target_url)
        if critique_payload.get("state") == "fail":
            success = False
        elif critique_payload.get("state") == "retry" and success:
            success = True
        if success:
            successes += 1

        print(
            f"[Metrics] success={success} | tokens_in={usage['input_tokens']} "
            f"| tokens_out={usage['output_tokens']} | cost=${task_cost:.4f} | elapsed={elapsed_ms}ms"
        )

        ledger.log_task(
            ledger.MissionLog(
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
        )

    print(f"\nCycle {cycle} complete :: {successes}/{len(mission_list)} successes | cost=${total_cost:.4f}")
    return {"successes": successes, "total_cost": total_cost, "tasks": len(mission_list)}


def main(*, cycles: int = 1, missions_path: Path | str = Path("data/missions.json")) -> None:
    ledger.init_db()
    missions = load_missions(missions_path)
    ledger.register_missions(missions)

    persona_bases = {persona: persona_scaffold(persona, limit=30) for persona in PERSONA_PREFIXES}
    prompt_id = ledger.save_prompt(MAIN_PROMPT)
    scaffold_id = ledger.save_scaffold(json.dumps(persona_bases, ensure_ascii=False, indent=2))

    for cycle in range(1, cycles + 1):
        run_cycle(
            cycle=cycle,
            missions=missions,
            persona_bases=persona_bases,
            prompt_id=prompt_id,
            scaffold_id=scaffold_id,
        )


__all__ = ["main", "run_cycle"]
