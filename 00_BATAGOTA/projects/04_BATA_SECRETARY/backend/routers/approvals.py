from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, Header, HTTPException

from database import db_cursor

router = APIRouter(prefix="/api/v1/sessions/{session_id}/approvals", tags=["approvals"])


def _require_demo_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    token = authorization.split(" ", 1)[1].strip()
    if not token.startswith("demo-token-"):
        raise HTTPException(status_code=401, detail="Invalid token")
    return token.replace("demo-token-", "", 1) or "unknown"


def _insert_approval(session_id: int, action: str, actor: str, note: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    with db_cursor() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                note TEXT,
                acted_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO approvals (session_id, action, actor, note, acted_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, action, actor, note, now),
        )

        if action == "confirm1":
            conn.execute("UPDATE sessions SET status = 'confirmed_1st' WHERE id = ?", (session_id,))
        elif action == "confirm2":
            conn.execute("UPDATE sessions SET status = 'confirmed_2nd' WHERE id = ?", (session_id,))
        elif action == "reject":
            conn.execute("UPDATE sessions SET status = 'rejected' WHERE id = ?", (session_id,))

        conn.commit()
    return {"session_id": session_id, "action": action, "actor": actor, "note": note, "acted_at": now}


@router.post("/confirm1")
def confirm1(session_id: int, payload: Optional[Dict[str, Any]] = None, authorization: Optional[str] = Header(default=None)):
    actor = _require_demo_token(authorization)
    note = (payload or {}).get("note")
    return _insert_approval(session_id, "confirm1", actor, note)


@router.post("/confirm2")
def confirm2(session_id: int, payload: Optional[Dict[str, Any]] = None, authorization: Optional[str] = Header(default=None)):
    actor = _require_demo_token(authorization)
    note = (payload or {}).get("note")
    return _insert_approval(session_id, "confirm2", actor, note)


@router.post("/reject")
def reject(session_id: int, payload: Optional[Dict[str, Any]] = None, authorization: Optional[str] = Header(default=None)):
    actor = _require_demo_token(authorization)
    note = (payload or {}).get("note")
    return _insert_approval(session_id, "reject", actor, note)


@router.post("/revise")
def revise(session_id: int, payload: Optional[Dict[str, Any]] = None, authorization: Optional[str] = Header(default=None)):
    actor = _require_demo_token(authorization)
    note = (payload or {}).get("note")
    return _insert_approval(session_id, "revision_requested", actor, note)


@router.get("/history")
def history(session_id: int, authorization: Optional[str] = Header(default=None)):
    _require_demo_token(authorization)
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT action, actor, note, acted_at FROM approvals WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]
