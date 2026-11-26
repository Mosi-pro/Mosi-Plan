"""Google-Calendar-Integration (OAuth 2.0 Web-Server-Flow + Calendar API v3).

Synchronisationsregeln (siehe docs/GOOGLE_CALENDAR.md):
* Google-Termine werden als Spiegel (source='google') mit eindeutiger
  Kombination (google_calendar_id, external_id) gespeichert -> keine Duplikate.
* Google ist für Google-Termine die führende Quelle. Ein Sync überschreibt den
  Spiegel; in Google gelöschte/abgesagte Termine werden lokal entfernt.
* Wiederholungen werden über singleEvents=true als Einzelinstanzen geladen.
* Schreibzugriffe nach Google erfolgen nur auf ausdrückliche Benutzeraktion
  und mit If-Match/ETag -> wurde der Termin in Google zwischenzeitlich geändert,
  wird ein Konflikt gemeldet statt still zu überschreiben.
* Interne Termine werden niemals automatisch nach Google kopiert.
"""
import logging
import secrets
import time as _time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import CalendarEvent, GoogleCalendar
from ..schemas import EventIn, EventPatch
from . import settings_store as st
from .audit import audit
from .calendar import _resolve_times, get_event, local_midnight

log = logging.getLogger("mosi.google")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar"
SYNC_PAST_DAYS = 60
SYNC_FUTURE_DAYS = 400

# In Tests durch httpx.MockTransport ersetzbar
TRANSPORT: httpx.BaseTransport | None = None


class GoogleError(Exception):
    pass


def _client() -> httpx.Client:
    return httpx.Client(timeout=20, transport=TRANSPORT)


def redirect_uri() -> str:
    return get_settings().public_url.rstrip("/") + "/api/google/callback"


def credentials(db: Session) -> tuple[str, str]:
    cfg = st.get_section(db, "google")
    return cfg.get("client_id", ""), st.get_secret(db, "google.client_secret")


def is_configured(db: Session) -> bool:
    cid, secret = credentials(db)
    return bool(cid and secret)


def get_tokens(db: Session) -> dict | None:
    import json

    raw = st.get_secret(db, "google.tokens")
    return json.loads(raw) if raw else None


def _save_tokens(db: Session, tokens: dict | None) -> None:
    import json

    st.set_secret(db, "google.tokens", json.dumps(tokens) if tokens else None)


def is_connected(db: Session) -> bool:
    t = get_tokens(db)
    return bool(t and t.get("refresh_token"))


