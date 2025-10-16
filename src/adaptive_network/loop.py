from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

from . import ledger
from .ledger import TaskLog
from .llm import call_claude
from .main_agent import load_main_prompt, plan_task
from .persona import PERSONA_CONFIG, get_persona_context
from .subagent import run_subagent
from .task_loader import Task, load_tasks


def extract_usage(raw: Mapping[str, object]) -> Dict[str, float | int]:
    usage = raw.get("usage") if isinstance(raw, Mapping) else None
    if not isinstance(usage, Mapping):
        return {"input_tokens": None, "output_tokens": None, "cost": None, "duration_ms": None}
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cost": raw.get("total_cost_usd"),
        "duration_ms": raw.get("duration_api_ms"),
    }


def print_task_header(cycle: int, task: Task) -> None:
    print(f"\n=== Cycle {cycle} :: Task {task.id} ({task.persona}) ===")
    print(task.query)


def build_scaffolding() -> Dict[str, List[Dict[str, str]]]:
    return {persona: get_persona_context(persona) for persona in PERSONA_CONFIG}


def run_cycle(
    *,
    cycle: int,
    tasks: Iterable[Task],
    main_prompt: str,
    scaffolding: Dict[str, List[Dict[str, str]]],
) -> Dict[str, float]:
    task_list = list(tasks)
    prompt_id = ledger.save_prompt(main_prompt)
    scaffold_body = json.dumps(scaffolding, ensure_ascii=False, indent=2)
    scaffold_id = ledger.save_scaffold(scaffold_body)

    successes = 0
    total_cost = 0.0

    for task in task_list:
        print_task_header(cycle, task)
        context = scaffolding[task.persona]

        brief_payload = plan_task(
            persona=task.persona,
            query=task.query,
            context=context,
            system_prompt=main_prompt,
        )
        task_brief = brief_payload.get("task_brief", "").strip()
        notes = brief_payload.get("notes", "")
        if task_brief:
            print(f"[Main brief] {task_brief}")
        if notes:
            print(f"[Main notes] {notes}")

        augmented_query = (
            f"{task_brief}\n\nOriginal request: {task.query}" if task_brief else task.query
        )

        t_start = time.time()
        sub_payload, sub_raw, critique_payload, critique_raw = run_subagent(
            persona=task.persona,
            query=augmented_query,
            expected_url=task.expected_url,
            context=context,
        )
        elapsed_ms = int((time.time() - t_start) * 1000)

        sub_metrics = extract_usage(sub_raw)
        crit_metrics = extract_usage(critique_raw)

        chosen_url = sub_payload.get("chosen_url")
        critique_state = critique_payload.get("state")
        final_url = critique_payload.get("revised_url") or chosen_url

        success = bool(final_url and task.expected_url in final_url)
        if critique_state == "fail":
            success = False
        elif critique_state == "retry" and final_url and task.expected_url in final_url:
            success = True

        if success:
            successes += 1

        cost_components = [
            component
            for component in (sub_metrics.get("cost"), crit_metrics.get("cost"))
            if component is not None
        ]
        task_cost = float(sum(cost_components))
        total_cost += task_cost

        print(f"[Subagent] URL={chosen_url} confidence={sub_payload.get('confidence')}")
        print(f"[Critique] state={critique_state} -> final_url={final_url}")
        print(
            f"[Metrics] success={success} | tokens_in={sub_metrics.get('input_tokens')} "
            f"| tokens_out={sub_metrics.get('output_tokens')} | cost=${task_cost:.4f} "
            f"| elapsed={elapsed_ms}ms"
        )

        ledger.log_task(
            TaskLog(
                cycle=cycle,
                task_id=task.id,
                persona=task.persona,
                success=success,
                expected_url=task.expected_url,
                predicted_url=final_url,
                prompt_id=prompt_id,
                scaffold_id=scaffold_id,
                subagent_tokens_in=sub_metrics.get("input_tokens"),
                subagent_tokens_out=sub_metrics.get("output_tokens"),
                subagent_cost=sub_metrics.get("cost"),
                critique_tokens_in=crit_metrics.get("input_tokens"),
                critique_tokens_out=crit_metrics.get("output_tokens"),
                critique_cost=crit_metrics.get("cost"),
                total_cost=task_cost,
                wall_time_ms=elapsed_ms,
                hops=2,
                critique_state=critique_state,
                critique_justification=critique_payload.get("justification"),
                raw_response=sub_raw,
                raw_critique=critique_raw,
            )
        )

    print(f"\nCycle {cycle} complete :: {successes}/{len(task_list)} successes | cost=${total_cost:.4f}")
    return {"successes": successes, "total_cost": total_cost, "tasks": len(task_list)}


def maybe_update_prompt(current_prompt: str, cycle_results: Dict[str, float]) -> str:
    success_rate = cycle_results["successes"] / max(1, cycle_results["tasks"])
    if success_rate >= 0.85:
        return current_prompt

    summary = (
        f"Cycle success rate was {success_rate:.2%}. "
        f"Total cost ${cycle_results['total_cost']:.4f}."
    )
    prompt = (
        "You are improving the main-agent prompt for future cycles.\n"
        "Existing prompt:\n"
        f"{current_prompt}\n\n"
        f"Performance summary: {summary}\n\n"
        "Suggest a revised prompt that is at most 200 words, keeping the JSON response format requirement. "
        "Respond with JSON: {\"prompt\": \"...\"}"
    )
    response = call_claude(prompt)
    try:
        payload = json.loads(response.text)
        new_prompt = payload.get("prompt")
        if new_prompt:
            timestamped = Path("agent_history/prompts")
            timestamped.mkdir(parents=True, exist_ok=True)
            timestamped = timestamped / f"main_agent_cycle_{int(time.time())}.md"
            timestamped.write_text(new_prompt, encoding="utf-8")
            print(f"[Prompt updated] Saved to {timestamped}")
            return new_prompt
    except json.JSONDecodeError:
        pass
    print("[Prompt update] No change applied.")
    return current_prompt


def main(cycles: int = 1) -> None:
    ledger.init_db()
    tasks = load_tasks()
    main_prompt = load_main_prompt()
    scaffolding = build_scaffolding()

    for cycle in range(1, cycles + 1):
        results = run_cycle(
            cycle=cycle,
            tasks=tasks,
            main_prompt=main_prompt,
            scaffolding=scaffolding,
        )
        main_prompt = maybe_update_prompt(main_prompt, results)
