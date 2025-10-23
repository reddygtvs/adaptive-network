from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable

from .missions import Mission

DEFAULT_DB_PATH = Path("agent_history/ledger.db")

PROMPTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT UNIQUE NOT NULL,
    body TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

SCAFFOLDS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scaffolds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT UNIQUE NOT NULL,
    body TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

MISSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS missions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona TEXT NOT NULL,
    question TEXT NOT NULL,
    start_url TEXT NOT NULL,
    target_url TEXT NOT NULL,
    target_label TEXT NOT NULL,
    hardness REAL NOT NULL,
    UNIQUE(persona, question, start_url, target_url)
);
"""

CYCLES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle INTEGER NOT NULL,
    mission_id INTEGER NOT NULL,
    persona TEXT NOT NULL,
    success INTEGER NOT NULL,
    start_url TEXT NOT NULL,
    target_url TEXT NOT NULL,
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
    shortest_hops INTEGER,
    critique_state TEXT,
    critique_justification TEXT,
    raw_response TEXT,
    raw_critique TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(mission_id) REFERENCES missions(id)
);
"""

CYCLE_METRICS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cycle_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle INTEGER UNIQUE NOT NULL,
    successes INTEGER NOT NULL,
    failures INTEGER NOT NULL,
    total_cost REAL NOT NULL,
    payload TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

REVISIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle INTEGER NOT NULL,
    target TEXT NOT NULL,
    suggestion TEXT,
    rationale TEXT,
    payload TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    prompt_id INTEGER,
    scaffold_id INTEGER,
    raw_response TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

EXPECTED_CYCLES_COLUMNS = [
    "id",
    "cycle",
    "mission_id",
    "persona",
    "success",
    "start_url",
    "target_url",
    "predicted_url",
    "prompt_id",
    "scaffold_id",
    "subagent_tokens_in",
    "subagent_tokens_out",
    "subagent_cost",
    "critique_tokens_in",
    "critique_tokens_out",
    "critique_cost",
    "total_cost",
    "wall_time_ms",
    "shortest_hops",
    "critique_state",
    "critique_justification",
    "raw_response",
    "raw_critique",
    "created_at",
]

EXPECTED_MISSIONS_COLUMNS = [
    "id",
    "persona",
    "question",
    "start_url",
    "target_url",
    "target_label",
    "hardness",
]


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def _ensure_table(conn: sqlite3.Connection, table: str, expected_cols: list[str], create_sql: str) -> None:
    try:
        cols = _table_columns(conn, table)
    except sqlite3.OperationalError:
        cols = []
    if cols != expected_cols:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(create_sql)


def init_db(path: Path | str = DEFAULT_DB_PATH) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(PROMPTS_TABLE_SQL)
        conn.execute(SCAFFOLDS_TABLE_SQL)
        _ensure_table(conn, "missions", EXPECTED_MISSIONS_COLUMNS, MISSIONS_TABLE_SQL)
        _ensure_table(conn, "cycles", EXPECTED_CYCLES_COLUMNS, CYCLES_TABLE_SQL)
        conn.execute(CYCLE_METRICS_TABLE_SQL)
        conn.execute(REVISIONS_TABLE_SQL)
        conn.commit()


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


def register_missions(missions: Iterable[Mission], path: Path | str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(Path(path)) as conn:
        for mission in missions:
            conn.execute(
                """
                INSERT OR IGNORE INTO missions (
                    persona,
                    question,
                    start_url,
                    target_url,
                    target_label,
                    hardness
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    mission.persona,
                    mission.question,
                    mission.start_url,
                    mission.target_url,
                    mission.target_label,
                    mission.shortest_hops,
                ),
            )
        conn.commit()
        for mission in missions:
            cursor = conn.execute(
                """
                SELECT id FROM missions
                WHERE persona = ? AND question = ? AND start_url = ? AND target_url = ?
                """,
                (
                    mission.persona,
                    mission.question,
                    mission.start_url,
                    mission.target_url,
                ),
            )
            row = cursor.fetchone()
            if row:
                mission.id = row[0]


@dataclass
class MissionLog:
    cycle: int
    mission_id: int
    persona: str
    success: bool
    start_url: str
    target_url: str
    predicted_url: str | None
    prompt_id: int
    scaffold_id: int
    shortest_hops: int
    subagent_tokens_in: int | None
    subagent_tokens_out: int | None
    subagent_cost: float | None
    critique_tokens_in: int | None
    critique_tokens_out: int | None
    critique_cost: float | None
    total_cost: float | None
    wall_time_ms: int | None
    critique_state: str | None
    critique_justification: str | None
    raw_response: Any
    raw_critique: Any


def log_task(task_log: MissionLog, path: Path | str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(Path(path)) as conn:
        conn.execute(
            """
            INSERT INTO cycles (
                cycle,
                mission_id,
                persona,
                success,
                start_url,
                target_url,
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
                shortest_hops,
                critique_state,
                critique_justification,
                raw_response,
                raw_critique
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_log.cycle,
                task_log.mission_id,
                task_log.persona,
                int(task_log.success),
                task_log.start_url,
                task_log.target_url,
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
                task_log.shortest_hops,
                task_log.critique_state,
                task_log.critique_justification,
                json.dumps(task_log.raw_response),
                json.dumps(task_log.raw_critique),
            ),
        )
        conn.commit()


def record_cycle_metrics(
    *,
    cycle: int,
    successes: int,
    failures: int,
    total_cost: float,
    payload: Dict[str, Any],
    path: Path | str = DEFAULT_DB_PATH,
) -> None:
    with sqlite3.connect(Path(path)) as conn:
        conn.execute(
            """
            INSERT INTO cycle_metrics (cycle, successes, failures, total_cost, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cycle) DO UPDATE SET
                successes=excluded.successes,
                failures=excluded.failures,
                total_cost=excluded.total_cost,
                payload=excluded.payload
            """,
            (cycle, successes, failures, total_cost, json.dumps(payload)),
        )
        conn.commit()


def log_revision(
    *,
    cycle: int,
    target: str,
    suggestion: str | None,
    rationale: str | None,
    payload: Dict[str, Any],
    status: str = "pending",
    prompt_id: int | None = None,
    scaffold_id: int | None = None,
    raw_response: Dict[str, Any] | None = None,
    path: Path | str = DEFAULT_DB_PATH,
) -> None:
    with sqlite3.connect(Path(path)) as conn:
        conn.execute(
            """
            INSERT INTO revisions (
                cycle, target, suggestion, rationale, payload, status, prompt_id, scaffold_id, raw_response
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cycle,
                target,
                suggestion,
                rationale,
                json.dumps(payload),
                status,
                prompt_id,
                scaffold_id,
                json.dumps(raw_response) if raw_response is not None else None,
            ),
        )
        conn.commit()
