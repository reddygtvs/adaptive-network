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

## Requirements
- Python ≥ 3.10
- `requests`, `networkx`

```bash
python -m pip install --upgrade pip
python -m pip install requests networkx
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
- Runs every mission with the navigator, which repeatedly requests outgoing links before locking in a final URL.
- Sends the prediction through a critique pass and records tokens, costs, and outcomes in `agent_history/ledger.db`.

### Output reference
- CLI prints per-mission success flags, token totals, elapsed time, and USD cost (input $0.60/M, cached $0.11/M, output $2.20/M for `glm-4.6`).
- SQLite keeps every cycle in `agent_history/ledger.db`, including raw navigator turns and critique payloads for later analysis.

## Mission tweaks
- Edit `data/missions.json` to add/remove missions (persona, start URL, target URL, label, question).
- Adjust the navigator prompt directly inside `src/adaptive_network/agents.py` if you want different tooling rules.
