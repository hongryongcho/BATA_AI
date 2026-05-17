from __future__ import annotations

import asyncio
import logging
import time
import uuid

logger = logging.getLogger(__name__)
from contextlib import asynccontextmanager
from typing import Optional
import bcrypt
import os
from threading import Lock

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Body, UploadFile, File, Header, Form
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, db_cursor
from security import create_token
from security import verify_token, extract_token_from_header
from routers.approvals import router as approvals_router
from routers.ws import router as ws_router
from routers.records import router as records_router
from routers.reference import router as reference_router
from stt import transcribe_audio_bytes, transcribe_full_audio_bytes, transcribe_youtube_url_detailed
from llm_summary import generate_summary

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="BATA Secretary", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8811",
        "http://127.0.0.1:8812",
        "http://localhost:8811",
        "http://localhost:8812",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(ws_router)
app.include_router(approvals_router)
app.include_router(records_router)
app.include_router(reference_router)

_YT_JOBS = {}
_YT_JOBS_LOCK = Lock()
_YT_JOB_TTL_SEC = int(os.getenv("YOUTUBE_JOB_TTL_SEC", "1800"))


def _cleanup_yt_jobs() -> None:
    now = time.time()
    with _YT_JOBS_LOCK:
        expired_keys = [
            key
            for key, job in _YT_JOBS.items()
            if now - float(job.get("updated_at", now)) > _YT_JOB_TTL_SEC
        ]
        for key in expired_keys:
            _YT_JOBS.pop(key, None)


def _set_yt_job(job_id: str, **updates) -> None:
    with _YT_JOBS_LOCK:
        job = _YT_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = time.time()


def _get_yt_job(job_id: str) -> Optional[dict]:
    with _YT_JOBS_LOCK:
        job = _YT_JOBS.get(job_id)
        if not job:
            return None
        return dict(job)


@app.get("/")
async def health_check():
    return {"status": "ok", "service": "BATA Secretary"}


@app.post("/auth/login")
async def login(username: str = Body(...), password: str = Body(...)):
    """
    JWT 토큰 발급 (bcrypt 비밀번호 해싱)
    요청 바디: {"username": "hong", "password": "hong123"}
    응답: {"access_token": "...", "token_type": "bearer", ...}
    """
    with db_cursor() as conn:
        user = conn.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    
    if not user or not bcrypt.checkpw(password.encode('utf-8'), user["password_hash"].encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token(user["id"], user["username"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "role": user["role"],
    }


def _require_jwt_user(authorization: Optional[str]) -> dict:
    token = extract_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload


@app.post("/api/v1/transcriptions/upload")
async def transcribe_uploaded_audio(
    audio_file: UploadFile = File(...),
    stt_profile: str = Form(default="normal"),
    authorization: Optional[str] = Header(default=None),
):
    payload = _require_jwt_user(authorization)
    audio_bytes = await audio_file.read()
    transcript = await asyncio.to_thread(
        transcribe_full_audio_bytes,
        audio_bytes,
        0,
        audio_file.content_type or audio_file.filename or "audio/webm",
        "ko",
        stt_profile,
    )
    return {
        "filename": audio_file.filename,
        "content_type": audio_file.content_type,
        "transcript": transcript,
        "stt_profile": stt_profile,
        "uploaded_by": payload.get("username"),
    }


@app.post("/api/v1/transcriptions/youtube")
async def transcribe_youtube(
    body: dict = Body(...),
    authorization: Optional[str] = Header(default=None),
):
    payload = _require_jwt_user(authorization)
    url: str = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url 필드가 필요합니다.")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="유효하지 않은 URL 형식입니다.")
    stt_profile: str = (body.get("stt_profile") or "normal").strip().lower()
    try:
        result = await asyncio.to_thread(transcribe_youtube_url_detailed, url, "ko", stt_profile)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "url": url,
        "transcript": result.get("transcript", ""),
        "source": result.get("source"),
        "subtitle_status": result.get("subtitle_status"),
        "subtitle_language": result.get("subtitle_language"),
        "subtitle_provider": result.get("subtitle_provider"),
        "subtitle_items": result.get("subtitle_items", []),
        "timings_ms": result.get("timings_ms", {}),
        "notice": result.get("notice", ""),
        "stt_profile": stt_profile,
        "requested_by": payload.get("username"),
    }


@app.post("/api/v1/transcriptions/youtube/jobs")
async def create_youtube_transcription_job(
    body: dict = Body(...),
    authorization: Optional[str] = Header(default=None),
):
    payload = _require_jwt_user(authorization)
    url: str = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url 필드가 필요합니다.")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="유효하지 않은 URL 형식입니다.")

    stt_profile: str = (body.get("stt_profile") or "normal").strip().lower()
    job_id = str(uuid.uuid4())
    now_ts = time.time()

    _cleanup_yt_jobs()
    with _YT_JOBS_LOCK:
        _YT_JOBS[job_id] = {
            "job_id": job_id,
            "url": url,
            "stt_profile": stt_profile,
            "requested_by": payload.get("username"),
            "status": "queued",
            "stage": "queued",
            "stage_label": "대기 중",
            "created_at": now_ts,
            "updated_at": now_ts,
            "timings_ms": {},
            "result": None,
            "error": None,
        }

    def progress_callback(stage: str, message: str) -> None:
        _set_yt_job(job_id, status="running", stage=stage, stage_label=message)

    async def run_job() -> None:
        _set_yt_job(job_id, status="running", stage="started", stage_label="작업 시작")
        try:
            result = await asyncio.to_thread(
                transcribe_youtube_url_detailed,
                url,
                "ko",
                stt_profile,
                progress_callback,
            )
            _set_yt_job(
                job_id,
                status="completed",
                stage="completed",
                stage_label="전사 완료",
                result=result,
                timings_ms=result.get("timings_ms", {}),
            )
        except Exception as exc:
            _set_yt_job(
                job_id,
                status="failed",
                stage="failed",
                stage_label="전사 실패",
                error=str(exc),
            )

    asyncio.create_task(run_job())

    return {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "stage_label": "대기 중",
    }


@app.get("/api/v1/transcriptions/youtube/jobs/{job_id}")
async def get_youtube_transcription_job(
    job_id: str,
    authorization: Optional[str] = Header(default=None),
):
    _require_jwt_user(authorization)
    _cleanup_yt_jobs()
    job = _get_yt_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="요청한 전사 작업을 찾을 수 없습니다.")

    return {
        "job_id": job["job_id"],
        "status": job.get("status"),
        "stage": job.get("stage"),
        "stage_label": job.get("stage_label"),
        "timings_ms": job.get("timings_ms", {}),
        "result": job.get("result"),
        "error": job.get("error"),
        "requested_by": job.get("requested_by"),
    }


@app.post("/api/v1/summaries/auto-generate")
async def auto_generate_summary(
    body: dict = Body(...),
    authorization: Optional[str] = Header(default=None),
):
    """로컬 LLM(Ollama)을 사용하여 전사 내용을 자동 요약"""
    payload = _require_jwt_user(authorization)
    transcript: str = (body.get("transcript") or "").strip()
    
    if not transcript:
        raise HTTPException(status_code=400, detail="transcript 필드가 필요합니다.")
    
    try:
        summary = await asyncio.to_thread(generate_summary, transcript)
        return {
            "status": "success",
            "summary": summary,
            "generated_by": payload.get("username"),
        }
    except RuntimeError as exc:
        logger.error("[summary] RuntimeError: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))
