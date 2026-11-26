"""Tagesübersicht und datenbasierte Zusammenfassung für Dashboard und KI."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, Task, User
from . import settings_store as st
from .calendar import list_occurrences, local_midnight
from .work import OPEN_STATES, list_projects, list_tasks, project_out, task_out

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
_NUM = {1: "ein", 2: "zwei", 3: "drei", 4: "vier", 5: "fünf", 6: "sechs", 7: "sieben", 8: "acht", 9: "neun", 10: "zehn", 11: "elf", 12: "zwölf"}


def num(n: int) -> str:
    return _NUM.get(n, str(n))


def fmt_date(d: date, today: date | None = None) -> str:
    if today:
        delta = (d - today).days
        if delta == 0:
            return "heute"
        if delta == 1:
            return "morgen"
        if delta == -1:
            return "gestern"
        if 1 < delta < 7:
            return f"am {WEEKDAYS[d.weekday()]}"
    return f"{WEEKDAYS[d.weekday()]}, {d.day}. {MONTHS[d.month - 1]}"


def greeting_for(hour: int) -> str:
    if hour < 5:
        return "Gute Nacht"
    if hour < 11:
        return "Guten Morgen"
    if hour < 18:
        return "Guten Tag"
    return "Guten Abend"


def user_name(db: Session, user: User) -> str:
    return st.get_section(db, "dashboard").get("greeting_name") or user.display_name or user.username


def daily_overview(db: Session, user: User, day: date | None = None) -> dict:
    tz = ZoneInfo(user.timezone)
    now = datetime.now(timezone.utc)
    local_now = now.astimezone(tz)
    today = day or local_now.date()
    day_start, day_end = local_midnight(today, tz), local_midnight(today + timedelta(days=1), tz)

    events_today = list_occurrences(db, day_start, day_end, user.timezone)
    upcoming = [e for e in list_occurrences(db, now, now + timedelta(days=7), user.timezone) if e["start"] >= now.isoformat() or e["all_day"]]
    upcoming = [e for e in upcoming if not (e["start"] < day_end.isoformat() and e in events_today)][:8]

    tasks_today = task_out(db, list_tasks(db, status="active", due_from=today, due_before=today), today)
    overdue = task_out(db, [t for t in list_tasks(db, status="active", due_before=today - timedelta(days=1))], today)
    deadlines_tasks = task_out(db, list_tasks(db, status="active", due_from=today + timedelta(days=1), due_before=today + timedelta(days=14)), today)
    proj = project_out(db, list_projects(db, status="open"), today)
    active = [p for p in proj if p.status == "active"]
    project_deadlines = [p for p in proj if p.deadline and today <= p.deadline <= today + timedelta(days=30)]

    deadlines = sorted(
        [{"type": "task", "id": t.id, "title": t.title, "date": t.due_date.isoformat(), "project_name": t.project_name, "priority": t.priority} for t in deadlines_tasks if t.priority in ("high", "critical") or (t.due_date - today).days <= 7]
        + [{"type": "project", "id": p.id, "title": p.name, "date": p.deadline.isoformat(), "project_name": p.name, "priority": p.priority} for p in project_deadlines],
        key=lambda x: x["date"],
    )[:10]

    return {
        "date": today.isoformat(),
        "date_label": fmt_date(today),
        "greeting": greeting_for(local_now.hour),
        "name": user_name(db, user),
        "events_today": events_today,
        "tasks_today": [t.model_dump(mode="json") for t in tasks_today],
        "overdue": [t.model_dump(mode="json") for t in overdue],
        "upcoming_events": upcoming,
        "deadlines": deadlines,
        "active_projects": [p.model_dump(mode="json") for p in active],
        "summary": summary_text(db, user, today, events_today, tasks_today, overdue, deadlines, local_now),
        "headline": f"{greeting_for(local_now.hour)}, {user_name(db, user)}",
    }


def summary_text(db, user, today, events_today, tasks_today, overdue, deadlines, local_now) -> str:
    """Deterministische, ausschließlich aus echten Daten erzeugte Zusammenfassung."""
    parts = []
    timed = [e for e in events_today if not e["all_day"]]
    remaining = [e for e in timed if e["end"] > datetime.now(timezone.utc).isoformat()]
    if not events_today:
        parts.append("Heute stehen keine Termine an.")
    elif len(events_today) == 1:
        e = events_today[0]
        when = "ganztägig" if e["all_day"] else "um " + datetime.fromisoformat(e["start"]).astimezone(ZoneInfo(user.timezone)).strftime("%H:%M") + " Uhr"
        parts.append(f"Heute steht ein Termin an: „{e['title']}“ {when}.")
    else:
        extra = f", davon {'ist noch einer' if len(remaining) == 1 else 'sind noch ' + num(len(remaining))} offen" if timed and len(remaining) != len(timed) else ""
        parts.append(f"Heute stehen {num(len(events_today))} Termine an{extra}.")
    if tasks_today:
        parts.append(f"{'Eine Aufgabe ist' if len(tasks_today) == 1 else num(len(tasks_today)).capitalize() + ' Aufgaben sind'} heute fällig.")
    if overdue:
        parts.append(f"{'Eine Aufgabe ist' if len(overdue) == 1 else num(len(overdue)).capitalize() + ' Aufgaben sind'} überfällig – am ältesten: „{min(overdue, key=lambda t: t.due_date).title}“.")
    nxt = next((d for d in deadlines if d["type"] == "project"), None) or (deadlines[0] if deadlines else None)
    if nxt:
        d = date.fromisoformat(nxt["date"])
        label = f"Für dein Projekt {nxt['title']}" if nxt["type"] == "project" else f"Die Aufgabe „{nxt['title']}“"
        parts.append(f"{label} ist die nächste Deadline {fmt_date(d, today)}.")
    if not tasks_today and not overdue and not events_today:
        parts.append("Es liegen keine fälligen Punkte vor.")
    return " ".join(parts)



def week_open_tasks(db: Session, user: User) -> list[Task]:
    tz = ZoneInfo(user.timezone)
    today = datetime.now(tz).date()
    end = today + timedelta(days=6 - today.weekday())
    return list(db.scalars(select(Task).where(Task.status.in_(OPEN_STATES), Task.due_date <= end).order_by(Task.due_date)))


def project_context(db: Session) -> list[dict]:
    return [{"id": p.id, "name": p.name, "status": p.status, "deadline": p.deadline.isoformat() if p.deadline else None} for p in db.scalars(select(Project).where(Project.status != "archived").order_by(Project.name))]
