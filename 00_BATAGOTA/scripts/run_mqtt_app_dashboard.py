from __future__ import annotations

import os
from pathlib import Path

import uvicorn

if __name__ == "__main__":
    host = os.getenv("APP_SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("APP_SERVER_PORT", "8787"))
    project_root = Path(__file__).resolve().parents[1]
    uvicorn.run(
        "interfaces.app_server.server:app",
        host=host,
        port=port,
        reload=False,
        app_dir=str(project_root),
    )
