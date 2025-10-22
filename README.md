# Adaptive Network Self-Improver

## What’s in the box
- `agent_loop.py` – thin CLI entry point that runs one or more navigation cycles.
- `csuchico_graph.py` – full CSU Chico crawl (9,286 nodes).
- `csuchico_graph_refined.py` – deduplicated, breadcrumb-free graph used at runtime.
- `data/missions.json` – curated human-style missions with start/goal URLs.
- `src/adaptive_network/` – minimal package:
  - `engine.py` (cycle runner & logging)
  - `agents.py` (Claude calls + navigator/critique prompts)
  - `graph.py` (persona scaffolds + neighbor lookups)
  - `ledger.py` (SQLite helpers)
  - `missions.py` (JSON loader)

## Requirements
- Python ≥ 3.10
- `requests`, `networkx`

```bash
python -m pip install --upgrade pip
python -m pip install requests networkx
```

## Configure Claude access
Set your endpoint and token (Z.AI shown here, but any Anthropic-compatible endpoint works):

```bash
export ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic
export ANTHROPIC_AUTH_TOKEN=YOUR_API_KEY
```

You can also mirror the Claude Code CLI config by writing the same values to `~/.claude/settings.json`.

## Run it
```bash
python agent_loop.py          # defaults to one full cycle (all missions once)
```

Each cycle:
1. Loads persona scaffolds from the refined graph (start page only; everything else must be “expanded” by the navigator).
2. Hands every mission to the navigator, which incrementally requests neighbors before submitting a final URL.
3. Validates the answer with a critique call and records metrics in `agent_history/ledger.db`.

## What you’ll see
- Console: per-mission success flag, token totals, USD cost (input \$0.60/M, cached \$0.11/M, output \$2.20/M for `glm-4.6`), elapsed time.
- SQLite: `agent_history/ledger.db` retains missions, cycle history, raw Claude responses, and persona scaffolds so you can diff improvements across runs.

## Customizing missions
- Edit `data/missions.json` to add, remove, or tweak human-readable missions. Each item needs a persona, start URL, target URL, label, and question.
- The navigator prompt lives inline in `src/adaptive_network/agents.py`. Adjust it there if you want different tool semantics or stricter formatting.
