from __future__ import annotations

import json
import os
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import time

import requests

from .graph import neighbors, page_label

NAVIGATOR_PROMPT = """You are a navigation assistant for csuchico.edu.

Mission: {question}
Persona: {persona}
Start from: {start_label} ({start_url})

Known pages:
{context_table}

Guidelines:
1. To inspect outgoing links from a listed page, reply with
   {{"action": "expand", "target_url": "<url from table>", "reasoning": "why"}}
2. When you are confident about the destination, reply with
   {{"action": "answer", "chosen_url": "<url from table>", "confidence": 0-1, "reasoning": "why"}}
3. Only reference URLs already in the table. Always answer in JSON.
{feedback}
"""

CRITIQUE_PROMPT = """You are reviewing a navigation attempt for csuchico.edu.

Task query: {query}
Persona: {persona}
Expected URL: {expected_url}

Assistant output:
{assistant_output}

Respond in JSON:
{{
  "state": "ok" | "retry" | "fail",
  "justification": "brief reason",
  "revised_url": "<url or null>"
}}

Return "ok" if the chosen URL matches the expectation, "retry" if the assistant should try again with a short hint, or "fail" if the chosen URL is wrong and a retry would not help.
"""

CONTROLLER_PROMPT = """You are the supervising agent for a self-improving website navigator.

Inputs you receive each cycle:
- The current controller prompt (what you would change if needed).
- The persona scaffolds (what context is available to the navigator).
- The subagent configuration settings.
- A summary of the latest cycle (success/failure counts, per-persona stats, notable failures).

Your job:
1. Inspect the summary for failure patterns, cost spikes, or regressions.
2. Decide which lever to adjust next:
   - "update_prompt" (rewrite the main controller prompt)
   - "update_scaffold" (adjust persona scaffolding: add/remove URLs, reorder priorities)
   - "update_subagent" (tweak execution parameters such as max expansions, neighbor limit)
   - "no_change" (keep current setup when metrics look stable)
3. Provide a concise plan plus any data needed for implementation.

Respond **only** in JSON with this format:
{
  "action": "...",
  "issues": ["short bullet list of key observations"],
  "suggestion": "concise recommendation (<=120 words)",
  "rationale": "why this change should help",
  "confidence": 0.0-1.0,
  "follow_up": ["optional questions or data requests"],
  "updated_asset": "full prompt text to use next"           # required when action == "update_prompt"
  "scaffold_diff": {                                       # required when action == "update_scaffold"
      "persona": "<persona or 'all'>",
      "add": [{"url": "...", "label": "..."}],
      "remove": ["<url>", "..."]
  },
  "config_updates": {                                      # required when action == "update_subagent"
      "base_max_expansions": 6,
      "neighbor_limit": 8,
      "hardness_offset": 2
  }
}

Leave unused fields out or set them to null. Stay focused on concrete next steps; avoid generic advice.
"""


class ClaudeError(RuntimeError):
    """Raised when Claude API calls fail."""


@dataclass
class ClaudeResponse:
    text: str
    raw: Dict


def _load_credentials() -> tuple[str, str]:
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    token = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")

    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            env = settings.get("env", {})
            base_url = base_url or env.get("ANTHROPIC_BASE_URL")
            token = token or env.get("ANTHROPIC_AUTH_TOKEN")
        except json.JSONDecodeError:
            pass

    if not base_url:
        base_url = "https://api.anthropic.com"
    if not token:
        raise ClaudeError("Anthropic API token not configured. Set ANTHROPIC_AUTH_TOKEN or update ~/.claude/settings.json")
    return base_url.rstrip("/"), token


def call_claude(
    prompt: str,
    *,
    model: str = "glm-4.6",
    timeout: int = 120,
    max_tokens: int = 600,
    system: Optional[str] = None,
    retries: int = 3,
    retry_backoff: float = 1.5,
) -> ClaudeResponse:
    base_url, token = _load_credentials()

    headers = {
        "Content-Type": "application/json",
        "x-api-key": token,
        "anthropic-version": "2023-06-01",
    }

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
    }
    if system:
        payload["system"] = system

    last_error: Optional[str] = None
    for attempt in range(max(1, retries)):
        try:
            response = requests.post(
                f"{base_url}/v1/messages",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt == retries - 1:
                raise ClaudeError(f"Claude API request failed: {exc}") from exc
            time.sleep(retry_backoff * (attempt + 1))
            continue

        if response.status_code >= 500:
            last_error = response.text
            if attempt == retries - 1:
                raise ClaudeError(f"Claude API error {response.status_code}: {response.text}")
            time.sleep(retry_backoff * (attempt + 1))
            continue

        if response.status_code >= 400:
            raise ClaudeError(f"Claude API error {response.status_code}: {response.text}")

        break
    else:
        raise ClaudeError(f"Claude API error: {last_error or 'unknown failure'}")

    data = response.json()
    text = "".join(
        part.get("text", "")
        for part in data.get("content", [])
        if part.get("type") == "text"
    ).strip()
    return ClaudeResponse(text=text, raw=data)


def _format_context(pages: Iterable[Dict[str, str]]) -> str:
    return "\n".join(
        f"{idx}. {item['label']} — {item['url']}"
        for idx, item in enumerate(pages, start=1)
    )


def _parse_json_blob(text: str) -> Dict[str, object]:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[0].lower().startswith("json"):
            lines = lines[1:]
        if lines and lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"action": "fail", "reasoning": raw}


