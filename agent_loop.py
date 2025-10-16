#!/usr/bin/env python3
"""Convenience wrapper for running the adaptive network loop."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from adaptive_network.loop import main

if __name__ == "__main__":
    main()
