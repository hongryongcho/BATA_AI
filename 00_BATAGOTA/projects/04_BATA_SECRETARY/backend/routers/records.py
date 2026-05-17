"""
회의록 확정본 (session_records) 및 2차 승인 라우터.

POST /api/v1/sessions/{id}/confirm1  ─ 1차 Confirm: DB 저장 + 2차 승인자 지정
POST /api/v1/sessions/{id}/confirm2  ─ 2차 Confirm: 댓글 + 승인/반려
GET  /api/v1/records                 ─ 확정본 목록 (승인자/상담자 공통)
GET  /api/v1/records/{session_id}    ─ 확정본 상세
GET  /api/v1/users/approvers         ─ 2차 승인자 목록 (셀렉트박스용)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Header, HTTPException, Body

from database import db_cursor
from security import verify_token, extract_token_from_header

router = APIRouter(tags=["records"])


def _require_user(authorization: Optional[str]) -> dict:
    token = extract_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authorization header required")
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


# ── 1차 Confirm ────────────────────────────────────────────────────────────────
@router.post("/api/v1/sessions/{session_id}/confirm1")
def confirm1(
    session_id: int,
    body: dict = Body(...),
    authorization: Optional[str] = Header(default=None),
):
    """
    1차 Confirm: 회의록 확정본을 DB에 저장하고 선택적으로 2차 승인자를 지정.
    body: {
      transcript, core_summary, key_points, flow, action_items,
      counselor_note, second_approver (nullable), mode
    }
    """
    user = _require_user(authorization)
    now = datetime.now().isoformat(timespec="seconds")

    transcript = body.get("transcript", "")
    core_summary = body.get("core_summary", "")
    key_points = body.get("key_points", "")
    flow = body.get("flow", "")
    action_items = body.get("action_items", "")
    counselor_note = body.get("counselor_note", "")
    second_approver = body.get("second_approver") or None
    mode = body.get("mode", "counseling")

    if not transcript and not core_summary:
        raise HTTPException(status_code=400, detail="transcript 또는 core_summary가 필요합니다.")

    record_status = "pending_confirm2" if second_approver else "confirmed_1st_only"

    with db_cursor() as conn:
        # sessions 상태 업데이트
        conn.execute(
            "UPDATE sessions SET status = 'confirmed_1st', mode = ? WHERE id = ?",
            (mode, session_id),
        )

        # 기존 session_record 덮어쓰기 (UPSERT)
        conn.execute(
            """
            INSERT INTO session_records
              (session_id, mode, transcript, core_summary, key_points, flow,
               action_items, counselor_note, confirmed_by, confirmed_at,
               second_approver, record_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              mode=excluded.mode,
              transcript=excluded.transcript,
              core_summary=excluded.core_summary,
              key_points=excluded.key_points,
              flow=excluded.flow,
              action_items=excluded.action_items,
              counselor_note=excluded.counselor_note,
              confirmed_by=excluded.confirmed_by,
              confirmed_at=excluded.confirmed_at,
              second_approver=excluded.second_approver,
              record_status=excluded.record_status
            """,
            (session_id, mode, transcript, core_summary, key_points, flow,
             action_items, counselor_note, user["username"], now,
             second_approver, record_status),
        )

        # approvals 이력 기록
        conn.execute(
            "INSERT INTO approvals (session_id, action, actor, note, acted_at) VALUES (?,?,?,?,?)",
            (session_id, "confirm1", user["username"],
             f"2차 승인자: {second_approver or '미지정'}", now),
        )
        conn.commit()

    return {
        "status": "ok",
        "session_id": session_id,
        "confirmed_by": user["username"],
        "confirmed_at": now,
        "second_approver": second_approver,
        "record_status": record_status,
    }


# ── 2차 Confirm (승인/반려) ────────────────────────────────────────────────────
@router.post("/api/v1/sessions/{session_id}/confirm2")
def confirm2(
    session_id: int,
    body: dict = Body(...),
    authorization: Optional[str] = Header(default=None),
):
    """
    2차 Confirm: 댓글 + 'approved' 또는 'rejected'.
    body: { decision: 'approved'|'rejected', comment }
    """
    user = _require_user(authorization)
    now = datetime.now().isoformat(timespec="seconds")

    decision = (body.get("decision") or "").strip().lower()
    comment = (body.get("comment") or "").strip()

    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision은 'approved' 또는 'rejected' 이어야 합니다.")

    with db_cursor() as conn:
        record = conn.execute(
            "SELECT second_approver FROM session_records WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if not record:
            raise HTTPException(status_code=404, detail="1차 Confirm 된 회의록이 없습니다.")

        second_approver = record["second_approver"]
        if second_approver and second_approver != user["username"] and user.get("role") != "admin":
            raise HTTPException(
                status_code=403,
                detail=f"지정된 2차 승인자({second_approver})만 처리할 수 있습니다.",
            )

        new_status = "approved" if decision == "approved" else "rejected"
        conn.execute(
            "UPDATE session_records SET record_status = ? WHERE session_id = ?",
            (new_status, session_id),
        )
        conn.execute(
            "UPDATE sessions SET status = ? WHERE id = ?",
            (new_status, session_id),
        )
        conn.execute(
            """
            INSERT INTO approval_comments
              (session_id, stage, actor, comment, decision, acted_at)
            VALUES (?, 'confirm2', ?, ?, ?, ?)
            """,
            (session_id, user["username"], comment, decision, now),
        )
        conn.execute(
            "INSERT INTO approvals (session_id, action, actor, note, acted_at) VALUES (?,?,?,?,?)",
            (session_id, f"confirm2_{decision}", user["username"], comment, now),
        )
        conn.commit()

    return {
        "status": "ok",
        "session_id": session_id,
        "decision": decision,
        "actor": user["username"],
        "acted_at": now,
    }


# ── 확정본 목록 ────────────────────────────────────────────────────────────────
@router.get("/api/v1/records")
def list_records(
    authorization: Optional[str] = Header(default=None),
):
    user = _require_user(authorization)
    with db_cursor() as conn:
        rows = conn.execute(
            """
            SELECT r.session_id, r.mode, r.core_summary, r.confirmed_by,
                   r.confirmed_at, r.second_approver, r.record_status,
                   s.session_code
            FROM session_records r
            LEFT JOIN sessions s ON s.id = r.session_id
            ORDER BY r.confirmed_at DESC
            """,
        ).fetchall()
    return [dict(row) for row in rows]


# ── 확정본 상세 ────────────────────────────────────────────────────────────────
@router.get("/api/v1/records/{session_id}")
def get_record(
    session_id: int,
    authorization: Optional[str] = Header(default=None),
):
    _require_user(authorization)
    with db_cursor() as conn:
        record = conn.execute(
            "SELECT * FROM session_records WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not record:
            raise HTTPException(status_code=404, detail="확정본이 없습니다.")

        comments = conn.execute(
            "SELECT actor, comment, decision, acted_at FROM approval_comments WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()

        refs = conn.execute(
            "SELECT id, title, file_type, uploaded_by, uploaded_at FROM reference_materials WHERE attached_session_id = ?",
            (session_id,),
        ).fetchall()

    return {
        "record": dict(record),
        "comments": [dict(c) for c in comments],
        "references": [dict(r) for r in refs],
    }


# ── 승인자 목록 (셀렉트박스용) ────────────────────────────────────────────────
@router.get("/api/v1/users/approvers")
def list_approvers(
    authorization: Optional[str] = Header(default=None),
):
    _require_user(authorization)
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT username, role FROM users WHERE role IN ('approver','admin') OR role = 'counselor'",
        ).fetchall()
    return [dict(r) for r in rows]
