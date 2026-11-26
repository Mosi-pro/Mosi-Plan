import json
import os
import shutil
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..ai import agent
from ..config import APP_VERSION, get_settings
from ..db import get_db
from ..models import (
    AuditLog, CalendarEvent, Category, Conversation, MemoryEntry, Message, Notification, Project,
    PushSubscription, Task, User, WeeklyPlan,
)
from ..security import get_current_user, rate_limit
from ..services import notifications as notif
from ..services import settings_store as st
from ..services.audit import audit

router = APIRouter(prefix="/api", tags=["system"])

SECTIONS = ("ai", "voice", "calendar", "planner", "notifications", "dashboard")
SECRET_FIELDS = {
    "ai": {"direct_api_key": "ai.direct_api_key"},
    "voice": {"stt_api_key": "voice.stt_api_key", "tts_api_key": "voice.tts_api_key"},
    "notifications": {"discord_webhook": "notifications.discord_webhook"},
}


# ----------------------------------------------------------------- Einstellungen
@router.get("/settings")
def get_settings_all(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = {s: st.get_section(db, s) for s in SECTIONS}
    for section, fields in SECRET_FIELDS.items():
        for field, key in fields.items():
            out[section][f"has_{field}"] = st.has_secret(db, key)
    return out


@router.put("/settings/{section}")
def put_settings(section: str, patch: dict, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if section not in SECTIONS:
        raise HTTPException(404, "Unbekannter Einstellungsbereich.")
    if len(json.dumps(patch)) > 20000:
        raise HTTPException(413, "Einstellungen zu groß.")
    for field, key in SECRET_FIELDS.get(section, {}).items():
        if field in patch:
            value = patch.pop(field)
            if value is not None and not isinstance(value, str):
                raise HTTPException(400, f"{field} muss Text sein.")
            if section == "notifications" and value and not value.startswith(("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")):
                raise HTTPException(400, "Bitte eine gültige Discord-Webhook-URL angeben.")
            st.set_secret(db, key, value or None)
    _validate(section, patch)
    result = st.update_section(db, section, patch)
    audit(db, "settings.update", f"Einstellungen „{section}“ geändert")
    return result


def _validate(section: str, p: dict) -> None:
    import re

    def hm(k):
        if k in p and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(p[k])):
            raise HTTPException(400, f"{k}: Uhrzeit im Format HH:MM erwartet.")

    if section == "planner":
        for k in ("time", "work_start", "work_end", "lunch_start", "lunch_end"):
            if k in p and p[k] in ("", None) and k.startswith("lunch"):
                continue
            hm(k)
        if "work_days" in p and (not isinstance(p["work_days"], list) or any(d not in range(7) for d in p["work_days"])):
            raise HTTPException(400, "Arbeitstage ungültig.")
        for k, lo, hi in (("buffer_minutes", 0, 120), ("max_focus_minutes_per_day", 30, 900), ("max_block_minutes", 15, 480), ("min_block_minutes", 10, 240), ("default_task_minutes", 5, 480), ("weekday", 0, 6)):
            if k in p and not (isinstance(p[k], int) and lo <= p[k] <= hi):
                raise HTTPException(400, f"{k} muss zwischen {lo} und {hi} liegen.")
        if "rules_text" in p and len(str(p["rules_text"])) > 3000:
            raise HTTPException(400, "Planungsregeln zu lang.")
    if section == "notifications":
        hm("daily_digest_time")
    if section == "ai" and "mode" in p and p["mode"] not in ("hermes", "direct", "off"):
        raise HTTPException(400, "Ungültiger KI-Modus.")
    if section == "voice":
        if "tts_rate" in p and not (0.5 <= float(p["tts_rate"]) <= 2.0):
            raise HTTPException(400, "Sprechgeschwindigkeit zwischen 0,5 und 2,0.")
        for k in ("stt_provider", "tts_provider"):
            if k in p and p[k] not in ("browser", "server"):
                raise HTTPException(400, "Ungültiger Sprachanbieter.")
    for k in ("direct_base_url", "stt_base_url", "tts_base_url"):
        if p.get(k) and not str(p[k]).startswith(("http://", "https://")):
            raise HTTPException(400, f"{k} muss mit http:// oder https:// beginnen.")


@router.post("/settings/ai/test")
def test_ai(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit("ai:test", 5, 60)
    try:
        text_ = agent.complete_text(db, "Antworte nur mit dem Wort OK.", "Test")
    except agent.AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"ok": True, "backend": agent.choose_backend(db), "answer": text_[:200]}


# ----------------------------------------------------------------- Benachrichtigungen
@router.get("/notifications")
def notifications(unread: bool = False, since_id: int = 0, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.id > since_id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.scalars(stmt.order_by(Notification.id.desc()).limit(100))
    unread_count = db.scalar(select(func.count()).select_from(Notification).where(Notification.read_at.is_(None)))
    return {"unread": unread_count, "items": [{"id": n.id, "type": n.type, "title": n.title, "body": n.body, "link": n.link, "created_at": n.created_at, "read": n.read_at is not None} for n in rows]}


@router.post("/notifications/read-all")
def read_all(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.read_at.is_(None)).update({Notification.read_at: datetime.now(timezone.utc)})
    db.commit()
    return {"ok": True}


@router.post("/notifications/{nid}/read")
def read_one(nid: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n:
        raise HTTPException(404, "Nicht gefunden.")
    n.read_at = n.read_at or datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


class TestNotifyIn(BaseModel):
    channel: str = Field(pattern="^(in_app|push|discord)$")


@router.post("/notifications/test")
def test_notification(data: TestNotifyIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit("notify:test", 5, 60)
    if data.channel == "discord":
        if not st.has_secret(db, "notifications.discord_webhook"):
            raise HTTPException(400, "Kein Discord-Webhook hinterlegt.")
        if not notif.send_discord(db, "MOSI PLAN – Test", "Die Discord-Benachrichtigung funktioniert."):
            raise HTTPException(502, "Discord hat die Nachricht nicht angenommen. Webhook-URL prüfen.")
        return {"ok": True}
    n = notif.Notification(type="ai_hint", title="Testbenachrichtigung", body="Benachrichtigungen funktionieren.", link="/", channels={})
    db.add(n)
    db.commit()
    if data.channel == "push":
        sent = notif._send_push(db, n)
        if not sent:
            raise HTTPException(400, "Kein Gerät für Push registriert oder Versand fehlgeschlagen.")
        return {"ok": True, "sent": sent}
    return {"ok": True}


@router.get("/push/vapid-key")
def vapid_key(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"public_key": notif.vapid_keys(db)[1]}


class PushSubIn(BaseModel):
    endpoint: str = Field(max_length=1024, pattern=r"^https://")
    keys: dict[str, str]
    user_agent: str = Field(default="", max_length=255)


@router.post("/push/subscribe")
def push_subscribe(data: PushSubIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not data.keys.get("p256dh") or not data.keys.get("auth"):
        raise HTTPException(400, "Unvollständiges Push-Abonnement.")
    sub = db.scalars(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)).first() or PushSubscription(endpoint=data.endpoint)
    sub.p256dh, sub.auth, sub.user_agent = data.keys["p256dh"], data.keys["auth"], data.user_agent
    db.add(sub)
    db.commit()
    return {"ok": True}


class PushUnsubIn(BaseModel):
    endpoint: str = Field(max_length=1024)


@router.post("/push/unsubscribe")
def push_unsubscribe(data: PushUnsubIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(PushSubscription).filter(PushSubscription.endpoint == data.endpoint).delete()
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------- Sprache (optional serverseitig)
@router.post("/voice/transcribe")
async def transcribe(file: UploadFile = File(...), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit("voice:stt", 30, 60)
    cfg = st.get_section(db, "voice")
    if not cfg["stt_enabled"]:
        raise HTTPException(400, "Spracheingabe ist deaktiviert.")
    if cfg["stt_provider"] != "server" or not cfg["stt_base_url"]:
        raise HTTPException(400, "Kein serverseitiger Spracherkennungsdienst konfiguriert.")
    limit = get_settings().max_upload_mb * 1024 * 1024
    audio = await file.read(limit + 1)
    if len(audio) > limit:
        raise HTTPException(413, f"Aufnahme zu groß (max. {get_settings().max_upload_mb} MB).")
    ctype = (file.content_type or "").split(";")[0]
    if not ctype.startswith("audio/") and ctype != "video/webm":
        raise HTTPException(400, "Nur Audiodateien sind erlaubt.")
    headers = {}
    key = st.get_secret(db, "voice.stt_api_key")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    ext = {"audio/webm": "webm", "video/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}.get(ctype, "webm")
    # Audio wird nur weitergereicht und nicht gespeichert.
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(cfg["stt_base_url"].rstrip("/") + "/audio/transcriptions", headers=headers,
                             files={"file": (f"aufnahme.{ext}", audio, ctype or "audio/webm")}, data={"model": cfg["stt_model"], "language": cfg.get("stt_language", "de")})
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Spracherkennungsdienst nicht erreichbar: {exc.__class__.__name__}") from exc
    if r.status_code != 200:
        raise HTTPException(502, f"Spracherkennung fehlgeschlagen ({r.status_code}).")
    return {"text": (r.json().get("text") or "").strip()}


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/voice/speak")
def speak(data: SpeakIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit("voice:tts", 30, 60)
    cfg = st.get_section(db, "voice")
    if cfg["tts_provider"] != "server" or not cfg["tts_base_url"]:
        raise HTTPException(400, "Kein serverseitiger Sprachausgabe-Dienst konfiguriert.")
    headers = {"Content-Type": "application/json"}
    key = st.get_secret(db, "voice.tts_api_key")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        r = httpx.post(cfg["tts_base_url"].rstrip("/") + "/audio/speech", headers=headers, timeout=60,
                       json={"model": cfg["tts_model"], "voice": cfg["tts_voice"], "input": data.text, "speed": float(cfg["tts_rate"]), "response_format": "mp3"})
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Sprachausgabe-Dienst nicht erreichbar: {exc.__class__.__name__}") from exc
    if r.status_code != 200:
        raise HTTPException(502, f"Sprachausgabe fehlgeschlagen ({r.status_code}).")
    return Response(r.content, media_type=r.headers.get("content-type", "audio/mpeg"), headers={"Cache-Control": "no-store"})


# ----------------------------------------------------------------- System
def _dir_size(path: str) -> int | None:
    total = 0
    try:
        for root, _dirs, files in os.walk(path, onerror=lambda e: None):
            for f in files:
                try:
                    total += os.lstat(os.path.join(root, f)).st_size
                except OSError:
                    pass
    except OSError:
        return None
    return total


def storage_report(db: Session) -> dict:
    s = get_settings()
    db_size = db.scalar(text("SELECT pg_database_size(current_database())")) or 0
    parts = {"database": int(db_size)}
    for name in ("uploads", "backups", "hermes", "logs"):
        p = os.path.join(s.data_dir, name)
        if os.path.isdir(p):
            parts[name] = _dir_size(p) or 0
    used = sum(parts.values())
    limit = int(s.storage_limit_gb * 1024**3)
    try:
        du = shutil.disk_usage(s.data_dir if os.path.isdir(s.data_dir) else "/")
        disk = {"total": du.total, "used": du.used, "free": du.free}
    except OSError:
        disk = None
    pct = round(100 * used / limit, 1) if limit else 0
    return {"parts": parts, "used": used, "limit": limit, "percent": pct, "level": "critical" if pct >= 90 else "warning" if pct >= 80 else "ok", "disk": disk}


@router.get("/system/status")
def system_status(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok, db_version = True, db.scalar(text("SHOW server_version"))
    except Exception as exc:  # noqa: BLE001
        db_ok, db_version = False, str(exc)
    ok, msg = agent.hermes_status(force=True)
    from ..jobs import job_status

    counts = {name: db.scalar(select(func.count()).select_from(m)) for name, m in (("projects", Project), ("tasks", Task), ("events", CalendarEvent), ("memory", MemoryEntry), ("weekly_plans", WeeklyPlan), ("conversations", Conversation))}
    return {
        "version": APP_VERSION,
        "database": {"ok": db_ok, "version": db_version},
        "hermes": {"ok": ok, "message": msg, "url": get_settings().hermes_url if get_settings().hermes_enabled else None},
        "storage": storage_report(db),
        "jobs": job_status(),
        "counts": counts,
        "public_url": get_settings().public_url,
        "secure_context_hint": get_settings().public_url.startswith("https://"),
        "server_time": datetime.now(timezone.utc),
    }


@router.get("/system/audit")
def audit_log(limit: int = 200, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.ts.desc()).limit(min(limit, 1000)))
    return [{"ts": r.ts, "actor": r.actor, "action": r.action, "summary": r.summary, "ip": r.ip} for r in rows]


@router.get("/system/export")
def export(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit("export", 5, 300)

    def rows(model, exclude=()):
        out = []
        for r in db.scalars(select(model)):
            out.append({c.name: getattr(r, c.name) for c in model.__table__.columns if c.name not in exclude})
        return out

    data = {
        "exported_at": datetime.now(timezone.utc), "version": APP_VERSION,
        "user": {"username": user.username, "display_name": user.display_name, "timezone": user.timezone},
        "projects": rows(Project), "tasks": rows(Task), "categories": rows(Category), "events": rows(CalendarEvent),
        "memory": rows(MemoryEntry), "weekly_plans": [{"id": p.id, "week_start": p.week_start, "status": p.status, "data": p.data,
                                                      "items": [{c.name: getattr(i, c.name) for c in i.__table__.columns} for i in p.items]} for p in db.scalars(select(WeeklyPlan))],
        "conversations": [{"id": c.id, "title": c.title, "messages": [{"role": m.role, "content": m.content, "created_at": m.created_at} for m in db.scalars(select(Message).where(Message.conversation_id == c.id).order_by(Message.id))]} for c in db.scalars(select(Conversation))],
    }
    audit(db, "system.export", "Datenexport heruntergeladen")
    body = json.dumps(data, ensure_ascii=False, default=str, indent=1)
    fname = f"mosi-plan-export-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return Response(body, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/system/backups")
def backups(_: User = Depends(get_current_user)):
    folder = os.path.join(get_settings().data_dir, "backups")
    if not os.path.isdir(folder):
        return []
    out = []
    for f in sorted(os.listdir(folder), reverse=True):
        p = os.path.join(folder, f)
        if os.path.isfile(p):
            out.append({"name": f, "size": os.path.getsize(p), "created_at": datetime.fromtimestamp(os.path.getmtime(p), timezone.utc)})
    return out[:50]


@router.post("/system/backups")
def create_backup(_: User = Depends(get_current_user)):
    """Erstellt ein Datenbank-Backup (pg_dump) im Backup-Verzeichnis."""
    rate_limit("backup", 3, 600)
    from ..jobs import run_db_backup

    try:
        name = run_db_backup()
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"ok": True, "name": name}
