You are reviewing a navigation assistant's work.

Task query: {query}
Persona: {persona}
Expected URL: {expected_url}

Assistant output:
{assistant_output}

Decide if the chosen URL resolves the task. Respond in JSON:
{{
  "state": "ok" | "retry" | "fail",
  "justification": "brief human-readable reason",
  "revised_url": "<updated url or null>"
}}

Use "retry" if the assistant should try once more with a short hint.
Use "fail" if the task cannot be solved with the provided context.
