import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConversationStore:
    DB_PATH = PROJECT_ROOT / "data" / "conversation_memory.db"

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or self.DB_PATH
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_id ON messages(user_id, id)
            """)
            conn.commit()

    def load_history(self, user_id: str, limit: int = 20) -> List[dict]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT role, content FROM (
                    SELECT id, role, content FROM messages
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC
                """,
                (user_id, limit),
            ).fetchall()
        result = []
        for role, content_str in rows:
            try:
                content = json.loads(content_str)
            except (json.JSONDecodeError, TypeError):
                content = content_str
            result.append({"role": role, "content": content})
        return result

    def append(self, user_id: str, role: str, content) -> None:
        if isinstance(content, str):
            content_str = json.dumps(content, ensure_ascii=False)
        else:
            content_str = json.dumps(content, ensure_ascii=False)
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (user_id, role, content_str, now),
            )
            conn.commit()

    def clear(self, user_id: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            conn.commit()
