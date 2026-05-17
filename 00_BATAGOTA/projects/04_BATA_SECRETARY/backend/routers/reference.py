"""
참고 자료 라우터.

POST /api/v1/reference-materials            ─ 텍스트 참고 자료 저장 (1차 Confirm 즉시)
POST /api/v1/reference-materials/upload     ─ 파일 참고 자료 저장
GET  /api/v1/reference-materials            ─ 전체 목록 (선택적으로 session 필터)
GET  /api/v1/reference-materials/{id}       ─ 단건 조회
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Body, UploadFile, File, Form

from database import db_cursor
from security import verify_token, extract_token_from_header

router = APIRouter(tags=["reference"])


def _require_user(authorization: Optional[str]) -> dict:
    token = extract_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authorization header required")
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


@router.post("/api/v1/reference-materials")
def save_reference_text(
    body: dict = Body(...),
    authorization: Optional[str] = Header(default=None),
):
    """
    텍스트 참고 자료 저장 (1차 Confirm만으로 완료).
    body: { title, content, attached_session_id (nullable) }
    """
    user = _require_user(authorization)
    now = datetime.now().isoformat(timespec="seconds")

    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    attached_session_id = body.get("attached_session_id") or None

    if not title:
        raise HTTPException(status_code=400, detail="title은 필수입니다.")

    if attached_session_id is not None:
        # 유효한 session_id인지 확인 (session_records에 있어야 첨부 가능)
        with db_cursor() as conn:
            rec = conn.execute(
                "SELECT session_id FROM session_records WHERE session_id = ?",
                (attached_session_id,),
            ).fetchone()
        if not rec:
            raise HTTPException(
                status_code=404,
                detail=f"session_id={attached_session_id}에 해당하는 확정 회의록이 없습니다.",
            )

    with db_cursor() as conn:
        cur = conn.execute(
            """
            INSERT INTO reference_materials
              (attached_session_id, title, content, file_type, uploaded_by, uploaded_at)
            VALUES (?, ?, ?, 'text', ?, ?)
            """,
            (attached_session_id, title, content, user["username"], now),
        )
        conn.commit()
        new_id = cur.lastrowid

    return {
        "status": "ok",
        "id": new_id,
        "title": title,
        "attached_session_id": attached_session_id,
        "uploaded_by": user["username"],
        "uploaded_at": now,
    }


@router.post("/api/v1/reference-materials/upload")
async def upload_reference_file(
    title: str = Form(...),
    attached_session_id: Optional[int] = Form(default=None),
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(default=None),
):
    """파일 참고 자료 저장 (파일 내용은 텍스트로 저장)."""
    user = _require_user(authorization)
    now = datetime.now().isoformat(timespec="seconds")

    raw = await file.read()
    try:
        content = raw.decode("utf-8", errors="replace")
    except Exception:
        content = f"[바이너리 파일: {file.filename}, {len(raw)} bytes]"

    if attached_session_id is not None:
        with db_cursor() as conn:
            rec = conn.execute(
                "SELECT session_id FROM session_records WHERE session_id = ?",
                (attached_session_id,),
            ).fetchone()
        if not rec:
            raise HTTPException(
                status_code=404,
                detail=f"session_id={attached_session_id}에 해당하는 확정 회의록이 없습니다.",
            )

    with db_cursor() as conn:
        cur = conn.execute(
            """
            INSERT INTO reference_materials
              (attached_session_id, title, content, file_type, uploaded_by, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (attached_session_id, title or file.filename, content,
             file.content_type or "file", user["username"], now),
        )
        conn.commit()
        new_id = cur.lastrowid

    return {
        "status": "ok",
        "id": new_id,
        "title": title or file.filename,
        "filename": file.filename,
        "attached_session_id": attached_session_id,
        "uploaded_by": user["username"],
        "uploaded_at": now,
    }


@router.get("/api/v1/reference-materials")
def list_references(
    session_id: Optional[int] = None,
    authorization: Optional[str] = Header(default=None),
):
    _require_user(authorization)
    with db_cursor() as conn:
        if session_id is not None:
            rows = conn.execute(
                "SELECT id, attached_session_id, title, file_type, uploaded_by, uploaded_at FROM reference_materials WHERE attached_session_id = ? ORDER BY id DESC",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, attached_session_id, title, file_type, uploaded_by, uploaded_at FROM reference_materials ORDER BY id DESC",
            ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/v1/reference-materials/{ref_id}")
def get_reference(
    ref_id: int,
    authorization: Optional[str] = Header(default=None),
):
    _require_user(authorization)
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT * FROM reference_materials WHERE id = ?",
            (ref_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="참고 자료를 찾을 수 없습니다.")
    return dict(row)
