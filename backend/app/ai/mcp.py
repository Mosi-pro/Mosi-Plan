"""Minimaler MCP-Server (Streamable HTTP, JSON-Antworten) für Hermes Agent.

Hermes verbindet sich laut Hermes-Doku über `mcp_servers.<name>.url` + `headers`.
Der Endpunkt ist nur im internen Docker-Netz erreichbar (Nginx leitet /internal
nicht weiter) und zusätzlich per Bearer-Token geschützt. Er stellt ausschließlich
die MOSI-Werkzeuge bereit – mit derselben Validierung und Bestätigungslogik wie
im direkten Modus.
"""
import json
import secrets

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..config import APP_VERSION, get_settings
from ..db import SessionLocal
from ..security import get_owner, rate_limit
from .tools import REGISTRY, ToolContext, execute_tool, mcp_tools

router = APIRouter()
SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")


def _authorized(request: Request) -> bool:
    token = get_settings().mcp_token
    header = request.headers.get("authorization", "")
    return bool(token) and secrets.compare_digest(header, f"Bearer {token}")


def _result(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _handle(msg: dict) -> dict | None:
    method = msg.get("method")
    id_ = msg.get("id")
    params = msg.get("params") or {}
    if id_ is None:  # Notification
        return None
    if method == "initialize":
        requested = params.get("protocolVersion")
        return _result(id_, {
            "protocolVersion": requested if requested in SUPPORTED else SUPPORTED[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "mosi-plan", "version": APP_VERSION},
            "instructions": "Werkzeuge von MOSI PLAN. Bestätigungspflichtige Aktionen liefern status=confirmation_required und werden erst nach Freigabe durch den Benutzer ausgeführt.",
        })
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": mcp_tools()})
    if method == "tools/call":
        name = params.get("name", "")
        if name not in REGISTRY:
            return _error(id_, -32602, f"Unbekanntes Werkzeug: {name}")
        rate_limit("mcp:tools", 120, 60)
        db = SessionLocal()
        try:
            ctx = ToolContext(db=db, user=get_owner(db), actor="assistant")
            out = execute_tool(ctx, name, params.get("arguments") or {})
        finally:
            db.close()
        return _result(id_, {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, default=str)}], "structuredContent": out, "isError": not out.get("ok", False)})
    if method in ("resources/list", "prompts/list"):
        return _result(id_, {method.split("/")[0]: []})
    return _error(id_, -32601, f"Methode nicht unterstützt: {method}")


@router.post("/internal/mcp")
async def mcp_post(request: Request):
    if not _authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
    from starlette.concurrency import run_in_threadpool

    if isinstance(payload, list):
        out = [r for r in [await run_in_threadpool(_handle, m) for m in payload] if r]
        return JSONResponse(out) if out else Response(status_code=202)
    res = await run_in_threadpool(_handle, payload)
    return JSONResponse(res) if res else Response(status_code=202)


@router.get("/internal/mcp")
async def mcp_get(request: Request):
    # Kein serverseitiger SSE-Stream – laut Spezifikation mit 405 zu beantworten.
    return Response(status_code=405 if _authorized(request) else 401)


@router.delete("/internal/mcp")
async def mcp_delete():
    return Response(status_code=405)
