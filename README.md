# Adaptive Network Self‑Improver

## What you get
- `agent_loop.py` runs the Claude-driven navigation loop on the packaged Chico State graph, logging per-task tokens, costs, and outcomes.
- `csuchico_graph_pruned.py` supplies a 9,286-node, nav-pruned site map used to build persona-specific scaffolding.
- `src/adaptive_network/` contains the agent package (prompt planner, subagent/critique runner, task loader, ledger helper).
- `persona_sampler.py` can generate weighted random walks over the graph for exploration or testing.

## Requirements
- Python ≥ 3.10
- Packages: `requests`, `networkx`

Install dependencies:
```bash
python -m pip install --upgrade pip
python -m pip install requests networkx
```

## Configure API access
Set your Z.AI (or compatible Anthropic) endpoint and key so the agent can call `glm-4.6`:
```bash
export ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic
export ANTHROPIC_AUTH_TOKEN=YOUR_API_KEY
```

Alternatively, replicate the Claude Code CLI setup by placing the same values in `~/.claude/settings.json`:
```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "YOUR_API_KEY",
    "ANTHROPIC_MODEL": "glm-4.6",
    "ANTHROPIC_SMALL_FAST_MODEL": "glm-4.5-air"
  }
}
```

## Run the loop
```bash
python agent_loop.py
```

The script automatically:
1. Loads persona-specific scaffolding from the pruned graph.
2. Runs each task (see `src/adaptive_network/task_data/tasks.json`) through the main agent, subagent, and critique.
3. Logs metrics to `agent_history/ledger.db` (created on first run) along with per-cycle prompt/scaffold snapshots.

## Outputs to know
- Console output lists per-task tokens, computed USD cost (based on \$0.60/M input, \$0.11/M cached input, \$2.20/M output for `glm-4.6`), success flags, and elapsed time.
- `agent_history/ledger.db` stores full results, while raw Claude responses are preserved in JSON columns for later inspection.

## Optional utilities
- `persona_sampler.py` demonstrates persona-weighted random walks over the pruned graph. It’s standalone; run `python persona_sampler.py` to print sample trajectories.

## Customizing tasks or prompts
- Edit `src/adaptive_network/task_data/tasks.json` to add or modify navigation tasks.
- Prompt templates live in `src/adaptive_network/prompts/`. Adjust `main_agent.md`, `subagent.md`, or `critique.md` as needed; they’re packaged and loaded via `importlib.resources`.