def build_auth_url(db: Session) -> str:
    cid, secret = credentials(db)
    if not cid or not secret:
        raise HTTPException(400, "Google OAuth ist nicht eingerichtet. Bitte Client-ID und Client-Secret in den Einstellungen eintragen.")
    state = secrets.token_urlsafe(24)
    st.set_raw(db, "google_oauth_state", {"state": state, "ts": _time.time()})
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def handle_callback(db: Session, code: str, state: str) -> None:
    saved = st.get_raw(db, "google_oauth_state") or {}
    if not saved or not secrets.compare_digest(saved.get("state", ""), state) or _time.time() - saved.get("ts", 0) > 900:
        raise HTTPException(400, "Ungültiger oder abgelaufener OAuth-Status. Bitte Verbindung erneut starten.")
    st.set_raw(db, "google_oauth_state", None)
    cid, secret = credentials(db)
    with _client() as c:
        r = c.post(TOKEN_URL, data={"code": code, "client_id": cid, "client_secret": secret, "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise HTTPException(400, f"Google hat den Code abgelehnt: {r.text[:300]}")
    data = r.json()
    if not data.get("refresh_token"):
        raise HTTPException(400, "Google hat kein Refresh-Token geliefert. Bitte den Zugriff unter myaccount.google.com/permissions entfernen und erneut verbinden.")
    _save_tokens(db, {"access_token": data["access_token"], "refresh_token": data["refresh_token"], "expires_at": _time.time() + int(data.get("expires_in", 3600)) - 60})
    st.update_section(db, "google", {"last_error": None})
    audit(db, "google.connect", "Google Calendar verbunden")
    sync_calendar_list(db)


def disconnect(db: Session) -> None:
    tokens = get_tokens(db)
    if tokens:
        try:
            with _client() as c:
                c.post(REVOKE_URL, params={"token": tokens.get("refresh_token")})
        except httpx.HTTPError:
            pass
    _save_tokens(db, None)
    db.execute(delete(CalendarEvent).where(CalendarEvent.source == "google"))
    db.execute(delete(GoogleCalendar))
    st.update_section(db, "google", {"connected_email": "", "last_sync_at": None, "last_error": None})
    audit(db, "google.disconnect", "Google Calendar getrennt; gespiegelte Termine lokal entfernt")


def _access_token(db: Session) -> str:
    tokens = get_tokens(db)
    if not tokens:
        raise GoogleError("Google Calendar ist nicht verbunden.")
    if tokens.get("expires_at", 0) > _time.time():
        return tokens["access_token"]
    cid, secret = credentials(db)
    with _client() as c:
        r = c.post(TOKEN_URL, data={"client_id": cid, "client_secret": secret, "refresh_token": tokens["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code != 200:
        err = r.json().get("error", "") if r.headers.get("content-type", "").startswith("application/json") else r.text[:100]
        if err == "invalid_grant":
            msg = "Die Google-Verbindung ist abgelaufen oder wurde widerrufen. Bitte in den Einstellungen neu verbinden."
        else:
            msg = f"Token-Erneuerung bei Google fehlgeschlagen ({err})."
        st.update_section(db, "google", {"last_error": msg})
        raise GoogleError(msg)
    data = r.json()
    tokens.update(access_token=data["access_token"], expires_at=_time.time() + int(data.get("expires_in", 3600)) - 60)
    _save_tokens(db, tokens)
    return tokens["access_token"]


def _request(db: Session, method: str, path: str, **kw) -> httpx.Response:
    headers = kw.pop("headers", {})
    headers["Authorization"] = f"Bearer {_access_token(db)}"
    with _client() as c:
        try:
            r = c.request(method, API + path, headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise GoogleError(f"Google ist nicht erreichbar: {exc}") from exc
    if r.status_code == 401:
        raise GoogleError("Google hat den Zugriff verweigert (401). Bitte neu verbinden.")
    return r


# ----------------------------------------------------------------- Kalenderliste
def sync_calendar_list(db: Session) -> list[GoogleCalendar]:
    r = _request(db, "GET", "/users/me/calendarList", params={"maxResults": 250})
    if r.status_code != 200:
        raise GoogleError(f"Kalenderliste konnte nicht geladen werden ({r.status_code}).")
    items = r.json().get("items", [])
    existing = {c.google_id: c for c in db.scalars(select(GoogleCalendar))}
    seen = set()
    for it in items:
        gid = it["id"]
        seen.add(gid)
        cal = existing.get(gid) or GoogleCalendar(google_id=gid, selected=bool(it.get("primary")))
        cal.summary = it.get("summaryOverride") or it.get("summary", gid)
        cal.color = it.get("backgroundColor", "#4C8DF6")
        cal.access_role = it.get("accessRole", "reader")
        cal.primary = bool(it.get("primary"))
        db.add(cal)
        if cal.primary:
            st.update_section(db, "google", {"connected_email": gid})
    for gid, cal in existing.items():
        if gid not in seen:
            db.execute(delete(CalendarEvent).where(CalendarEvent.source == "google", CalendarEvent.google_calendar_id == gid))
            db.delete(cal)
    db.commit()
    return list(db.scalars(select(GoogleCalendar).order_by(GoogleCalendar.primary.desc(), GoogleCalendar.summary)))


# ----------------------------------------------------------------- Mapping
def _parse_time(obj: dict, tz: ZoneInfo) -> tuple[datetime, bool]:
    if "dateTime" in obj:
        return datetime.fromisoformat(obj["dateTime"].replace("Z", "+00:00")).astimezone(timezone.utc), False
    return local_midnight(date.fromisoformat(obj["date"]), tz), True


def _apply_remote(ev: CalendarEvent, item: dict, tz: ZoneInfo, tz_name: str) -> None:
    ev.title = (item.get("summary") or "(ohne Titel)")[:300]
    ev.notes = item.get("description", "") or ""
    ev.location = (item.get("location", "") or "")[:300]
    ev.start_at, ev.all_day = _parse_time(item["start"], tz)
    ev.end_at, _ = _parse_time(item["end"], tz)
    ev.timezone = item["start"].get("timeZone", tz_name)
    ev.busy = item.get("transparency", "opaque") != "transparent"
    ev.etag = item.get("etag")
    ev.recurring_event_id = item.get("recurringEventId")
    ev.sync_state = "synced"
    ev.deleted = False


def _to_remote(title: str, notes: str, location: str, start: datetime, end: datetime, all_day: bool, tz: ZoneInfo, tz_name: str) -> dict:
    body: dict = {"summary": title, "description": notes, "location": location}
    if all_day:
        body["start"] = {"date": start.astimezone(tz).date().isoformat()}
        body["end"] = {"date": end.astimezone(tz).date().isoformat()}
    else:
        body["start"] = {"dateTime": start.astimezone(tz).isoformat(), "timeZone": tz_name}
        body["end"] = {"dateTime": end.astimezone(tz).isoformat(), "timeZone": tz_name}
    return body


# ----------------------------------------------------------------- Event-Sync
def sync_events(db: Session, tz_name: str) -> dict:
    tz = ZoneInfo(tz_name)
    now = datetime.now(timezone.utc)
    t_min, t_max = now - timedelta(days=SYNC_PAST_DAYS), now + timedelta(days=SYNC_FUTURE_DAYS)
    stats = {"calendars": 0, "upserted": 0, "removed": 0, "errors": []}
    for cal in db.scalars(select(GoogleCalendar).where(GoogleCalendar.selected.is_(True))).all():
        try:
            remote: dict[str, dict] = {}
            page = None
            while True:
                params = {"singleEvents": "true", "timeMin": t_min.isoformat(), "timeMax": t_max.isoformat(), "maxResults": 2500, "showDeleted": "false"}
                if page:
                    params["pageToken"] = page
                r = _request(db, "GET", f"/calendars/{quote(cal.google_id, safe='')}/events", params=params)
                if r.status_code != 200:
                    raise GoogleError(f"Termine konnten nicht geladen werden ({r.status_code}).")
                data = r.json()
                for it in data.get("items", []):
                    if it.get("status") != "cancelled" and "start" in it:
                        remote[it["id"]] = it
                page = data.get("nextPageToken")
                if not page:
                    break
            local = {
                e.external_id: e
                for e in db.scalars(
                    select(CalendarEvent).where(CalendarEvent.source == "google", CalendarEvent.google_calendar_id == cal.google_id)
                )
            }
            for gid, item in remote.items():
                ev = local.get(gid)
                if ev is None:
                    ev = CalendarEvent(source="google", google_calendar_id=cal.google_id, external_id=gid, title="", origin="google")
                    db.add(ev)
                if ev.etag != item.get("etag") or ev.deleted:
                    _apply_remote(ev, item, tz, tz_name)
                    stats["upserted"] += 1
            for gid, ev in local.items():
                # Nur innerhalb des Sync-Fensters entfernen, was Google nicht mehr liefert
                if gid not in remote and ev.end_at > t_min and ev.start_at < t_max:
                    db.delete(ev)
                    stats["removed"] += 1
            cal.last_synced_at = now
            cal.last_error = None
            stats["calendars"] += 1
            db.commit()
        except GoogleError as exc:
            db.rollback()
            cal.last_error = str(exc)
            db.commit()
            stats["errors"].append(f"{cal.summary}: {exc}")
    st.update_section(db, "google", {"last_sync_at": now.isoformat(), "last_error": "; ".join(stats["errors"]) or None})
    return stats


def full_sync(db: Session, tz_name: str) -> dict:
    sync_calendar_list(db)
    return sync_events(db, tz_name)


# ----------------------------------------------------------------- Schreiben (nur explizit)
def _writable_calendar(db: Session, cal_id: str | None) -> GoogleCalendar:
    cal_id = cal_id or st.get_section(db, "calendar").get("google_write_calendar_id") or None
    stmt = select(GoogleCalendar)
    cal = db.scalars(stmt.where(GoogleCalendar.google_id == cal_id)).first() if cal_id else db.scalars(stmt.where(GoogleCalendar.primary.is_(True))).first()
    if not cal:
        raise HTTPException(400, "Kein Google-Kalender zum Schreiben ausgewählt.")
    if cal.access_role not in ("owner", "writer"):
        raise HTTPException(403, f"Keine Schreibberechtigung für Google-Kalender „{cal.summary}“.")
    return cal


def create_remote_event(db: Session, data: EventIn, tz_name: str, actor: str = "user") -> CalendarEvent:
    if data.rrule:
        raise HTTPException(400, "Wiederkehrende Termine bitte direkt in Google anlegen oder im internen Kalender erstellen.")
    tz = ZoneInfo(tz_name)
    cal = _writable_calendar(db, data.google_calendar_id)
    start, end, all_day = _resolve_times(data, None, tz)
    body = _to_remote(data.title, data.notes, data.location, start, end, all_day, tz, tz_name)
    try:
        r = _request(db, "POST", f"/calendars/{quote(cal.google_id, safe='')}/events", json=body)
    except GoogleError as exc:
        raise HTTPException(502, str(exc)) from exc
    if r.status_code not in (200, 201):
        raise HTTPException(502, f"Google hat den Termin nicht angelegt ({r.status_code}): {r.text[:200]}")
    item = r.json()
    ev = CalendarEvent(source="google", google_calendar_id=cal.google_id, external_id=item["id"], title="", origin="assistant" if actor == "assistant" else "user", task_id=data.task_id, project_id=data.project_id)
    _apply_remote(ev, item, tz, tz_name)
    db.add(ev)
    db.flush()
    audit(db, "google.event.create", f"Google-Termin „{ev.title}“ in „{cal.summary}“ erstellt", actor=actor, entity_type="event", entity_id=ev.id, commit=False)
    db.commit()
    return ev


def update_remote_event(db: Session, event_id: int, patch: EventPatch, tz_name: str, actor: str = "user") -> CalendarEvent:
    ev = get_event(db, event_id)
    if ev.source != "google":
        raise HTTPException(400, "Kein Google-Termin.")
    cal = _writable_calendar(db, ev.google_calendar_id)
    tz = ZoneInfo(ev.timezone or tz_name)
    changes = patch.model_dump(exclude_unset=True)
    start, end, all_day = ev.start_at, ev.end_at, ev.all_day
    if any(k in changes for k in ("start", "end", "all_day", "start_date", "end_date")):
        start, end, all_day = _resolve_times(patch, ev, tz)
    body = _to_remote(changes.get("title", ev.title), changes.get("notes", ev.notes), changes.get("location", ev.location), start, end, all_day, tz, ev.timezone or tz_name)
    headers = {"If-Match": ev.etag} if ev.etag else {}
    try:
        r = _request(db, "PATCH", f"/calendars/{quote(cal.google_id, safe='')}/events/{quote(ev.external_id or '', safe='')}", json=body, headers=headers)
    except GoogleError as exc:
        raise HTTPException(502, str(exc)) from exc
    if r.status_code == 412:
        ev.sync_state = "conflict"
        db.commit()
        raise HTTPException(409, "Konflikt: Der Termin wurde zwischenzeitlich in Google geändert. Bitte zuerst synchronisieren.")
    if r.status_code != 200:
        raise HTTPException(502, f"Google hat die Änderung abgelehnt ({r.status_code}).")
    _apply_remote(ev, r.json(), tz, tz_name)
    for k in ("task_id", "project_id"):
        if k in changes:
            setattr(ev, k, changes[k])
    audit(db, "google.event.update", f"Google-Termin „{ev.title}“ geändert", actor=actor, entity_type="event", entity_id=ev.id, commit=False)
    db.commit()
    return ev


def delete_remote_event(db: Session, event_id: int, actor: str = "user") -> None:
    ev = get_event(db, event_id)
    if ev.source != "google":
        raise HTTPException(400, "Kein Google-Termin.")
    cal = _writable_calendar(db, ev.google_calendar_id)
    headers = {"If-Match": ev.etag} if ev.etag else {}
    try:
        r = _request(db, "DELETE", f"/calendars/{quote(cal.google_id, safe='')}/events/{quote(ev.external_id or '', safe='')}", headers=headers)
    except GoogleError as exc:
        raise HTTPException(502, str(exc)) from exc
    if r.status_code == 412:
        raise HTTPException(409, "Konflikt: Der Termin wurde zwischenzeitlich in Google geändert. Bitte zuerst synchronisieren.")
    if r.status_code not in (200, 204, 404, 410):
        raise HTTPException(502, f"Google hat das Löschen abgelehnt ({r.status_code}).")
    title = ev.title
    db.delete(ev)
    audit(db, "google.event.delete", f"Google-Termin „{title}“ gelöscht", actor=actor, entity_type="event", entity_id=event_id, commit=False)
    db.commit()
