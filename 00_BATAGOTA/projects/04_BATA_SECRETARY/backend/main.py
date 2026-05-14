from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional
import bcrypt
import os

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, db_cursor
from security import create_token
from routers.approvals import router as approvals_router
from routers.ws import router as ws_router

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
