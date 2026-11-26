"""Zuverlässige interne Hintergrundjobs (ohne zusätzlichen Container).

Läuft als Thread im Backend. Ein PostgreSQL-Advisory-Lock stellt sicher, dass
auch bei mehreren Worker-Prozessen genau ein Scheduler aktiv ist.

Jobs:
* jede Minute: Erinnerungen (Termine, überfällige Aufgaben, Deadlines)
* alle N Minuten: Google-Calendar-Synchronisation
* wöchentlich (Standard: Sonntag 18:00 Europe/Berlin): Wochenplan-Entwurf
* täglich 02:30: Datenbank-Backup (pg_dump), Aufbewahrung 14 Stück
* täglich 03:30: Bereinigung + Speicherüberwachung (Warnung bei 80 % / 90 %)
"""
import hashlib
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, text

from .config import get_settings
from .db import SessionLocal, engine
from .models import AuditLog, Notification, PendingAction, UserSession, WeeklyPlan

log = logging.getLogger("mosi.jobs")

_state: dict[str, dict] = {}
_stop = threading.Event()
LOCK_ID = 7_310_442


def _mark(name: str, ok: bool, info: str = "") -> None:
    _state[name] = {"last_run": datetime.now(timezone.utc).isoformat(), "ok": ok, "info": info[:300]}


def job_status() -> dict:
    return dict(_state)


def _run(name: str, fn) -> None:
    db = SessionLocal()
    try:
        info = fn(db)
        _mark(name, True, str(info or ""))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("Job %s fehlgeschlagen", name)
        _mark(name, False, str(exc))
    finally:
        db.close()


def job_reminders(db) -> str:
    from .security import get_owner
    from .services.notifications import run_checks

    return f"{run_checks(db, get_owner(db))} neue Hinweise"


def job_google(db) -> str:
    from .security import get_owner
    from .services import google_calendar as g
    from .services import settings_store as st
    from .services.notifications import notify

    if not g.is_connected(db):
        return "nicht verbunden"
    cfg = st.get_section(db, "calendar")
    last = st.get_section(db, "google").get("last_sync_at")
    if last and datetime.now(timezone.utc) - datetime.fromisoformat(last) < timedelta(minutes=int(cfg.get("google_sync_minutes", 10))):
        return "übersprungen"
    user = get_owner(db)
    try:
        stats = g.full_sync(db, user.timezone)
    except g.GoogleError as exc:
        stats = {"errors": [str(exc)]}
    if stats.get("errors"):
        err = "; ".join(stats["errors"])
        day = datetime.now(timezone.utc).date().isoformat()
        notify(db, "sync_error", "Google-Synchronisation fehlgeschlagen", err[:500], "/einstellungen/kalender", f"sync:{day}:{hashlib.sha1(err.encode()).hexdigest()[:10]}")
        raise RuntimeError(err)
    return f"{stats.get('upserted', 0)} aktualisiert, {stats.get('removed', 0)} entfernt"


def job_weekly_plan(db) -> str:
    from .security import get_owner
    from .services import planner
    from .services import settings_store as st
    from .services.notifications import notify

    cfg = st.get_section(db, "planner")
    if not cfg.get("enabled"):
        return "deaktiviert"
    user = get_owner(db)
    now = datetime.now(ZoneInfo(user.timezone))
    if now.weekday() != int(cfg["weekday"]) or now.strftime("%H:%M") < cfg["time"]:
        return "nicht fällig"
    target = planner.week_start_of(now.date()) + timedelta(days=7)
    exists = db.scalars(select(WeeklyPlan).where(WeeklyPlan.week_start == target, WeeklyPlan.generated_by == "schedule")).first()
    if exists:
        return "bereits erstellt"
    plan = planner.generate_plan(db, user, target, generated_by="schedule")
    notify(db, "weekly_plan", f"Dein Wochenplan für KW {target.isocalendar().week} ist bereit",
           f"{len(plan.items)} Arbeitsblöcke geplant. Bitte prüfen und freigeben.", "/wochenplan", f"weekly:{target.isoformat()}")
    return f"Plan {plan.id} erstellt"


