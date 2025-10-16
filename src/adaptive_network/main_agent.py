from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Iterable, Mapping

from .llm import call_claude


def _read_prompt_text(default_package: str, resource_name: str, override: Path | None) -> str:
    if override is not None:
        return override.read_text(encoding="utf-8")
    resource = resources.files(default_package).joinpath(resource_name)
    return resource.read_text(encoding="utf-8")


def load_main_prompt(path: Path | None = None) -> str:
    return _read_prompt_text("adaptive_network.prompts", "main_agent.md", path)


def plan_task(
    persona: str,
    query: str,
    context: Iterable[Mapping[str, str]],
    *,
    system_prompt: str | None = None,
) -> dict[str, str]:
    prompt_body = system_prompt if system_prompt is not None else load_main_prompt()
    context_lines = "\n".join(f"- {item['label']} ({item['url']})" for item in context)

    prompt = f"""{prompt_body}

Persona: {persona}
Task query: {query}

Context pages:
{context_lines}
"""
    response = call_claude(prompt)
    raw_text = response.text.strip()
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines and lines[0].lower().startswith("json"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw_text = "\n".join(lines).strip()

    payload = json.loads(raw_text)
    if "task_brief" not in payload:
        raise ValueError(f"Main agent response missing 'task_brief': {payload}")
    return payload
