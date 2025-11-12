from __future__ import annotations

import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from . import ledger
from .agents import critique_answer, plan_brief, run_controller, run_navigation
from .graph import PERSONA_PREFIXES, page_label, persona_scaffold
from .missions import Mission, load_missions

INPUT_RATE = 0.6 / 1_000_000
CACHED_INPUT_RATE = 0.11 / 1_000_000
OUTPUT_RATE = 2.2 / 1_000_000

MAIN_PROMPT = """You are the coordinating agent for navigation missions on csuchico.edu.

Respond strictly in JSON:
{
  "brief": "one or two sentences telling the navigator how to proceed (<=40 words)",
  "notes": "optional extra context for logging (<=40 words)"
}

Guidelines:
- Do not guess the final URL or mention a specific target page.
- Suggest which site sections, breadcrumbs, or keywords the navigator should explore.
- Encourage collecting more context when information is missing.
- Keep language concise and actionable."""


@dataclass
class RunnerConfig:
    batch_size: int = 10
    stagger_seconds: float = 0.35
    parallel: bool = True
    auto_apply: bool = False
    mission_limit: int | None = None


DEFAULT_AGENT_CONFIG: Dict[str, Any] = {
    "base_max_expansions": 6,
    "hardness_offset": 2,
    "neighbor_limit": 8,
}


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
    action: str
    confidence: float | None
    brief: Dict[str, Any] | None

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
    config: Dict[str, Any],
    prompt_body: str,
) -> MissionOutcome:
    time.sleep(max(delay, 0))
    initial_pages = _build_initial_pages(mission, persona_bases)
    start_label = page_label(mission.start_url)

    brief_payload = plan_brief(
        system_prompt=prompt_body,
        persona=mission.persona,
        question=mission.question,
        start_label=start_label,
        start_url=mission.start_url,
    )
    brief_text = ""
    if isinstance(brief_payload, dict):
        brief_text = str(brief_payload.get("brief", "")).strip()
    augmented_question = mission.question
    if brief_text:
        augmented_question = f"{mission.question}\n\nCoordinator brief: {brief_text}"

    base_expansions = int(config.get("base_max_expansions", 6))
    hardness_offset = int(config.get("hardness_offset", 2))
    neighbor_limit = int(config.get("neighbor_limit", 8))
    max_expansions = max(base_expansions, mission.shortest_hops + hardness_offset)

    t_start = time.time()
    payload, call_log, _known = run_navigation(
        persona=mission.persona,
        question=augmented_question,
        start_url=mission.start_url,
        initial_pages=initial_pages,
        max_expansions=max_expansions,
        neighbor_limit=neighbor_limit,
    )
    elapsed_ms = int((time.time() - t_start) * 1000)

    raw_records = [entry["raw"] for entry in call_log]
    usage = _aggregate_usage(raw_records)

    chosen_url = payload.get("chosen_url")
    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw is not None else None
    except (TypeError, ValueError):
        confidence = None
    action = str(payload.get("action") or "answer")

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
        raw_response={"brief": brief_payload, "steps": call_log},
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
        action=action,
        confidence=confidence,
        brief=brief_payload if isinstance(brief_payload, dict) else None,
    )


