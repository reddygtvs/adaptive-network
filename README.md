# Adaptive Network Self-Improver

## Repository layout
- `agent_loop.py` — entry point that runs one or more navigation cycles.
- `csuchico_graph.py` — full CSU Chico crawl (9,286 nodes).
- `csuchico_graph_refined.py` — deduplicated graph used at runtime.
- `data/missions.json` — curated missions with start/goal URLs.
- `src/adaptive_network/` — package with the runtime code:
  - `engine.py` (cycle runner & logging)
  - `agents.py` (Claude calls plus navigator/critique prompts)
  - `graph.py` (persona scaffolds and neighbor lookup)
  - `ledger.py` (SQLite helpers)
  - `missions.py` (mission loader)
- `scripts/` — utilities:
  - `run_benchmarks.py` (greedy/markov/random baselines)
  - `print_baseline_summary.py` (tables for the latest runs)
  - `manage_scaffolds.py` (regenerate persona scaffolds from the graph)

## Requirements
- Python ≥ 3.10
- `requests`, `networkx`, `pydantic`

```bash
python -m pip install --upgrade pip
python -m pip install requests networkx pydantic
```

## Install Claude Code CLI
```bash
python3 -m pip install --upgrade claude-code
```

## Configure Claude Code for Z.AI (glm-4.6)
```bash
# 0) kill any running Claude Code
pkill -f '^claude($| )' 2>/dev/null || true

# 1) Force onboarding complete so the setup wizard stays hidden
ts=$(date +%s)
[ -f ~/.claude.json ] && cp ~/.claude.json ~/.claude.json.bak.$ts
printf '{
  "hasCompletedOnboarding": true
}
' > ~/.claude.json

# 2) Drop your Z.AI endpoint + key into Claude Code settings
mkdir -p ~/.claude
cat > ~/.claude/settings.json <<'JSON'
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "PASTE_YOUR_GLM_API_KEY",
    "ANTHROPIC_MODEL": "glm-4.6",
    "ANTHROPIC_SMALL_FAST_MODEL": "glm-4.5-air"
  }
}
JSON

# 3) Clear any old Anthropic API key to avoid clashes
unset ANTHROPIC_API_KEY

# 4) Launch the CLI
claude
```

Once configured, the CLI serves the same glm-4.6 endpoint that the repo calls.

## Run a navigation cycle
```bash
python agent_loop.py
```

### What a cycle does
- Loads persona scaffolds from the refined graph (start page only; everything else must be fetched through expansions).
- Runs mission batches through the planner → navigator → critique pipeline (`src/adaptive_network/engine.py`).
- Logs every turn plus token/cost usage to SQLite (`agent_history/ledger.db`) via `ledger.py`.
- Asks the supervising controller for a follow-up action; scaffold & config updates auto-apply, prompt rewrites stay manual.

### Output reference
- CLI prints per-mission success flags, token totals, elapsed time, and USD cost (input $0.60/M, cached $0.11/M, output $2.20/M for `glm-4.6`).
- SQLite keeps raw navigator turns, critique payloads, per-cycle summaries, controller suggestions, and applied scaffold diffs.
- Benchmarks live in `benchmark_results.json` + `benchmark_series/` and stay out of git; regenerate with `scripts/run_benchmarks.py`.

## Mission tweaks
- Edit `data/missions.json` to add/remove missions (persona, start URL, target URL, label, question).
- Extend or swap persona scaffolds in `src/adaptive_network/graph.py` (mirrors CSU Chico; drop in alternate graphs if you prefer).
- Tweak navigator/critique/controller prompts inside `src/adaptive_network/agents.py`; planner brief + controller JSON schema live there.
- Controller suggestions persist in SQLite (`revisions` table); inspect them if you want to apply prompt updates by hand.
- `--cycles N` — number of cycles to run (default 1).
- `--missions PATH` — alternate missions file (default `data/missions.json`).
- `--db-path PATH` — SQLite ledger location; new path starts at cycle 1.
- `--batch-size N` — missions per batch (default 10).
- `--stagger SECONDS` — delay between mission launches within a batch (default 0.35).
- `--auto` — apply controller suggestions without prompting.
- `--limit N` — process only N missions per cycle (wraps across cycles).

Benchmarks & scaffolds:
- `python scripts/run_benchmarks.py [--mission-limit N --budget M --markov-skip K --output FILE]`
- `python scripts/print_baseline_summary.py`
- `python scripts/manage_scaffolds.py regen --persona {all|name} [--limit N --db-path PATH]`
