#!/usr/bin/env python3
"""Utilities for regenerating persona scaffolds stored in SQLite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from adaptive_network import ledger  # noqa: E402
from adaptive_network.engine import _default_scaffold_dict  # noqa: E402
from adaptive_network.graph import PERSONA_PREFIXES, persona_scaffold  # noqa: E402


def load_current_scaffold(db_path: Path) -> tuple[int, dict]:
    default = json.dumps(_default_scaffold_dict(), ensure_ascii=False, indent=2)
    scaffold_id, body = ledger.load_latest_scaffold(default, path=db_path)
    return scaffold_id, json.loads(body)


def save_scaffold(body: dict, db_path: Path) -> int:
    payload = dict(body)
    scaffold_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return ledger.save_scaffold(scaffold_json, path=db_path)


def regenerate(personas: Iterable[str], limit: int, db_path: Path) -> None:
    _, scaffold_body = load_current_scaffold(db_path)
    config = scaffold_body.get("__config__", {})
    updated: List[str] = []
    for persona in personas:
        scaffold_body[persona] = persona_scaffold(persona, limit=limit)
        updated.append(persona)
    scaffold_body["__config__"] = config
    new_id = save_scaffold(scaffold_body, db_path)
    persona_list = ", ".join(updated) if updated else "none"
    print(f"Scaffold {new_id} saved (personas regenerated: {persona_list})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage persona scaffolds.")
    sub = parser.add_subparsers(dest="command", required=True)

    regen = sub.add_parser("regen", help="Regenerate scaffolds from the graph.")
    regen.add_argument("--persona", default="all", help="Persona key or 'all'.")
    regen.add_argument("--limit", type=int, default=30, help="Entries per persona.")
    regen.add_argument("--db-path", type=Path, default=Path("agent_history/ledger.db"))

    args = parser.parse_args()

    if args.command == "regen":
        if args.persona == "all":
            personas = PERSONA_PREFIXES.keys()
        else:
            if args.persona not in PERSONA_PREFIXES:
                raise SystemExit(f"Unknown persona '{args.persona}'.")
            personas = [args.persona]
        regenerate(personas, limit=max(1, args.limit), db_path=Path(args.db_path))


if __name__ == "__main__":
    main()
