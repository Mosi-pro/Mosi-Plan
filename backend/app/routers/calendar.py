from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CalendarEvent, GoogleCalendar, User
from ..schemas import EventIn, EventPatch
from ..security import get_current_user, rate_limit
from ..services import calendar as cal
from ..services import google_calendar as g
from ..services import settings_store as st

router = APIRouter(prefix="/api", tags=["calendar"])


def _parse(v: str) -> datetime:
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "Ungültiges Datum.") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/events")
def events(
    start: str,
    end: str,
    sources: str | None = Query(None, pattern=r"^(internal|google)(,(internal|google))?$"),
    categories: str | None = Query(None, pattern=r"^\d+(,\d+)*$"),
    calendars: str | None = Query(None, max_length=2000),
    q: str | None = Query(None, max_length=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s, e = _parse(start), _parse(end)
    if e <= s or (e - s).days > 400:
        raise HTTPException(400, "Zeitraum ungültig (maximal 400 Tage).")
    return cal.list_occurrences(
        db, s, e, user.timezone,
        sources=sources.split(",") if sources else None,
        category_ids=[int(x) for x in categories.split(",")] if categories else None,
        google_calendar_ids=calendars.split(",") if calendars else None,
        q=q,
    )


@router.post("/events", status_code=201)
def create_event(data: EventIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ev = g.create_remote_event(db, data, user.timezone) if data.target == "google" else cal.create_internal_event(db, data, user.timezone)
    conflicts = [] if ev.all_day else cal.find_conflicts(db, ev.start_at, ev.end_at, user.timezone, exclude_event_id=ev.id)
    return {"id": ev.id, "conflicts": conflicts}


@router.get("/events/{event_id}")
def get_event(event_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from zoneinfo import ZoneInfo

    ev = cal.get_event(db, event_id)
    return cal.serialize(ev, ev.start_at, ev.end_at, None, ZoneInfo(user.timezone), {"writable": True})


@router.patch("/events/{event_id}")
def update_event(event_id: int, data: EventPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ev = cal.get_event(db, event_id)
    if ev.source == "google":
        ev = g.update_remote_event(db, event_id, data, user.timezone)
    else:
        ev = cal.update_internal_event(db, event_id, data, user.timezone)
    conflicts = [] if ev.all_day else cal.find_conflicts(db, ev.start_at, ev.end_at, user.timezone, exclude_event_id=ev.id)
    return {"id": ev.id, "conflicts": conflicts}


@router.delete("/events/{event_id}")
def delete_event(event_id: int, occurrence: str | None = Query(None, max_length=40), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ev = cal.get_event(db, event_id)
    if ev.source == "google":
        g.delete_remote_event(db, event_id)
    else:
        cal.delete_internal_event(db, event_id, occurrence)
    return {"ok": True}


@router.get("/events-conflicts")
def conflicts(start: str, end: str, exclude: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return cal.find_conflicts(db, _parse(start), _parse(end), user.timezone, exclude)


# ----------------------------------------------------------------- Google
@router.get("/google/status")
def google_status(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = st.get_section(db, "google")
    cals = db.scalars(select(GoogleCalendar).order_by(GoogleCalendar.primary.desc(), GoogleCalendar.summary))
    return {
        "configured": g.is_configured(db),
        "connected": g.is_connected(db),
        "email": cfg.get("connected_email"),
        "last_sync_at": cfg.get("last_sync_at"),
        "last_error": cfg.get("last_error"),
        "redirect_uri": g.redirect_uri(),
        "client_id": cfg.get("client_id", ""),
        "has_client_secret": bool(st.get_secret(db, "google.client_secret")),
        "calendars": [
            {"google_id": c.google_id, "summary": c.summary, "color": c.color, "access_role": c.access_role, "primary": c.primary, "selected": c.selected,
             "last_synced_at": c.last_synced_at, "last_error": c.last_error,
             "event_count": db.query(CalendarEvent).filter(CalendarEvent.google_calendar_id == c.google_id).count()}
            for c in cals
        ],
    }


class GoogleCredentialsIn(BaseModel):
    client_id: str
    client_secret: str | None = None


@router.put("/google/credentials")
def google_credentials(data: GoogleCredentialsIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not data.client_id.strip().endswith(".apps.googleusercontent.com"):
        raise HTTPException(400, "Die Client-ID muss auf .apps.googleusercontent.com enden.")
    st.update_section(db, "google", {"client_id": data.client_id.strip()})
    if data.client_secret:
        st.set_secret(db, "google.client_secret", data.client_secret.strip())
    return {"ok": True}


@router.get("/google/auth-url")
def google_auth_url(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"url": g.build_auth_url(db)}


@router.get("/google/callback")
def google_callback(code: str | None = None, state: str | None = None, error: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if error or not code or not state:
        return RedirectResponse(f"/einstellungen/kalender?google=fehler&grund={error or 'abgebrochen'}", status_code=302)
    try:
        g.handle_callback(db, code, state)
        g.sync_events(db, user.timezone)
    except HTTPException as exc:
        from urllib.parse import quote

        return RedirectResponse(f"/einstellungen/kalender?google=fehler&grund={quote(str(exc.detail))}", status_code=302)
    except g.GoogleError as exc:
        from urllib.parse import quote

        return RedirectResponse(f"/einstellungen/kalender?google=fehler&grund={quote(str(exc))}", status_code=302)
    return RedirectResponse("/einstellungen/kalender?google=verbunden", status_code=302)


class CalendarSelectIn(BaseModel):
    selected: list[str]


@router.put("/google/calendars")
def google_select(data: CalendarSelectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for c in db.scalars(select(GoogleCalendar)):
        c.selected = c.google_id in data.selected
    db.commit()
    return {"ok": True}


@router.post("/google/sync")
def google_sync(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit("google:sync", 6, 60)
    if not g.is_connected(db):
        raise HTTPException(400, "Google Calendar ist nicht verbunden.")
    try:
        return g.full_sync(db, user.timezone)
    except g.GoogleError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/google/disconnect")
def google_disconnect(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g.disconnect(db)
    return {"ok": True}
