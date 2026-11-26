"""Benachrichtigungen: In-App, Browser (über Polling), Web-Push (VAPID) und Discord."""
import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Notification, Project, PushSubscription, Task, User
from ..security import decrypt_secret, encrypt_secret
from . import settings_store as st
from .calendar import list_occurrences
from .overview import fmt_date

log = logging.getLogger("mosi.notify")

TYPE_LABEL = {
    "event_upcoming": "Anstehende Termine",
    "task_overdue": "Überfällige Aufgaben",
    "project_deadline": "Projektdeadlines",
    "weekly_plan": "Neuer Wochenplan",
    "ai_hint": "Wichtige KI-Hinweise",
    "sync_error": "Synchronisationsfehler",
}


# ----------------------------------------------------------------- VAPID
def vapid_keys(db: Session) -> tuple[str, str]:
    """Liefert (private_pem, public_key_b64url); erzeugt sie beim ersten Aufruf."""
    raw = st.get_raw(db, "vapid")
    if raw:
        return decrypt_secret(raw["private"]), raw["public"]
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    pub_b64 = base64.urlsafe_b64encode(pub).decode().rstrip("=")
    st.set_raw(db, "vapid", {"private": encrypt_secret(priv), "public": pub_b64})
    return priv, pub_b64


def _send_push(db: Session, n: Notification) -> int:
    subs = list(db.scalars(select(PushSubscription)))
    if not subs:
        return 0
    from pywebpush import WebPushException, webpush

    priv, _ = vapid_keys(db)
    sent = 0
    payload = json.dumps({"title": n.title, "body": n.body, "link": n.link or "/", "tag": n.type})
    for s in subs:
        try:
            webpush(
                subscription_info={"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                data=payload,
                vapid_private_key=priv,
                vapid_claims={"sub": "mailto:admin@" + (get_settings().public_url.split("//")[-1].split("/")[0].split(":")[0] or "localhost")},
                ttl=3600,
                timeout=10,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                db.delete(s)
            log.warning("Push fehlgeschlagen: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("Push fehlgeschlagen: %s", exc)
    db.commit()
    return sent


def send_discord(db: Session, title: str, body: str, link: str = "") -> bool:
    url = st.get_secret(db, "notifications.discord_webhook")
    if not url:
        return False
    full_link = get_settings().public_url.rstrip("/") + link if link.startswith("/") else link
    content = f"**{title}**\n{body}" + (f"\n{full_link}" if full_link else "")
    try:
        r = httpx.post(url, json={"content": content[:1900], "username": "MOSI PLAN", "allowed_mentions": {"parse": []}}, timeout=10)
        return r.status_code in (200, 204)
    except httpx.HTTPError as exc:
        log.warning("Discord fehlgeschlagen: %s", exc)
        return False


def notify(db: Session, type_: str, title: str, body: str = "", link: str = "", dedupe_key: str | None = None) -> Notification | None:
    cfg = st.get_section(db, "notifications")
    if not cfg["types"].get(type_, True):
        return None
    if dedupe_key and db.scalars(select(Notification).where(Notification.dedupe_key == dedupe_key)).first():
        return None
    n = Notification(type=type_, title=title[:200], body=body, link=link, dedupe_key=dedupe_key, channels={})
    db.add(n)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    channels = {"in_app": True}
    if cfg.get("push"):
        channels["push"] = _send_push(db, n)
    if cfg.get("discord"):
        channels["discord"] = send_discord(db, title, body, link)
    n.channels = channels
    db.commit()
    return n


# ----------------------------------------------------------------- Prüfungen (Job, minütlich)
def run_checks(db: Session, user: User, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(user.timezone)
    cfg = st.get_section(db, "notifications")
    count = 0
    default_min = int(cfg.get("event_reminder_minutes", 15))
    for o in list_occurrences(db, now, now + timedelta(hours=26), user.timezone):
        if o["all_day"]:
            continue
        start = datetime.fromisoformat(o["start"])
        mins = o["reminders"] or ([default_min] if default_min else [])
        for m in mins:
            if start - timedelta(minutes=m) <= now < start:
                when = start.astimezone(tz).strftime("%H:%M")
                body = f"Beginnt um {when} Uhr" + (f" · {o['location']}" if o["location"] else "")
                if notify(db, "event_upcoming", o["title"], body, f"/kalender?datum={start.astimezone(tz).date().isoformat()}", f"event:{o['id']}:{o['start']}:{m}"):
                    count += 1
    local = now.astimezone(tz)
    today = local.date()
    if local.strftime("%H:%M") >= cfg.get("daily_digest_time", "07:30"):
        overdue = list(db.scalars(select(Task).where(Task.status.in_(("open", "in_progress", "waiting")), Task.due_date < today)))
        if overdue:
            names = ", ".join(f"„{t.title}“" for t in overdue[:3]) + (" …" if len(overdue) > 3 else "")
            if notify(db, "task_overdue", f"{len(overdue)} überfällige Aufgabe(n)", names, "/aufgaben?filter=ueberfaellig", f"overdue:{today.isoformat()}"):
                count += 1
        days = int(cfg.get("deadline_days_before", 2))
        for p in db.scalars(select(Project).where(Project.status.in_(("active", "planned")), Project.deadline.is_not(None))):
            if today <= p.deadline <= today + timedelta(days=days):
                if notify(db, "project_deadline", f"Deadline {p.name}", f"Fällig {fmt_date(p.deadline, today)}", f"/projekte/{p.id}", f"deadline:project:{p.id}:{p.deadline.isoformat()}"):
                    count += 1
        for t in db.scalars(select(Task).where(Task.status.in_(("open", "in_progress")), Task.priority.in_(("high", "critical")), Task.due_date.is_not(None))):
            if today <= t.due_date <= today + timedelta(days=days):
                if notify(db, "project_deadline", f"Wichtige Aufgabe fällig: {t.title}", f"Fällig {fmt_date(t.due_date, today)}", "/aufgaben", f"deadline:task:{t.id}:{t.due_date.isoformat()}"):
                    count += 1
    return count
