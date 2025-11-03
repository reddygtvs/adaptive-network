#!/usr/bin/env python3
"""CLI entry point for running adaptive network cycles."""

import argparse
import sys
import warnings
from pathlib import Path

import urllib3

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from adaptive_network.engine import RunnerConfig, main  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the adaptive network loop.")
    parser.add_argument("--cycles", type=int, default=1, help="Number of cycles to run this invocation.")
    parser.add_argument("--missions", type=Path, default=Path("data/missions.json"), help="Path to missions JSON.")
    parser.add_argument("--db-path", type=Path, default=Path("agent_history/ledger.db"), help="SQLite ledger path.")
    parser.add_argument("--batch-size", type=int, default=10, help="Concurrent missions per batch.")
    parser.add_argument(
        "--stagger",
        type=float,
        default=0.35,
        help="Seconds to stagger parallel launches within a batch.",
    )
    parser.add_argument("--auto", action="store_true", help="Auto-apply controller suggestions without prompting.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum missions per cycle (0 = all missions).")
    return parser.parse_args()


def main_cli() -> None:
    warnings.filterwarnings("ignore", category=urllib3.exceptions.NotOpenSSLWarning)
    args = parse_args()
    runner = RunnerConfig(
        batch_size=max(1, args.batch_size),
        stagger_seconds=max(0.0, args.stagger),
        parallel=True,
        auto_apply=args.auto,
        mission_limit=args.limit if args.limit and args.limit > 0 else None,
    )
    main(
        cycles=max(1, args.cycles),
        missions_path=args.missions,
        db_path=args.db_path,
        runner=runner,
    )


if __name__ == "__main__":
    main_cli()
