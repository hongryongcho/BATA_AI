from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, db_cursor
from security import create_token
from routers.approvals import router as approvals_router
from routers.ws import router as ws_router


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


@app.get("/")
async def health_check():
    return {"status": "ok", "service": "BATA Secretary"}


@app.post("/auth/login")
async def login(username: str = Body(...), password: str = Body(...)):
    """
    JWT 토큰 발급.
    요청 바디: {"username": "hong", "password": "demo"}
    응답: {"access_token": "...", "token_type": "bearer", ...}
    """
    with db_cursor() as conn:
        user = conn.execute(
            "SELECT id, username, role FROM users WHERE username = ? AND password_hash = ?",
            (username, f"hashed-pwd-{username}"),
        ).fetchone()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token(user["id"], user["username"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "role": user["role"],
    }


@app.post("/auth/login")
async def login(username: str = Body(...), password: str = Body(...)):
    """
    로그인 추감 
    
    발전 단계: 현재는 단순 마다 검스(password == "demo")
    프로덕션에서는 bcrypt 등으로 패스워드 해싱을 구현해야 함
    """
    with db_cursor() as conn:
        user = conn.execute(
            "SELECT id, username, role FROM users WHERE username = ? AND password_hash = ?",
            (username, f"hashed-pwd-{username}"),
        ).fetchone()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token(user["id"], user["username"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "role": user["role"],
    }
