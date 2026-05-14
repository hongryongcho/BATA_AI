from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, Header, HTTPException, Body

from database import db_cursor
from security import verify_token, extract_token_from_header

router = APIRouter(prefix="/api/v1/sessions/{session_id}/approvals", tags=["approvals"])


def _require_jwt_token(authorization: Optional[str]) -> str:
    """
    Authorization 헬더에서 JWT 토큰을 추출하고 검증.
    
    Args:
        authorization: "Bearer <token>" 형식의 헬더
    
    Returns:
        토큰이 유효하면 username, 아니면 HTTPException 발생
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    token = extract_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return payload.get("username", "unknown")


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
def confirm1(session_id: int, payload: Optional[Dict[str, Any]] = Body(default=None), authorization: Optional[str] = Header(default=None)):
    actor = _require_jwt_token(authorization)
    note = (payload or {}).get("note")
    return _insert_approval(session_id, "confirm1", actor, note)


@router.post("/confirm2")
def confirm2(session_id: int, payload: Optional[Dict[str, Any]] = Body(default=None), authorization: Optional[str] = Header(default=None)):
    actor = _require_jwt_token(authorization)
    note = (payload or {}).get("note")
    return _insert_approval(session_id, "confirm2", actor, note)


@router.post("/reject")
def reject(session_id: int, payload: Optional[Dict[str, Any]] = Body(default=None), authorization: Optional[str] = Header(default=None)):
    actor = _require_jwt_token(authorization)
    note = (payload or {}).get("note")
    return _insert_approval(session_id, "reject", actor, note)


@router.post("/revise")
def revise(session_id: int, payload: Optional[Dict[str, Any]] = Body(default=None), authorization: Optional[str] = Header(default=None)):
    actor = _require_jwt_token(authorization)
    note = (payload or {}).get("note")
    return _insert_approval(session_id, "revision_requested", actor, note)


@router.get("/history")
def history(session_id: int, authorization: Optional[str] = Header(default=None)):
    _require_jwt_token(authorization)
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT action, actor, note, acted_at FROM approvals WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]
