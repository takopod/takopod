import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

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
from orchestrator.mcp_seed import seed_builtin_mcp_servers
from orchestrator.ollama import check_ollama_status
from orchestrator.oauth_routes import router as oauth_router
from orchestrator.routes import router
from orchestrator.scheduler import run_scheduler
from orchestrator.settings import get_setting
from orchestrator.slack_poller import run_slack_poller

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

_schema_version: int = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _schema_version
    db = await connect()
    _schema_version = await run_migrations(db)
    await seed_builtin_mcp_servers(db)

    await boot_recovery()

    await ensure_network()
    await build_image()

    scheduler_task = asyncio.create_task(run_scheduler(), name="scheduler")
    slack_poller_task = asyncio.create_task(run_slack_poller(), name="slack-poller")
    yield
    scheduler_task.cancel()
    slack_poller_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    try:
        await slack_poller_task
    except asyncio.CancelledError:
        pass

    from orchestrator.routes import graceful_shutdown
    shutdown_timeout = int(os.environ.get("SHUTDOWN_TIMEOUT_SECONDS", "30"))
    await graceful_shutdown(timeout=shutdown_timeout)

    await disconnect()


app = FastAPI(title="rhclaw", lifespan=lifespan)
app.include_router(router)
app.include_router(oauth_router)

@app.get("/api/health")
async def health():
    if await get_setting("ollama_enabled", "true") == "true":
        ollama = await check_ollama_status()
    else:
        ollama = {"status": "disabled"}
    return {"status": "ok", "schema_version": _schema_version, "ollama": ollama}


if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        # Serve static files from dist root if they exist
        static_file = WEB_DIST / path
        if path and static_file.is_file():
            return FileResponse(static_file)
        return FileResponse(WEB_DIST / "index.html")
