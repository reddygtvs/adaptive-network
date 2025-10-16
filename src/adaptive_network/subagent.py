from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from .llm import call_claude


def _read_prompt(resource_name: str, override: Path | None = None) -> str:
    if override is not None:
        return override.read_text(encoding="utf-8")
    resource = resources.files("adaptive_network.prompts").joinpath(resource_name)
    return resource.read_text(encoding="utf-8")


def _strip_fence(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines and lines[0].lower().startswith("json"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


def _format_context(context: Iterable[Dict[str, str]]) -> str:
    return "\n".join(
        f"{idx}. {item['label']} — {item['url']}"
        for idx, item in enumerate(context, start=1)
    )


def run_subagent(
    *,
    persona: str,
    query: str,
    expected_url: str,
    context: List[Dict[str, str]],
    subagent_prompt_path: Path | None = None,
    critique_prompt_path: Path | None = None,
) -> Tuple[Dict[str, object], Dict[str, object], Dict[str, object], Dict[str, object]]:
    subagent_prompt_template = _read_prompt("subagent.md", subagent_prompt_path)
    subagent_prompt = subagent_prompt_template.format(
        query=query,
        persona=persona,
        context_table=_format_context(context),
    )
    subagent_response = call_claude(subagent_prompt)

    try:
        payload = json.loads(_strip_fence(subagent_response.text))
    except json.JSONDecodeError:
        payload = {
            "chosen_url": None,
            "confidence": 0,
            "reasoning": subagent_response.text,
            "answer": subagent_response.text,
        }

    critique_prompt_template = _read_prompt("critique.md", critique_prompt_path)
    critique_prompt = critique_prompt_template.format(
        query=query,
        persona=persona,
        expected_url=expected_url,
        assistant_output=json.dumps(payload, ensure_ascii=False),
    )

    critique_response = call_claude(critique_prompt)

    try:
        critique_payload = json.loads(_strip_fence(critique_response.text))
    except json.JSONDecodeError:
        critique_payload = {
            "state": "fail",
            "justification": critique_response.text,
            "revised_url": None,
        }

    return payload, subagent_response.raw, critique_payload, critique_response.raw