def run_cycle(
    *,
    cycle: int,
    missions: Iterable[Mission],
    persona_bases: Dict[str, List[Dict[str, str]]],
    prompt_id: int,
    scaffold_id: int,
    config: Dict[str, Any],
    runner: RunnerConfig,
    db_path: Path | str,
    prompt_body: str,
) -> Dict[str, Any]:
    mission_list = list(missions)
    outcomes: List[MissionOutcome] = []
    successes = 0
    total_cost = 0.0

    total_missions = len(mission_list)
    batch_size = max(1, runner.batch_size)
    total_batches = (total_missions + batch_size - 1) // batch_size
    print(
        f"Cycle {cycle} | missions {total_missions} | batch size {batch_size} | "
        f"parallel={'on' if runner.parallel else 'off'}"
    )

    completed = 0

    for batch_index, batch_start in enumerate(range(0, total_missions, batch_size), start=1):
        batch = mission_list[batch_start : batch_start + batch_size]
        print(f"Cycle {cycle} | batch {batch_index}/{total_batches} started")

        if runner.parallel:
            with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                future_map = {
                    executor.submit(
                        _mission_worker,
                        cycle=cycle,
                        order=batch_start + offset,
                        mission=mission,
                        persona_bases=persona_bases,
                        prompt_id=prompt_id,
                        scaffold_id=scaffold_id,
                        delay=offset * runner.stagger_seconds,
                        config=config,
                        prompt_body=prompt_body,
                    ): (batch_start + offset)
                    for offset, mission in enumerate(batch)
                }

                for future in as_completed(future_map):
                    outcome = future.result()
                    completed += 1
                    outcomes.append(outcome)
                    ledger.log_task(outcome.log_entry, path=db_path)
                    if outcome.success:
                        successes += 1
                    total_cost += outcome.total_cost
                    status = "success" if outcome.success else "fail"
                    print(
                        f"Cycle {cycle} | {completed}/{total_missions} | persona={outcome.mission.persona} | "
                        f"{status} | cost=${outcome.total_cost:.4f} | {outcome.elapsed_ms/1000:.1f}s"
                    )
        else:
            for offset, mission in enumerate(batch):
                outcome = _mission_worker(
                    cycle=cycle,
                    order=batch_start + offset,
                    mission=mission,
                    persona_bases=persona_bases,
                    prompt_id=prompt_id,
                    scaffold_id=scaffold_id,
                    delay=0.0,
                    config=config,
                    prompt_body=prompt_body,
                )
                completed += 1
                outcomes.append(outcome)
                ledger.log_task(outcome.log_entry, path=db_path)
                if outcome.success:
                    successes += 1
                total_cost += outcome.total_cost
                status = "success" if outcome.success else "fail"
                print(
                    f"Cycle {cycle} | {completed}/{total_missions} | persona={outcome.mission.persona} | "
                    f"{status} | cost=${outcome.total_cost:.4f} | {outcome.elapsed_ms/1000:.1f}s"
                )

    print(f"Cycle {cycle} complete :: {successes}/{total_missions} successes | cost=${total_cost:.4f}")
    return {
        "successes": successes,
        "total_cost": total_cost,
        "tasks": total_missions,
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


def _select_missions(missions: List[Mission], limit: int | None, cycle_number: int) -> List[Mission]:
    if not limit or limit <= 0 or limit >= len(missions):
        return list(missions)
    total = len(missions)
    limit = max(1, min(limit, total))
    start = ((cycle_number - 1) * limit) % total
    end = start + limit
    if end <= total:
        return missions[start:end]
    wrap = end - total
    return missions[start:] + missions[:wrap]


def _default_scaffold_dict() -> Dict[str, Any]:
    data: Dict[str, Any] = {persona: persona_scaffold(persona, limit=30) for persona in PERSONA_PREFIXES}
    data["__config__"] = DEFAULT_AGENT_CONFIG
    return data


def _build_scaffold_body(scaffold: Dict[str, List[Dict[str, str]]], config: Dict[str, Any]) -> str:
    payload: Dict[str, Any] = {persona: pages for persona, pages in scaffold.items()}
    payload["__config__"] = config
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _load_assets(db_path: Path | str) -> tuple[int, str, Dict[str, List[Dict[str, str]]], int, Dict[str, Any]]:
    default_scaffold_body = json.dumps(_default_scaffold_dict(), ensure_ascii=False, indent=2)
    scaffold_id, scaffold_body = ledger.load_latest_scaffold(default_scaffold_body, path=db_path)
    scaffold_payload = json.loads(scaffold_body)

    stored_config = scaffold_payload.pop("__config__", {})
    config = dict(DEFAULT_AGENT_CONFIG)
    if isinstance(stored_config, dict):
        config.update(stored_config)

    persona_bases: Dict[str, List[Dict[str, str]]] = {}
    for persona in PERSONA_PREFIXES:
        entries = scaffold_payload.get(persona)
        if isinstance(entries, list) and entries:
            persona_bases[persona] = entries
        else:
            persona_bases[persona] = persona_scaffold(persona, limit=30)

    prompt_id, prompt_body = ledger.load_latest_prompt(MAIN_PROMPT, path=db_path)
    return prompt_id, prompt_body, persona_bases, scaffold_id, config


def _apply_scaffold_diff(scaffold: Dict[str, List[Dict[str, str]]], diff: Dict[str, Any]) -> None:
    if not diff:
        return
    personas: Iterable[str]
    persona = diff.get("persona")
    if persona in (None, "all"):
        personas = list(scaffold.keys())
    else:
        personas = [persona]
        scaffold.setdefault(persona, [])

    remove_urls = {_normalize(url) for url in diff.get("remove", []) if isinstance(url, str)}
    additions = [
        {"url": item.get("url"), "label": item.get("label") or item.get("url")}
        for item in diff.get("add", [])
        if isinstance(item, dict) and item.get("url")
    ]

    for persona_key in personas:
        pages = scaffold.setdefault(persona_key, [])
        if remove_urls:
            pages = [item for item in pages if _normalize(item.get("url")) not in remove_urls]
        existing = {_normalize(item.get("url")) for item in pages}
        for item in additions:
            url = item["url"]
            norm = _normalize(url)
            if norm in existing:
                continue
            pages.append({"url": url, "label": item["label"]})
            existing.add(norm)
        scaffold[persona_key] = pages


def _apply_controller_suggestion(
    *,
    payload: Dict[str, Any],
    revision_id: int,
    prompt_body: str,
    prompt_id: int,
    persona_bases: Dict[str, List[Dict[str, str]]],
    scaffold_id: int,
    config: Dict[str, Any],
    db_path: Path | str,
) -> tuple[str, int, Dict[str, List[Dict[str, str]]], int, Dict[str, Any], bool]:
    action = payload.get("action")
    updated = False
    new_payload = dict(payload)
    new_prompt_id = prompt_id
    new_scaffold_id = scaffold_id
    new_prompt_body = prompt_body
    new_config = dict(config)
    scaffold_changed = False

    if action == "update_prompt":
        updated_prompt = (payload.get("updated_asset") or "").strip()
        if not updated_prompt:
            ledger.update_revision_status(
                revision_id=revision_id,
                status="skipped_prompt_missing",
                path=db_path,
            )
            return prompt_body, prompt_id, persona_bases, scaffold_id, config, False
        new_prompt_body = updated_prompt
        new_prompt_id = ledger.save_prompt(new_prompt_body, path=db_path)
        new_payload["applied_prompt"] = True
        updated = True

    if action == "update_scaffold":
        diff = payload.get("scaffold_diff") or {}
        _apply_scaffold_diff(persona_bases, diff)
        new_payload["applied_diff"] = diff
        scaffold_changed = True
        updated = True

    if action == "update_subagent":
        updates = payload.get("config_updates") or {}
        for key, value in updates.items():
            if isinstance(value, (int, float)):
                new_config[key] = value
            elif isinstance(value, str) and value.strip().isdigit():
                new_config[key] = int(value.strip())
        new_payload["applied_config"] = updates
        scaffold_changed = True
        updated = True

    if not updated:
        return prompt_body, prompt_id, persona_bases, scaffold_id, config, False

    if scaffold_changed:
        scaffold_body = _build_scaffold_body(persona_bases, new_config)
        new_scaffold_id = ledger.save_scaffold(scaffold_body, path=db_path)

    new_payload["prompt_id"] = new_prompt_id
    new_payload["scaffold_id"] = new_scaffold_id

    ledger.update_revision_status(
        revision_id=revision_id,
        status="applied",
        payload=new_payload,
        prompt_id=new_prompt_id,
        scaffold_id=new_scaffold_id,
        path=db_path,
    )
    return new_prompt_body, new_prompt_id, persona_bases, new_scaffold_id, new_config, True


def _print_controller_thoughts(payload: Dict[str, Any]) -> None:
    print("\nController thought process:")
    issues = payload.get("issues")
    if isinstance(issues, list) and issues:
        print("  Issues:", "; ".join(str(item) for item in issues))
    else:
        print("  Issues: (not specified)")

    print(
        "  Prompt:",
        "proposal received" if payload.get("updated_asset") else "no change proposed",
    )
    config_updates = payload.get("config_updates")
    if isinstance(config_updates, dict) and config_updates:
        print(f"  Sub-agent config: {config_updates}")
    else:
        print("  Sub-agent config: no change proposed")
    scaffold_diff = payload.get("scaffold_diff")
    if isinstance(scaffold_diff, dict) and scaffold_diff:
        persona = scaffold_diff.get("persona", "unspecified")
        adds = scaffold_diff.get("add")
        removes = scaffold_diff.get("remove")
        print(f"  Scaffold ({persona}): add={adds or []} remove={removes or []}")
    else:
        print("  Scaffold: no change proposed")
    suggestion = payload.get("suggestion")
    if suggestion:
        print("  Suggestion:", suggestion)


def main(
    *,
    cycles: int = 1,
    missions_path: Path | str = Path("data/missions.json"),
    db_path: Path | str = ledger.DEFAULT_DB_PATH,
    runner: RunnerConfig | None = None,
) -> None:
    db_path = Path(db_path)
    ledger.init_db(db_path)
    missions = load_missions(missions_path)
    ledger.register_missions(missions, path=db_path)

    runner = runner or RunnerConfig()

    prompt_id, prompt_body, persona_bases, scaffold_id, config = _load_assets(db_path)
    start_cycle = ledger.latest_cycle_number(db_path) + 1

    for offset in range(cycles):
        cycle_number = start_cycle + offset
        cycle_missions = _select_missions(missions, runner.mission_limit, cycle_number)

        results = run_cycle(
            cycle=cycle_number,
            missions=cycle_missions,
            persona_bases=persona_bases,
            prompt_id=prompt_id,
            scaffold_id=scaffold_id,
            config=config,
            runner=runner,
            db_path=db_path,
            prompt_body=prompt_body,
        )
        outcomes: List[MissionOutcome] = results.get("outcomes", [])
        summary = _summarize_outcomes(cycle_number, outcomes)

        successes = results.get("successes", 0)
        tasks = results.get("tasks", len(outcomes))
        failures = tasks - successes
        total_cost = float(results.get("total_cost", 0.0))

        ledger.record_cycle_metrics(
            cycle=cycle_number,
            successes=successes,
            failures=failures,
            total_cost=total_cost,
            payload=summary,
            path=db_path,
        )

        controller_payload, controller_raw = run_controller(
            summary=summary,
            controller_prompt=prompt_body,
            scaffolding=persona_bases,
            config=config,
        )
        action = str(controller_payload.get("action", "no_change"))
        suggestion = controller_payload.get("suggestion")
        rationale = controller_payload.get("rationale")
        revision_id = ledger.log_revision(
            cycle=cycle_number,
            target=action,
            suggestion=suggestion if isinstance(suggestion, str) else None,
            rationale=rationale if isinstance(rationale, str) else None,
            payload=controller_payload if isinstance(controller_payload, dict) else {"raw": controller_payload},
            prompt_id=prompt_id,
            scaffold_id=scaffold_id,
            raw_response=controller_raw,
            path=db_path,
        )

        confidence = controller_payload.get("confidence")
        print(f"Controller action: {action} | confidence={confidence}")
        _print_controller_thoughts(controller_payload if isinstance(controller_payload, dict) else {})

        actionable = action in {"update_prompt", "update_scaffold", "update_subagent"}
        if not actionable:
            ledger.update_revision_status(
                revision_id=revision_id,
                status="skipped",
                path=db_path,
            )
            continue

        apply_change = runner.auto_apply
        if not runner.auto_apply:
            answer = input("Apply controller suggestion now? [y/N]: ").strip().lower()
            apply_change = answer.startswith("y")

        if apply_change:
            prompt_body, prompt_id, persona_bases, scaffold_id, config, applied = _apply_controller_suggestion(
                payload=controller_payload,
                revision_id=revision_id,
                prompt_body=prompt_body,
                prompt_id=prompt_id,
                persona_bases=persona_bases,
                scaffold_id=scaffold_id,
                config=config,
                db_path=db_path,
            )
            if applied:
                print("Controller suggestion applied.")
            else:
                print("Controller suggestion could not be applied; left pending.")
        else:
            print("Controller suggestion left pending.")
            ledger.update_revision_status(
                revision_id=revision_id,
                status="pending",
                path=db_path,
            )

        if not runner.auto_apply and cycles > 1 and offset < cycles - 1:
            print("Continuing to next cycle...\n")
        print(f"Cycle {cycle_number} recorded.")


__all__ = ["main", "run_cycle"]
