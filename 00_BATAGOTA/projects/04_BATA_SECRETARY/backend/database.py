from __future__ import annotations

import os
import sqlite3
import bcrypt
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "bata_secretary.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")


def _db_path_from_url(url: str) -> Path:
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", "", 1)).expanduser().resolve()
    return DEFAULT_DB_PATH


def get_db_path() -> Path:
    return _db_path_from_url(DATABASE_URL)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'counselor',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_code TEXT UNIQUE,
                status TEXT NOT NULL DEFAULT 'recording',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                layer TEXT NOT NULL,
                version INTEGER NOT NULL,
                content TEXT NOT NULL,
                edited_by TEXT,
                is_latest INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                note TEXT,
                acted_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )
            """
        )
        # 테스트용 사용자 생성 (bcrypt 해싱 적용)
        hong_password = "hong123"
        kim_password = "kim456"
        
        hong_hash = bcrypt.hashpw(hong_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        kim_hash = bcrypt.hashpw(kim_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES (?, ?, ?, ?)",
            ("user-hong", "hong", hong_hash, "counselor"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES (?, ?, ?, ?)",
            ("user-kim", "kim", kim_hash, "approver"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, session_code, status) VALUES (2, ?, 'recording')",
            ("2026-05-14-017",),
        )
        conn.commit()


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