def _canon(url: str | None) -> str:
    if not url:
        return ""
    return url.rstrip("/").lower()


def plan_brief(
    *,
    system_prompt: str,
    persona: str,
    question: str,
    start_label: str,
    start_url: str,
) -> Dict[str, object]:
    prompt = (
        f"Persona: {persona}\n"
        f"Mission: {question}\n"
        f"Start page label: {start_label}\n"
        f"Start page URL: {start_url}\n"
        "Return JSON with keys 'brief' and 'notes'."
    )
    response = call_claude(prompt, max_tokens=160, system=system_prompt)
    payload = _parse_json_blob(response.text)
    if "brief" not in payload:
        payload["brief"] = payload.get("task_brief") or ""
    if "notes" not in payload:
        payload["notes"] = payload.get("notes") or ""
    return {"brief": str(payload.get("brief", "")).strip(), "notes": str(payload.get("notes", "")).strip()}


def run_navigation(
    *,
    persona: str,
    question: str,
    start_url: str,
    initial_pages: Iterable[Dict[str, str]],
    max_expansions: int = 5,
    neighbor_limit: int = 8,
) -> Tuple[Dict[str, object], List[Dict[str, object]], List[Dict[str, str]]]:
    known = OrderedDict()
    seen = set()

    def add_page(page: Dict[str, str]) -> bool:
        key = _canon(page.get("url"))
        if not key or key in seen:
            return False
        seen.add(key)
        known[key] = {"url": page["url"], "label": page.get("label") or page["url"]}
        return True

    start_label = page_label(start_url)
    add_page({"url": start_url, "label": start_label})
    for page in initial_pages:
        if _canon(page.get("url")) == _canon(start_url):
            continue
        add_page(page)

    feedback = ""
    call_log: List[Dict[str, object]] = []
    expansions = 0

    while expansions <= max_expansions:
        context_table = _format_context(known.values())
        prompt = NAVIGATOR_PROMPT.format(
            question=question,
            persona=persona,
            start_label=start_label,
            start_url=start_url,
            context_table=context_table or "(no known pages yet)",
            feedback=("\n4. " + feedback) if feedback else "",
        )
        response = call_claude(prompt)
        payload = _parse_json_blob(response.text)
        action = str(payload.get("action", "")).lower()
        call_log.append(
            {
                "prompt": prompt,
                "raw": response.raw,
                "payload": payload,
                "known_pages": list(known.values()),
            }
        )

        if action == "expand":
            target_url = payload.get("target_url")
            key = _canon(target_url if isinstance(target_url, str) else "")
            if not key or key not in known:
                feedback = (
                    "Expansion request was invalid. Choose a URL from the table when asking to expand."
                )
                expansions += 1
                continue

            new_pages = neighbors(known[key]["url"], limit=neighbor_limit)
            added = sum(1 for page in new_pages if add_page(page))
            if added:
                feedback = f"Added {added} pages discovered from {known[key]['label']}."
            else:
                feedback = f"No new pages found when expanding {known[key]['label']}."
            expansions += 1
            continue

        if action == "answer":
            if "chosen_url" not in payload and isinstance(payload.get("target_url"), str):
                payload["chosen_url"] = payload["target_url"]
            return payload, call_log, list(known.values())

        if payload.get("chosen_url"):
            payload.setdefault("action", "answer")
            return payload, call_log, list(known.values())

        feedback = "Reply using the JSON actions shown above."
        expansions += 1

    fallback = {
        "action": "answer",
        "chosen_url": None,
        "confidence": 0,
        "reasoning": "Reached navigation limit without a confident answer.",
    }
    return fallback, call_log, list(known.values())


def critique_answer(
    *,
    persona: str,
    question: str,
    expected_url: str,
    assistant_output: Dict[str, object],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    prompt = CRITIQUE_PROMPT.format(
        query=question,
        persona=persona,
        expected_url=expected_url,
        assistant_output=json.dumps(assistant_output, ensure_ascii=False),
    )
    response = call_claude(prompt)
    payload = _parse_json_blob(response.text)
    return payload, response.raw


def run_controller(
    *,
    summary: Dict[str, object],
    controller_prompt: str,
    scaffolding: Dict[str, List[Dict[str, str]]],
    config: Dict[str, object],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    body = (
        f"{CONTROLLER_PROMPT}\n\n"
        f"Current controller prompt:\n{controller_prompt.strip()}\n\n"
        "Persona scaffolds:\n"
        f"{json.dumps(scaffolding, ensure_ascii=False, indent=2)}\n\n"
        "Subagent configuration:\n"
        f"{json.dumps(config, ensure_ascii=False, indent=2)}\n\n"
        "Latest cycle summary:\n"
        f"{json.dumps(summary, ensure_ascii=False, indent=2)}\n"
    )
    response = call_claude(body, max_tokens=600)
    payload = _parse_json_blob(response.text)
    return payload, response.raw


__all__ = [
    "ClaudeError",
    "ClaudeResponse",
    "call_claude",
    "plan_brief",
    "run_navigation",
    "critique_answer",
    "run_controller",
]
