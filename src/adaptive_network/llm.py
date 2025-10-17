from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import requests


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
    max_tokens: int = 800,
    system: Optional[str] = None,
) -> ClaudeResponse:
    base_url, token = _load_credentials()

    headers = {
        "Content-Type": "application/json",
        "x-api-key": token,
        "anthropic-version": "2023-06-01",
    }

    messages = []
    if system:
        messages.append({"role": "system", "content": [{"type": "text", "text": system}]})
    messages.append({"role": "user", "content": [{"type": "text", "text": prompt}]})

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }

    response = requests.post(
        f"{base_url}/v1/messages",
        headers=headers,
        json=payload,
        timeout=timeout,
    )

    if response.status_code >= 400:
        raise ClaudeError(f"Claude API error {response.status_code}: {response.text}")

    data = response.json()
    parts = data.get("content", [])
    text = "".join(part.get("text", "") for part in parts if part.get("type") == "text").strip()
    return ClaudeResponse(text=text, raw=data)
