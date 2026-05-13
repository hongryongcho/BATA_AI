from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
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
