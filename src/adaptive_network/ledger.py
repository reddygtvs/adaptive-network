from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

DEFAULT_DB_PATH = Path("agent_history/ledger.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT UNIQUE NOT NULL,
    body TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scaffolds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT UNIQUE NOT NULL,
    body TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle INTEGER NOT NULL,
    task_id TEXT NOT NULL,
    persona TEXT NOT NULL,
    success INTEGER NOT NULL,
    expected_url TEXT NOT NULL,
    predicted_url TEXT,
    prompt_id INTEGER NOT NULL,
    scaffold_id INTEGER NOT NULL,
    subagent_tokens_in INTEGER,
    subagent_tokens_out INTEGER,
    subagent_cost REAL,
    critique_tokens_in INTEGER,
    critique_tokens_out INTEGER,
    critique_cost REAL,
    total_cost REAL,
    wall_time_ms INTEGER,
    hops INTEGER,
    critique_state TEXT,
    critique_justification TEXT,
    raw_response TEXT,
    raw_critique TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db(path: Path | str = DEFAULT_DB_PATH) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)


def _save_versioned(table: str, body: str, path: Path | str = DEFAULT_DB_PATH) -> int:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with sqlite3.connect(Path(path)) as conn:
        cursor = conn.execute(f"SELECT id FROM {table} WHERE hash = ?", (digest,))
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor = conn.execute(
            f"INSERT INTO {table} (hash, body) VALUES (?, ?)",
            (digest, body),
        )
        conn.commit()
        return cursor.lastrowid


def save_prompt(body: str, path: Path | str = DEFAULT_DB_PATH) -> int:
    return _save_versioned("prompts", body, path)


def save_scaffold(body: str, path: Path | str = DEFAULT_DB_PATH) -> int:
    return _save_versioned("scaffolds", body, path)


@dataclass
class TaskLog:
    cycle: int
    task_id: str
    persona: str
    success: bool
    expected_url: str
    predicted_url: str | None
    prompt_id: int
    scaffold_id: int
    subagent_tokens_in: int | None
    subagent_tokens_out: int | None
    subagent_cost: float | None
    critique_tokens_in: int | None
    critique_tokens_out: int | None
    critique_cost: float | None
    total_cost: float | None
    wall_time_ms: int | None
    hops: int
    critique_state: str | None
    critique_justification: str | None
    raw_response: Dict[str, Any]
    raw_critique: Dict[str, Any]


def log_task(task_log: TaskLog, path: Path | str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(Path(path)) as conn:
        conn.execute(
            """
            INSERT INTO cycles (
                cycle,
                task_id,
                persona,
                success,
                expected_url,
                predicted_url,
                prompt_id,
                scaffold_id,
                subagent_tokens_in,
                subagent_tokens_out,
                subagent_cost,
                critique_tokens_in,
                critique_tokens_out,
                critique_cost,
                total_cost,
                wall_time_ms,
                hops,
                critique_state,
                critique_justification,
                raw_response,
                raw_critique
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_log.cycle,
                task_log.task_id,
                task_log.persona,
                int(task_log.success),
                task_log.expected_url,
                task_log.predicted_url,
                task_log.prompt_id,
                task_log.scaffold_id,
                task_log.subagent_tokens_in,
                task_log.subagent_tokens_out,
                task_log.subagent_cost,
                task_log.critique_tokens_in,
                task_log.critique_tokens_out,
                task_log.critique_cost,
                task_log.total_cost,
                task_log.wall_time_ms,
                task_log.hops,
                task_log.critique_state,
                task_log.critique_justification,
                json.dumps(task_log.raw_response),
                json.dumps(task_log.raw_critique),
            ),
        )
        conn.commit()
