from __future__ import annotations

from sqlalchemy import Engine


_TABLE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "search_configs": [
        ("sources_json", "TEXT NOT NULL DEFAULT '[\"linkedin_public\"]'"),
    ],
    "candidate_profiles": [
        ("llm_profile_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("llm_strategy_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("profile_fingerprint", "TEXT NULL"),
        ("llm_model", "TEXT NULL"),
        ("llm_prompt_version", "TEXT NULL"),
        ("llm_status", "TEXT NOT NULL DEFAULT 'fallback'"),
        ("llm_error", "TEXT NULL"),
        ("learned_preferences_json", "TEXT NOT NULL DEFAULT '{}'"),
    ],
    "job_postings": [
        ("job_category", "TEXT NULL"),
        ("job_subcategory", "TEXT NULL"),
        ("job_content_hash", "TEXT NULL"),
    ],
    "search_results": [
        ("llm_fit_score", "REAL NOT NULL DEFAULT 0"),
        ("final_score", "REAL NOT NULL DEFAULT 0"),
        ("fit_reasons_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("gap_notes_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("role_alignment_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("llm_status", "TEXT NOT NULL DEFAULT 'fallback'"),
        ("llm_analysis_hash", "TEXT NULL"),
    ],
    "sessions": [
        ("analysis_executed_at", "DATETIME NULL"),
    ],
}

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_search_results_search_final_score ON search_results (search_config_id, final_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_search_results_search_discovered ON search_results (search_config_id, discovered_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_job_postings_category ON job_postings (job_category, job_subcategory)",
]


def run_db_migrations(engine: Engine) -> None:
    if not str(engine.url).startswith("sqlite"):
        return

    with engine.begin() as conn:
        for table_name, columns in _TABLE_COLUMNS.items():
            if not _table_exists(conn, table_name):
                continue

            existing_columns = _existing_columns(conn, table_name)
            for column_name, ddl in columns:
                if column_name in existing_columns:
                    continue
                conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")
                existing_columns.add(column_name)

        for stmt in _INDEXES:
            conn.exec_driver_sql(stmt)


def _table_exists(conn, table_name: str) -> bool:
    row = conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).first()
    return bool(row)


def _existing_columns(conn, table_name: str) -> set[str]:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").all()
    return {str(row[1]) for row in rows}
