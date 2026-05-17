from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.common.logging import get_logger

logger = get_logger(component="api_frontend")
_FRONTEND_DIR = Path(os.getenv("FRONTEND_DIST_DIR", "/app/dist/frontend"))
_RESERVED_FRONTEND_PATHS = {"api", "assets", "health", "metrics", "reports", "v1", "ws"}


def mount_frontend(app: FastAPI) -> None:
    index_path = _FRONTEND_DIR / "index.html"
    assets_dir = _FRONTEND_DIR / "assets"
    if not index_path.is_file() or not assets_dir.is_dir():
        logger.warning("frontend_dist_not_found", path=str(_FRONTEND_DIR))
        return

    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return FileResponse(index_path)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_spa(full_path: str) -> FileResponse:
        root_segment = full_path.split("/", 1)[0]
        if root_segment in _RESERVED_FRONTEND_PATHS:
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(index_path)


__all__ = ["mount_frontend"]
