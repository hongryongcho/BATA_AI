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
                mode TEXT NOT NULL DEFAULT 'counseling',
                status TEXT NOT NULL DEFAULT 'recording',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # sessions 테이블에 mode 컬럼이 없으면 추가 (기존 DB 마이그레이션)
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN mode TEXT NOT NULL DEFAULT 'counseling'")
        except Exception:
            pass

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
        # ── 회의록 확정본 ──────────────────────────────────────────────
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL UNIQUE,
                mode TEXT NOT NULL DEFAULT 'counseling',
                transcript TEXT,
                core_summary TEXT,
                key_points TEXT,
                flow TEXT,
                action_items TEXT,
                counselor_note TEXT,
                confirmed_by TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,
                second_approver TEXT,
                record_status TEXT NOT NULL DEFAULT 'pending_confirm2',
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )
            """
        )
        # ── 2차 승인 댓글 ──────────────────────────────────────────────
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                stage TEXT NOT NULL DEFAULT 'confirm2',
                actor TEXT NOT NULL,
                comment TEXT,
                decision TEXT NOT NULL,
                acted_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )
            """
        )
        # ── 참고 자료 ──────────────────────────────────────────────────
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reference_materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attached_session_id INTEGER,
                title TEXT NOT NULL,
                content TEXT,
                file_type TEXT NOT NULL DEFAULT 'text',
                uploaded_by TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                FOREIGN KEY(attached_session_id) REFERENCES session_records(session_id)
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
