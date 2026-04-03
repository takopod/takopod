from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from orchestrator.db import connect, disconnect, run_migrations

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

_schema_version: int = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _schema_version
    db = await connect()
    _schema_version = await run_migrations(db)

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="static")

    yield
    await disconnect()


app = FastAPI(title="rhclaw", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"status": "ok", "schema_version": _schema_version}
