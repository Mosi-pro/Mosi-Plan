"""MOSI PLAN – FastAPI-Anwendung."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .ai import mcp
from .config import APP_VERSION, get_settings
from .jobs import start_scheduler, stop_scheduler
from .routers import assistant, auth, calendar, core, planner, system

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mosi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if not s.secret_key and not s.testing:
        raise RuntimeError("SECRET_KEY fehlt. Bitte install.sh ausführen oder .env prüfen.")
    for sub in ("uploads", "backups"):
        try:
            os.makedirs(os.path.join(s.data_dir, sub), exist_ok=True)
        except OSError:
            log.warning("Verzeichnis %s/%s nicht beschreibbar", s.data_dir, sub)
    start_scheduler()
    log.info("MOSI PLAN %s gestartet", APP_VERSION)
    yield
    stop_scheduler()


app = FastAPI(title="MOSI PLAN", version=APP_VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    msgs = []
    for e in exc.errors()[:5]:
        loc = ".".join(str(x) for x in e.get("loc", []) if x not in ("body", "query"))
        msgs.append(f"{loc}: {e.get('msg')}" if loc else e.get("msg"))
    return JSONResponse({"detail": "Ungültige Eingabe – " + "; ".join(msgs)}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    log.exception("Unbehandelter Fehler bei %s", request.url.path)
    return JSONResponse({"detail": "Interner Fehler. Details stehen im Server-Log."}, status_code=500)


@app.get("/api/health")
def health():
    from sqlalchemy import text

    from .db import engine

    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "ok", "version": APP_VERSION}
    except Exception:  # noqa: BLE001
        return JSONResponse({"status": "error", "database": False}, status_code=503)


for r in (auth.router, core.router, calendar.router, assistant.router, planner.router, system.router, mcp.router):
    app.include_router(r)
