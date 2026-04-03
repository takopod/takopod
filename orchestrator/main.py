import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from orchestrator.boot_recovery import boot_recovery
from orchestrator.container_manager import build_image, ensure_network
from orchestrator.db import connect, disconnect, run_migrations
from orchestrator.ollama import (
    check_ollama_status,
    start_ollama,
    stop_ollama,
    wait_for_ollama,
)
from orchestrator.routes import _reap_idle_workers, router

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

_schema_version: int = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _schema_version
    db = await connect()
    _schema_version = await run_migrations(db)

    await boot_recovery()

    await ensure_network()
    await build_image()

    await start_ollama()
    await wait_for_ollama()

    reaper_task = asyncio.create_task(_reap_idle_workers(), name="idle-reaper")
    yield
    reaper_task.cancel()
    await stop_ollama()
    await disconnect()


app = FastAPI(title="rhclaw", lifespan=lifespan)
app.include_router(router)

@app.get("/api/health")
async def health():
    ollama = await check_ollama_status()
    return {"status": "ok", "schema_version": _schema_version, "ollama": ollama}


if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        return FileResponse(WEB_DIST / "index.html")