def run_db_backup() -> str:
    s = get_settings()
    folder = os.path.join(s.data_dir, "backups")
    os.makedirs(folder, exist_ok=True)
    name = f"mosi-db-{datetime.now().strftime('%Y%m%d-%H%M%S')}.dump"
    path = os.path.join(folder, name)
    url = s.database_url.replace("postgresql+psycopg://", "postgresql://")
    try:
        r = subprocess.run(["pg_dump", "--format=custom", "--no-owner", f"--file={path}", f"--dbname={url}"], capture_output=True, text=True, timeout=600)
    except FileNotFoundError as exc:
        raise RuntimeError("pg_dump ist nicht installiert.") from exc
    if r.returncode != 0:
        if os.path.exists(path):
            os.remove(path)
        raise RuntimeError("Backup fehlgeschlagen: " + r.stderr.strip()[:300].replace(url, "***"))
    dumps = sorted(f for f in os.listdir(folder) if f.startswith("mosi-db-") and f.endswith(".dump"))
    for old in dumps[:-14]:
        os.remove(os.path.join(folder, old))
    return name


def job_backup(db) -> str:
    return run_db_backup()


def job_cleanup(db) -> str:
    from .routers.system import storage_report
    from .services.notifications import notify

    now = datetime.now(timezone.utc)
    db.execute(delete(Notification).where(Notification.created_at < now - timedelta(days=90)))
    db.execute(delete(AuditLog).where(AuditLog.ts < now - timedelta(days=365)))
    db.execute(delete(UserSession).where(UserSession.expires_at < now))
    db.query(PendingAction).filter(PendingAction.status == "pending", PendingAction.created_at < now - timedelta(hours=24)).update({PendingAction.status: "expired"})
    db.commit()
    # Nur das eigene temporäre Verzeichnis bereinigen – niemals das System-/tmp
    tmp = os.path.join(get_settings().data_dir, "tmp")
    removed = 0
    if os.path.isdir(tmp):
        for f in os.listdir(tmp):
            p = os.path.join(tmp, f)
            try:
                if os.path.isfile(p) and time.time() - os.path.getmtime(p) > 86400:
                    os.remove(p)
                    removed += 1
            except OSError:
                pass
    rep = storage_report(db)
    if rep["level"] != "ok":
        notify(db, "sync_error", f"Speicherwarnung: {rep['percent']} % des Limits belegt",
               f"MOSI PLAN belegt {round(rep['used'] / 1024**3, 1)} GB von {round(rep['limit'] / 1024**3)} GB. Bitte Backups/Logs prüfen.",
               "/einstellungen/system", f"storage:{rep['level']}:{now.date().isoformat()}")
    return f"Speicher {rep['percent']} %, {removed} temporäre Dateien entfernt"


def _loop() -> None:
    last: dict[str, float] = {}
    daily_done: dict[str, str] = {}
    while not _stop.is_set():
        now = time.time()
        local = datetime.now(ZoneInfo("Europe/Berlin"))
        today = local.date().isoformat()
        if now - last.get("reminders", 0) >= 60:
            last["reminders"] = now
            _run("Erinnerungen", job_reminders)
            _run("Wochenplan", job_weekly_plan)
        if now - last.get("google", 0) >= 60:
            last["google"] = now
            _run("Google-Sync", job_google)
        if local.strftime("%H:%M") >= "02:30" and daily_done.get("backup") != today:
            daily_done["backup"] = today
            _run("Backup", job_backup)
        if local.strftime("%H:%M") >= "03:30" and daily_done.get("cleanup") != today:
            daily_done["cleanup"] = today
            _run("Bereinigung", job_cleanup)
        _stop.wait(15)


def start_scheduler() -> None:
    if get_settings().disable_jobs:
        return

    def runner():
        # Nur ein Prozess erhält den Lock (gehalten, solange die Verbindung offen ist).
        while not _stop.is_set():
            conn = None
            try:
                conn = engine.connect()
                if conn.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}).scalar():
                    log.info("Scheduler aktiv")
                    _loop()
                    return
            except Exception:  # noqa: BLE001
                log.exception("Scheduler-Lock fehlgeschlagen")
            finally:
                if conn is not None and _stop.is_set():
                    conn.close()
            if conn is not None:
                conn.close()
            _stop.wait(60)

    threading.Thread(target=runner, name="mosi-scheduler", daemon=True).start()


def stop_scheduler() -> None:
    _stop.set()
