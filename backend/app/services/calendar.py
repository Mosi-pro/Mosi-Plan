"""Interner MOSI-Kalender + vereinheitlichte Abfrage über alle Quellen.

Regeln:
* Zeiten werden in UTC gespeichert; Wiederholungen werden in der Zeitzone des
  Termins expandiert, damit Sommer-/Winterzeit korrekt bleibt (09:00 bleibt 09:00).
* Ganztägige Termine: start_at = lokale Mitternacht des ersten Tages,
  end_at = lokale Mitternacht nach dem letzten Tag (exklusiv).
* Google-Termine sind gespiegelte Kopien (source='google') und werden nur über
  das Google-Modul verändert.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import CalendarEvent, Category, GoogleCalendar, Project, Task
from ..schemas import EventIn, EventPatch
from .audit import audit

ALLOWED_FREQ = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
MAX_OCCURRENCES = 1500


def local_midnight(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time(0, 0), tzinfo=tz).astimezone(timezone.utc)


def validate_rrule(rule: str | None) -> str | None:
    if not rule:
        return None
    rule = rule.strip()
    if rule.upper().startswith("RRULE:"):
        rule = rule[6:]
    upper = rule.upper()
    if "DTSTART" in upper or "\n" in rule:
        raise HTTPException(400, "Ungültige Wiederholungsregel.")
    if not any(f"FREQ={f}" in upper for f in ALLOWED_FREQ):
        raise HTTPException(400, "Wiederholung muss täglich, wöchentlich, monatlich oder jährlich sein.")
    try:
        rrulestr(rule, dtstart=datetime(2026, 1, 1))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Ungültige Wiederholungsregel: {exc}") from exc
    return rule


def _resolve_times(data: EventIn | EventPatch, ev: CalendarEvent | None, tz: ZoneInfo) -> tuple[datetime, datetime, bool]:
    all_day = data.all_day if data.all_day is not None else (ev.all_day if ev else False)
    if all_day:
        sd = data.start_date or (data.start.astimezone(tz).date() if data.start else None)
        if sd is None and ev:
            sd = ev.start_at.astimezone(tz).date()
        if sd is None:
            raise HTTPException(400, "Für ganztägige Termine wird ein Startdatum benötigt.")
        ed = data.end_date or (ev.end_at.astimezone(tz).date() - timedelta(days=1) if ev and not data.start_date else sd)
        if ed < sd:
            raise HTTPException(400, "Das Enddatum liegt vor dem Startdatum.")
        return local_midnight(sd, tz), local_midnight(ed + timedelta(days=1), tz), True
    start = data.start or (ev.start_at if ev else None)
    end = data.end or (ev.end_at if ev and not data.start else None)
    if start is None:
        raise HTTPException(400, "Für Termine wird eine Startzeit benötigt.")
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end is None:
        dur = (ev.end_at - ev.start_at) if ev else timedelta(hours=1)
        end = start + dur
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    if end <= start:
        raise HTTPException(400, "Das Terminende muss nach dem Beginn liegen.")
    if end - start > timedelta(days=60):
        raise HTTPException(400, "Termine dürfen höchstens 60 Tage dauern.")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc), False


def _check_refs(db: Session, category_id: int | None, task_id: int | None, project_id: int | None) -> None:
    if category_id is not None and not db.get(Category, category_id):
        raise HTTPException(400, "Kategorie existiert nicht.")
    if task_id is not None and not db.get(Task, task_id):
        raise HTTPException(400, "Verknüpfte Aufgabe existiert nicht.")
    if project_id is not None and not db.get(Project, project_id):
        raise HTTPException(400, "Verknüpftes Projekt existiert nicht.")


def create_internal_event(db: Session, data: EventIn, tz_name: str, actor: str = "user", origin: str | None = None, commit: bool = True) -> CalendarEvent:
    tz = ZoneInfo(tz_name)
    start, end, all_day = _resolve_times(data, None, tz)
    _check_refs(db, data.category_id, data.task_id, data.project_id)
    ev = CalendarEvent(
        source="internal",
        title=data.title.strip(),
        notes=data.notes,
        location=data.location,
        start_at=start,
        end_at=end,
        all_day=all_day,
        timezone=tz_name,
        busy=data.busy if data.busy is not None else not all_day,
        rrule=validate_rrule(data.rrule),
        category_id=data.category_id,
        reminders=sorted({int(m) for m in data.reminders if 0 <= int(m) <= 40320}),
        task_id=data.task_id,
        project_id=data.project_id,
        origin=origin or ("assistant" if actor == "assistant" else "user"),
    )
    db.add(ev)
    db.flush()
    audit(db, "event.create", f"Termin „{ev.title}“ erstellt", actor=actor, entity_type="event", entity_id=ev.id, project_id=ev.project_id, commit=False)
    if commit:
        db.commit()
    return ev


def get_event(db: Session, event_id: int) -> CalendarEvent:
    ev = db.get(CalendarEvent, event_id)
    if not ev or ev.deleted:
        raise HTTPException(404, f"Termin {event_id} nicht gefunden.")
    return ev


def apply_patch(db: Session, ev: CalendarEvent, patch: EventPatch, tz_name: str) -> dict:
    tz = ZoneInfo(ev.timezone or tz_name)
    changes = patch.model_dump(exclude_unset=True)
    if any(k in changes for k in ("start", "end", "all_day", "start_date", "end_date")):
        ev.start_at, ev.end_at, ev.all_day = _resolve_times(patch, ev, tz)
        if "busy" not in changes and "all_day" in changes:
            ev.busy = not ev.all_day
    _check_refs(db, changes.get("category_id"), changes.get("task_id"), changes.get("project_id"))
    for k in ("title", "notes", "location", "category_id", "task_id", "project_id", "busy"):
        if k in changes:
            setattr(ev, k, changes[k])
    if "rrule" in changes:
        ev.rrule = validate_rrule(changes["rrule"])
        ev.exdates = []
    if "reminders" in changes:
        ev.reminders = sorted({int(m) for m in changes["reminders"] if 0 <= int(m) <= 40320})
    return changes


def update_internal_event(db: Session, event_id: int, patch: EventPatch, tz_name: str, actor: str = "user") -> CalendarEvent:
    ev = get_event(db, event_id)
    if ev.source != "internal":
        raise HTTPException(400, "Google-Termine werden über die Google-Synchronisation geändert.")
    changes = apply_patch(db, ev, patch, tz_name)
    audit(db, "event.update", f"Termin „{ev.title}“ geändert", actor=actor, entity_type="event", entity_id=ev.id, project_id=ev.project_id, data={"fields": list(changes)}, commit=False)
    db.commit()
    return ev


def delete_internal_event(db: Session, event_id: int, occurrence: str | None = None, actor: str = "user") -> None:
    ev = get_event(db, event_id)
    if ev.source != "internal":
        raise HTTPException(400, "Google-Termine werden über die Google-Synchronisation gelöscht.")
    if occurrence and ev.rrule:
        ev.exdates = sorted(set(ev.exdates or []) | {occurrence})
        audit(db, "event.delete_occurrence", f"Einzeltermin „{ev.title}“ am {occurrence[:10]} entfernt", actor=actor, entity_type="event", entity_id=ev.id, commit=False)
    else:
        db.delete(ev)
        audit(db, "event.delete", f"Termin „{ev.title}“ gelöscht", actor=actor, entity_type="event", entity_id=event_id, project_id=ev.project_id, commit=False)
    db.commit()


# ----------------------------------------------------------------- Abfrage
def _occurrences(ev: CalendarEvent, start: datetime, end: datetime) -> list[tuple[datetime, datetime, str | None]]:
    if not ev.rrule:
        return [(ev.start_at, ev.end_at, None)]
    tz = ZoneInfo(ev.timezone or "Europe/Berlin")
    duration = ev.end_at - ev.start_at
    dtstart = ev.start_at.astimezone(tz).replace(tzinfo=None)
    try:
        rule = rrulestr(ev.rrule, dtstart=dtstart)
    except Exception:  # noqa: BLE001
        return [(ev.start_at, ev.end_at, None)]
    win_start = (start - duration).astimezone(tz).replace(tzinfo=None)
    win_end = end.astimezone(tz).replace(tzinfo=None)
    ex = set(ev.exdates or [])
    out = []
    for occ in rule.xafter(win_start, count=MAX_OCCURRENCES, inc=True):
        if occ >= win_end:
            break
        key = occ.isoformat()
        if key in ex:
            continue
        s = occ.replace(tzinfo=tz).astimezone(timezone.utc)
        if ev.all_day:
            # Ganztägig: Dauer in Tagen, nicht in Stunden (DST)
            e = local_midnight((occ + timedelta(days=round(duration.total_seconds() / 86400))).date(), tz)
        else:
            e = s + duration
        out.append((s, e, key))
    return out


def serialize(ev: CalendarEvent, s: datetime, e: datetime, occ: str | None, tz: ZoneInfo, extra: dict) -> dict:
    d = {
        "id": f"{ev.id}@{occ}" if occ else str(ev.id),
        "event_id": ev.id,
        "occurrence": occ,
        "source": ev.source,
        "google_calendar_id": ev.google_calendar_id,
        "title": ev.title,
        "notes": ev.notes,
        "location": ev.location,
        "start": s.isoformat(),
        "end": e.isoformat(),
        "all_day": ev.all_day,
        "start_date": s.astimezone(tz).date().isoformat() if ev.all_day else None,
        "end_date": (e.astimezone(tz) - timedelta(days=1)).date().isoformat() if ev.all_day else None,
        "busy": ev.busy,
        "recurring": bool(ev.rrule or ev.recurring_event_id),
        "rrule": ev.rrule,
        "category_id": ev.category_id,
        "reminders": ev.reminders,
        "task_id": ev.task_id,
        "project_id": ev.project_id,
        "origin": ev.origin,
        "sync_state": ev.sync_state,
        "editable": ev.source == "internal" or extra.get("writable", False),
    }
    d["color"] = extra.get("color")
    return d


def list_occurrences(
    db: Session,
    start: datetime,
    end: datetime,
    tz_name: str,
    *,
    sources: list[str] | None = None,
    category_ids: list[int] | None = None,
    google_calendar_ids: list[str] | None = None,
    q: str | None = None,
) -> list[dict]:
    tz = ZoneInfo(tz_name)
    stmt = select(CalendarEvent).where(
        CalendarEvent.deleted.is_(False),
        or_(
            and_(CalendarEvent.rrule.is_(None), CalendarEvent.start_at < end, CalendarEvent.end_at > start),
            and_(CalendarEvent.rrule.is_not(None), CalendarEvent.start_at < end),
        ),
    )
    if sources:
        stmt = stmt.where(CalendarEvent.source.in_(sources))
    if category_ids:
        stmt = stmt.where(CalendarEvent.category_id.in_(category_ids))
    if q:
        stmt = stmt.where(or_(CalendarEvent.title.ilike(f"%{q}%"), CalendarEvent.notes.ilike(f"%{q}%"), CalendarEvent.location.ilike(f"%{q}%")))
    gcals = {c.google_id: c for c in db.scalars(select(GoogleCalendar))}
    cats = {c.id: c.color for c in db.scalars(select(Category))}
    out = []
    for ev in db.scalars(stmt):
        extra: dict = {"color": cats.get(ev.category_id) if ev.category_id else None}
        if ev.source == "google":
            cal = gcals.get(ev.google_calendar_id or "")
            if not cal or not cal.selected:
                continue
            if google_calendar_ids and ev.google_calendar_id not in google_calendar_ids:
                continue
            extra["color"] = extra["color"] or cal.color
            extra["writable"] = cal.access_role in ("owner", "writer")
        for s, e, occ in _occurrences(ev, start, end):
            if s < end and e > start:
                out.append(serialize(ev, s, e, occ, tz, extra))
    out.sort(key=lambda x: (x["start"], not x["all_day"]))
    return out


def find_conflicts(db: Session, start: datetime, end: datetime, tz_name: str, exclude_event_id: int | None = None) -> list[dict]:
    return [
        o
        for o in list_occurrences(db, start, end, tz_name)
        if o["busy"] and not o["all_day"] and o["event_id"] != exclude_event_id
    ]
