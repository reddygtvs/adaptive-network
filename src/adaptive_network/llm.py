from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


class ClaudeError(RuntimeError):
    """Raised when Claude CLI commands fail."""


@dataclass
class ClaudeResponse:
    text: str
    raw: dict


def call_claude(
    prompt: str,
    *,
    model: str = "glm-4.6",
    timeout: int = 120,
) -> ClaudeResponse:
    result = subprocess.run(
        ["claude", "--print", "--output-format=json", "--model", model],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )

    if result.returncode != 0:
        raise ClaudeError(
            f"Claude CLI exited with {result.returncode}: "
            f"{result.stderr.decode('utf-8', errors='ignore')}"
        )

    stdout = result.stdout.decode("utf-8")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeError(f"Failed to parse Claude output: {stdout}") from exc

    if payload.get("subtype") != "success":
        raise ClaudeError(f"Claude reported failure: {payload}")

    return ClaudeResponse(text=payload.get("result", "").strip(), raw=payload)
