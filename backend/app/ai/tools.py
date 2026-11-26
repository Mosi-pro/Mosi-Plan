"""Kontrollierte KI-Werkzeuge.

Jedes Werkzeug hat ein Pydantic-Eingabeschema (-> JSON-Schema für das Modell),
eine Ausführungsfunktion mit definierter Ausgabe (dict) und eine Regel, ob vor
der Ausführung eine explizite Bestätigung des Benutzers nötig ist.

Bestätigungspflichtig sind: Löschen (Projekte, Termine), Massenänderungen,
Übernahme kompletter Projektpläne und jedes Schreiben in Google Calendar.
Solche Aufrufe erzeugen eine PendingAction, die der Benutzer in der Oberfläche
freigibt oder ablehnt. Es gibt bewusst KEIN Werkzeug für Shell- oder Dateizugriff.
"""
import logging
from dataclasses import dataclass
from datetime import date as Date, datetime, timedelta, timezone
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CalendarEvent, PendingAction, Task, User
from ..schemas import EventIn, EventPatch, MemoryIn, ProjectIn, ProjectPatch, TaskIn, TaskPatch
from ..services import calendar as cal
from ..services import google_calendar as gcal
from ..services import memory as mem
from ..services import planner, work
from ..services import settings_store as st
from ..services.audit import audit
from ..services.overview import daily_overview

log = logging.getLogger("mosi.tools")

Prio = Literal["low", "normal", "high", "critical"]


@dataclass
class ToolContext:
    db: Session
    user: User
    conversation_id: int | None = None
    actor: str = "assistant"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.user.timezone)

    def today(self) -> Date:
        return datetime.now(self.tz).date()


@dataclass
class Tool:
    name: str
    description: str
    params: type[BaseModel]
    handler: Callable[[ToolContext, Any], dict]
    needs_confirmation: Callable[[ToolContext, Any], bool] = lambda ctx, a: False
    describe: Callable[[ToolContext, Any], str] | None = None
    preview: Callable[[ToolContext, Any], dict] | None = None
    read_only: bool = False


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, params: type[BaseModel], **kw):
    def deco(fn):
        REGISTRY[name] = Tool(name=name, description=description, params=params, handler=fn, **kw)
        return fn

    return deco


def _local_dt(ctx: ToolContext, value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, f"Ungültiges Datum/Uhrzeit: {value} (erwartet ISO 8601, z. B. 2026-12-01T09:00)") from exc
    return dt.replace(tzinfo=ctx.tz) if dt.tzinfo is None else dt


def _resolve_project(ctx: ToolContext, project_id: int | None, project_name: str | None) -> int | None:
    if project_id is not None:
        work.get_project(ctx.db, project_id)
        return project_id
    if project_name:
        p = work.find_project_by_name(ctx.db, project_name)
        if not p:
            raise HTTPException(400, f"Kein Projekt mit dem Namen „{project_name}“ gefunden. Verfügbare Projekte mit get_projects abfragen oder Projekt anlegen.")
        return p.id
    return None


def _task_dict(t) -> dict:
    return {
        "id": t.id, "title": t.title, "status": t.status, "priority": t.priority, "project_id": t.project_id,
        "project": t.project_name, "due_date": t.due_date.isoformat() if t.due_date else None,
        "estimated_minutes": t.estimated_minutes, "overdue": t.overdue, "subtasks": f"{t.subtask_done}/{t.subtask_total}" if t.subtask_total else None,
        "description": (t.description or "")[:300],
    }


def _event_brief(o: dict, tz: ZoneInfo) -> dict:
    s = datetime.fromisoformat(o["start"]).astimezone(tz)
    e = datetime.fromisoformat(o["end"]).astimezone(tz)
    return {
        "event_id": o["event_id"], "occurrence": o["occurrence"], "title": o["title"], "source": o["source"],
        "all_day": o["all_day"], "start": s.isoformat(timespec="minutes"), "end": e.isoformat(timespec="minutes"),
        "location": o["location"] or None, "recurring": o["recurring"], "busy": o["busy"],
    }


# ======================================================================= Übersicht
class OverviewArgs(BaseModel):
    date: Date | None = Field(default=None, description="Tag (YYYY-MM-DD); Standard: heute")


@tool("get_daily_overview", "Tagesübersicht: Termine, fällige und überfällige Aufgaben, Deadlines, aktive Projekte.", OverviewArgs, read_only=True)
def _overview(ctx: ToolContext, a: OverviewArgs) -> dict:
    o = daily_overview(ctx.db, ctx.user, a.date)
    return {
        "date": o["date"], "summary": o["summary"],
        "events_today": [_event_brief(e, ctx.tz) for e in o["events_today"]],
        "tasks_due_today": [{"id": t["id"], "title": t["title"], "priority": t["priority"], "project": t["project_name"]} for t in o["tasks_today"]],
        "overdue_tasks": [{"id": t["id"], "title": t["title"], "due_date": t["due_date"], "project": t["project_name"]} for t in o["overdue"]],
        "deadlines": o["deadlines"],
        "active_projects": [{"id": p["id"], "name": p["name"], "progress": p["progress"], "open_tasks": p["task_open"], "deadline": p["deadline"]} for p in o["active_projects"]],
    }


# ======================================================================= Kalender
class GetEventsArgs(BaseModel):
    start_date: Date = Field(description="Erster Tag (YYYY-MM-DD)")
    end_date: Date = Field(description="Letzter Tag (inklusiv, YYYY-MM-DD), max. 62 Tage nach start_date")
    query: str | None = Field(default=None, max_length=100, description="Optionaler Suchbegriff")


@tool("get_calendar_events", "Termine aus internem Kalender und Google Calendar in einem Zeitraum.", GetEventsArgs, read_only=True)
def _get_events(ctx: ToolContext, a: GetEventsArgs) -> dict:
    if a.end_date < a.start_date or (a.end_date - a.start_date).days > 62:
        raise HTTPException(400, "Zeitraum ungültig (maximal 62 Tage).")
    occ = cal.list_occurrences(ctx.db, cal.local_midnight(a.start_date, ctx.tz), cal.local_midnight(a.end_date + timedelta(days=1), ctx.tz), ctx.user.timezone, q=a.query)
    return {"timezone": ctx.user.timezone, "count": len(occ), "events": [_event_brief(o, ctx.tz) for o in occ[:200]]}


class FreeSlotsArgs(BaseModel):
    start_date: Date
    end_date: Date
    min_minutes: int = Field(default=30, ge=15, le=480)


@tool("get_free_slots", "Freie Zeitfenster innerhalb der hinterlegten Arbeitszeiten (berücksichtigt Termine, Puffer, Mittagspause).", FreeSlotsArgs, read_only=True)
def _free_slots(ctx: ToolContext, a: FreeSlotsArgs) -> dict:
    if a.end_date < a.start_date or (a.end_date - a.start_date).days > 31:
        raise HTTPException(400, "Zeitraum ungültig (maximal 31 Tage).")
    slots = planner.free_slots(ctx.db, ctx.user, a.start_date, a.end_date)
    out = [
        {"start": s.start.astimezone(ctx.tz).isoformat(timespec="minutes"), "end": s.end.astimezone(ctx.tz).isoformat(timespec="minutes"), "minutes": s.minutes}
        for s in slots if s.minutes >= a.min_minutes
    ]
    return {"slots": out[:100], "total_free_minutes": sum(s["minutes"] for s in out), "note": "Nur innerhalb der hinterlegten Arbeitszeiten; andere Zeiten gelten als nicht verfügbar."}


class CreateEventArgs(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    start: str | None = Field(default=None, description="Beginn lokal, ISO 8601 z. B. 2026-12-01T09:00 (nicht bei ganztägig)")
    end: str | None = Field(default=None, description="Ende lokal, ISO 8601; Standard: 1 Stunde nach Beginn")
    all_day: bool = False
    date: Date | None = Field(default=None, description="Tag bei ganztägigen Terminen")
    end_date: Date | None = Field(default=None, description="Letzter Tag bei mehrtägigen ganztägigen Terminen")
    notes: str = Field(default="", max_length=5000)
    location: str = Field(default="", max_length=300)
    rrule: str | None = Field(default=None, description="Optionale RFC-5545-Regel, z. B. FREQ=WEEKLY;BYDAY=MO")
    reminders: list[int] = Field(default_factory=list, description="Erinnerungen in Minuten vor Beginn")
    task_id: int | None = None
    project_id: int | None = None
    target: Literal["internal", "google"] = Field(default="internal", description="internal = MOSI-Kalender; google = Google Calendar (erfordert Bestätigung)")


def _event_in(ctx: ToolContext, a: CreateEventArgs) -> EventIn:
    return EventIn(
        title=a.title, notes=a.notes, location=a.location, all_day=a.all_day,
        start=_local_dt(ctx, a.start) if a.start else None, end=_local_dt(ctx, a.end) if a.end else None,
        start_date=a.date, end_date=a.end_date or a.date, rrule=a.rrule, reminders=a.reminders or st.get_section(ctx.db, "calendar")["default_reminders"],
        task_id=a.task_id, project_id=a.project_id, target=a.target,
    )


def _describe_create_event(ctx: ToolContext, a: CreateEventArgs) -> str:
    when = a.date.isoformat() if a.all_day and a.date else (a.start or "")
    return f"Termin „{a.title}“ ({when.replace('T', ' ')}) in Google Calendar eintragen"


@tool(
    "create_calendar_event",
    "Erstellt einen Termin. Standard: interner MOSI-Kalender (sofort). target=google schreibt nach Google Calendar und braucht eine Bestätigung.",
    CreateEventArgs,
    needs_confirmation=lambda ctx, a: a.target == "google",
    describe=_describe_create_event,
)
def _create_event(ctx: ToolContext, a: CreateEventArgs) -> dict:
    data = _event_in(ctx, a)
    if a.target == "google":
        ev = gcal.create_remote_event(ctx.db, data, ctx.user.timezone, actor=ctx.actor)
    else:
        ev = cal.create_internal_event(ctx.db, data, ctx.user.timezone, actor=ctx.actor)
    conflicts = cal.find_conflicts(ctx.db, ev.start_at, ev.end_at, ctx.user.timezone, exclude_event_id=ev.id) if not ev.all_day else []
    return {
        "saved": True, "event_id": ev.id, "source": ev.source, "title": ev.title,
        "start": ev.start_at.astimezone(ctx.tz).isoformat(timespec="minutes"), "end": ev.end_at.astimezone(ctx.tz).isoformat(timespec="minutes"),
        "conflicts": [_event_brief(c, ctx.tz) for c in conflicts],
    }


class UpdateEventArgs(BaseModel):
    event_id: int
    title: str | None = Field(default=None, max_length=300)
    start: str | None = None
    end: str | None = None
    all_day: bool | None = None
    date: Date | None = None
    end_date: Date | None = None
    notes: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=300)
    task_id: int | None = None
    project_id: int | None = None


def _event_patch(ctx: ToolContext, a: UpdateEventArgs) -> EventPatch:
    data = a.model_dump(exclude_unset=True, exclude={"event_id", "date", "start", "end"})
    if a.start:
        data["start"] = _local_dt(ctx, a.start)
    if a.end:
        data["end"] = _local_dt(ctx, a.end)
    if a.date:
        data["start_date"] = a.date
    return EventPatch(**data)


def _is_google_event(ctx: ToolContext, event_id: int) -> bool:
    ev = ctx.db.get(CalendarEvent, event_id)
    return bool(ev and ev.source == "google")


@tool(
    "update_calendar_event",
    "Ändert einen Termin (Zeiten lokal im ISO-Format). Interne Termine sofort; Google-Termine nach Bestätigung.",
    UpdateEventArgs,
    needs_confirmation=lambda ctx, a: _is_google_event(ctx, a.event_id),
    describe=lambda ctx, a: f"Google-Termin #{a.event_id} („{cal.get_event(ctx.db, a.event_id).title}“) ändern",
)
def _update_event(ctx: ToolContext, a: UpdateEventArgs) -> dict:
    patch = _event_patch(ctx, a)
    if _is_google_event(ctx, a.event_id):
        ev = gcal.update_remote_event(ctx.db, a.event_id, patch, ctx.user.timezone, actor=ctx.actor)
    else:
        ev = cal.update_internal_event(ctx.db, a.event_id, patch, ctx.user.timezone, actor=ctx.actor)
    return {"saved": True, "event_id": ev.id, "title": ev.title, "start": ev.start_at.astimezone(ctx.tz).isoformat(timespec="minutes"), "end": ev.end_at.astimezone(ctx.tz).isoformat(timespec="minutes")}


class DeleteEventArgs(BaseModel):
    event_id: int
    occurrence: str | None = Field(default=None, description="Nur bei Serien: Kennung eines Einzeltermins (aus get_calendar_events)")


def _describe_delete_event(ctx: ToolContext, a: DeleteEventArgs) -> str:
    ev = cal.get_event(ctx.db, a.event_id)
    src = "Google-Termin" if ev.source == "google" else "Termin"
    local = ev.start_at.astimezone(ctx.tz)
    extra = f" (nur Einzeltermin {a.occurrence[:16].replace('T', ' ')})" if a.occurrence else (" (gesamte Serie)" if ev.rrule else "")
    return f"{src} „{ev.title}“ am {local.strftime('%d.%m.%Y %H:%M')} löschen{extra}"


@tool("delete_calendar_event", "Löscht einen Termin. Erfordert immer eine Bestätigung durch den Benutzer.", DeleteEventArgs,
      needs_confirmation=lambda ctx, a: True, describe=_describe_delete_event)
def _delete_event(ctx: ToolContext, a: DeleteEventArgs) -> dict:
    if _is_google_event(ctx, a.event_id):
        gcal.delete_remote_event(ctx.db, a.event_id, actor=ctx.actor)
    else:
        cal.delete_internal_event(ctx.db, a.event_id, a.occurrence, actor=ctx.actor)
    return {"deleted": True, "event_id": a.event_id}


# ======================================================================= Projekte
class GetProjectsArgs(BaseModel):
    status: Literal["open", "planned", "active", "paused", "completed", "archived"] | None = Field(default="open")
    query: str | None = Field(default=None, max_length=100)


@tool("get_projects", "Listet Projekte mit Fortschritt, offenen/überfälligen Aufgaben und Deadlines.", GetProjectsArgs, read_only=True)
def _get_projects(ctx: ToolContext, a: GetProjectsArgs) -> dict:
    ps = work.project_out(ctx.db, work.list_projects(ctx.db, a.status, a.query), ctx.today())
    return {"projects": [
        {"id": p.id, "name": p.name, "status": p.status, "priority": p.priority, "goal": p.goal[:300], "deadline": p.deadline.isoformat() if p.deadline else None,
         "progress_percent": p.progress, "open_tasks": p.task_open, "overdue_tasks": p.task_overdue, "next_task_due": p.next_due.isoformat() if p.next_due else None}
        for p in ps]}


class CreateProjectArgs(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    goal: str = Field(default="", max_length=2000)
    status: Literal["planned", "active"] = "active"
    priority: Prio = "normal"
    start_date: Date | None = None
    deadline: Date | None = None
    categories: list[str] = Field(default_factory=list)


@tool("create_project", "Legt ein neues Projekt an.", CreateProjectArgs)
def _create_project(ctx: ToolContext, a: CreateProjectArgs) -> dict:
    if work.find_project_by_name(ctx.db, a.name) and work.find_project_by_name(ctx.db, a.name).name.lower() == a.name.lower():
        raise HTTPException(400, f"Ein Projekt „{a.name}“ existiert bereits.")
    p = work.create_project(ctx.db, ProjectIn(**a.model_dump()), actor=ctx.actor)
    return {"saved": True, "project_id": p.id, "name": p.name}


class UpdateProjectArgs(BaseModel):
    project_id: int
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    goal: str | None = Field(default=None, max_length=2000)
    status: Literal["planned", "active", "paused", "completed", "archived"] | None = None
    priority: Prio | None = None
    start_date: Date | None = None
    deadline: Date | None = None
    notes_append: str | None = Field(default=None, max_length=2000, description="Text, der an die Projektnotizen angehängt wird")


@tool("update_project", "Ändert Projektdaten (Status, Priorität, Deadline, Ziel …) oder ergänzt Notizen.", UpdateProjectArgs)
def _update_project(ctx: ToolContext, a: UpdateProjectArgs) -> dict:
    data = a.model_dump(exclude_unset=True, exclude={"project_id", "notes_append"})
    if a.notes_append:
        p = work.get_project(ctx.db, a.project_id)
        data["notes"] = (p.notes + "\n\n" if p.notes else "") + a.notes_append
    p = work.update_project(ctx.db, a.project_id, ProjectPatch(**data), actor=ctx.actor)
    return {"saved": True, "project_id": p.id, "name": p.name, "status": p.status}


class DeleteProjectArgs(BaseModel):
    project_id: int


@tool("delete_project", "Löscht ein Projekt (offene Aufgaben werden archiviert). Erfordert immer eine Bestätigung.", DeleteProjectArgs,
      needs_confirmation=lambda ctx, a: True,
      describe=lambda ctx, a: f"Projekt „{work.get_project(ctx.db, a.project_id).name}“ löschen (offene Aufgaben werden archiviert)")
def _delete_project(ctx: ToolContext, a: DeleteProjectArgs) -> dict:
    work.delete_project(ctx.db, a.project_id, actor=ctx.actor)
    return {"deleted": True, "project_id": a.project_id}


# ======================================================================= Aufgaben
class GetTasksArgs(BaseModel):
    status: Literal["active", "open", "in_progress", "waiting", "done", "archived"] | None = Field(default="active", description="active = offen + in Bearbeitung + wartet")
    project_id: int | None = None
    project_name: str | None = None
    due_from: Date | None = None
    due_before: Date | None = Field(default=None, description="Fällig bis einschließlich")
    query: str | None = Field(default=None, max_length=100)


@tool("get_tasks", "Listet Aufgaben, filterbar nach Status, Projekt, Fälligkeit und Suchbegriff.", GetTasksArgs, read_only=True)
def _get_tasks(ctx: ToolContext, a: GetTasksArgs) -> dict:
    pid = _resolve_project(ctx, a.project_id, a.project_name)
    ts = work.task_out(ctx.db, work.list_tasks(ctx.db, status=a.status, project_id=pid, due_from=a.due_from, due_before=a.due_before, q=a.query, limit=150), ctx.today())
    return {"count": len(ts), "tasks": [_task_dict(t) for t in ts]}


class CreateTaskArgs(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    priority: Prio = "normal"
    project_id: int | None = None
    project_name: str | None = Field(default=None, description="Alternativ zum project_id: Projektname")
    parent_id: int | None = Field(default=None, description="Übergeordnete Aufgabe (für Unteraufgaben)")
    due_date: Date | None = None
    estimated_minutes: int | None = Field(default=None, ge=5, le=10000)
    status: Literal["open", "in_progress", "waiting"] = "open"


@tool("create_task", "Erstellt eine Aufgabe (optional mit Projekt, Fälligkeit, Zeitschätzung, als Unteraufgabe).", CreateTaskArgs)
def _create_task(ctx: ToolContext, a: CreateTaskArgs) -> dict:
    pid = _resolve_project(ctx, a.project_id, a.project_name)
    t = work.create_task(ctx.db, TaskIn(**a.model_dump(exclude={"project_name", "project_id"}), project_id=pid), actor=ctx.actor)
    return {"saved": True, "task_id": t.id, "title": t.title, "project_id": t.project_id, "due_date": t.due_date.isoformat() if t.due_date else None}


class UpdateTaskArgs(BaseModel):
    task_id: int
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    status: Literal["open", "in_progress", "waiting", "done", "archived"] | None = None
    priority: Prio | None = None
    project_id: int | None = None
    due_date: Date | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=10000)


@tool("update_task", "Ändert eine Aufgabe (Titel, Status, Priorität, Fälligkeit, Schätzung, Projekt).", UpdateTaskArgs)
def _update_task(ctx: ToolContext, a: UpdateTaskArgs) -> dict:
    t = work.update_task(ctx.db, a.task_id, TaskPatch(**a.model_dump(exclude_unset=True, exclude={"task_id"})), actor=ctx.actor)
    return {"saved": True, "task_id": t.id, "title": t.title, "status": t.status, "priority": t.priority, "due_date": t.due_date.isoformat() if t.due_date else None}


class CompleteTaskArgs(BaseModel):
    task_id: int
    actual_minutes: int | None = Field(default=None, ge=0, le=10000)


@tool("complete_task", "Markiert eine Aufgabe als erledigt.", CompleteTaskArgs)
def _complete_task(ctx: ToolContext, a: CompleteTaskArgs) -> dict:
    t = work.complete_task(ctx.db, a.task_id, a.actual_minutes, actor=ctx.actor)
    return {"saved": True, "task_id": t.id, "title": t.title, "status": t.status}


class BulkUpdateArgs(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=100)
    status: Literal["open", "in_progress", "waiting", "done", "archived"] | None = None
    priority: Prio | None = None
    due_date: Date | None = None
    reason: str = Field(default="", max_length=300, description="Kurze Begründung für den Benutzer")


@tool("bulk_update_tasks", "Ändert mehrere Aufgaben gleichzeitig (z. B. Neupriorisierung). Massenänderung -> Bestätigung erforderlich.", BulkUpdateArgs,
      needs_confirmation=lambda ctx, a: True,
      describe=lambda ctx, a: f"{len(a.task_ids)} Aufgaben ändern: " + ", ".join(f"{k} → {v}" for k, v in a.model_dump(exclude_unset=True, exclude={'task_ids', 'reason'}).items()) + (f" ({a.reason})" if a.reason else ""),
      preview=lambda ctx, a: {"tasks": [{"id": t.id, "title": t.title} for t in ctx.db.scalars(select(Task).where(Task.id.in_(a.task_ids)))]})
def _bulk_update(ctx: ToolContext, a: BulkUpdateArgs) -> dict:
    patch = a.model_dump(exclude_unset=True, exclude={"task_ids", "reason"})
    if not patch:
        raise HTTPException(400, "Keine Änderung angegeben.")
    done = []
    for tid in a.task_ids:
        work.update_task(ctx.db, tid, TaskPatch(**patch), actor=ctx.actor)
        done.append(tid)
    return {"saved": True, "updated": done}


# ======================================================================= Projektplanung
class PlanTask(BaseModel):
    key: str = Field(min_length=1, max_length=40, description="Eindeutiger Kurzschlüssel innerhalb des Plans, z. B. 't1'")
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=2000)
    estimated_minutes: int = Field(ge=5, le=10000)
    due_date: Date | None = None
    priority: Prio = "normal"
    depends_on: list[str] = Field(default_factory=list, description="Schlüssel von Aufgaben, die vorher erledigt sein müssen")
    parent_key: str | None = Field(default=None, description="Schlüssel einer übergeordneten Aufgabe (Unteraufgabe)")


class ProjectPlanArgs(BaseModel):
    project_name: str = Field(min_length=1, max_length=200)
    existing_project_id: int | None = Field(default=None, description="Gesetzt, wenn die Aufgaben einem bestehenden Projekt hinzugefügt werden")
    goal: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=5000)
    start_date: Date | None = None
    deadline: Date | None = None
    priority: Prio = "normal"
    tasks: list[PlanTask] = Field(min_length=1, max_length=60)
    assumptions: list[str] = Field(default_factory=list, description="Annahmen, die der Benutzer prüfen sollte")


def _validate_plan(ctx: ToolContext, a: ProjectPlanArgs) -> dict:
    keys = [t.key for t in a.tasks]
    if len(set(keys)) != len(keys):
        raise HTTPException(400, "Doppelte Aufgabenschlüssel im Plan.")
    for t in a.tasks:
        for d in t.depends_on:
            if d not in keys or d == t.key:
                raise HTTPException(400, f"Unbekannte Abhängigkeit „{d}“ bei „{t.title}“.")
        if t.parent_key and t.parent_key not in keys:
            raise HTTPException(400, f"Unbekannte übergeordnete Aufgabe „{t.parent_key}“.")
    # Zyklen erkennen
    graph = {t.key: set(t.depends_on) for t in a.tasks}
    visiting, done = set(), set()

    def visit(k):
        if k in done:
            return
        if k in visiting:
            raise HTTPException(400, "Die Abhängigkeiten enthalten einen Zyklus.")
        visiting.add(k)
        for d in graph[k]:
            visit(d)
        visiting.discard(k)
        done.add(k)

    for k in graph:
        visit(k)
    if a.existing_project_id:
        work.get_project(ctx.db, a.existing_project_id)
    total = sum(t.estimated_minutes for t in a.tasks if not any(o.parent_key == t.key for o in a.tasks))
    today = ctx.today()
    end = a.deadline or max([t.due_date for t in a.tasks if t.due_date] or [today + timedelta(days=28)])
    capacity = sum(s.minutes for s in planner.free_slots(ctx.db, ctx.user, max(today, a.start_date or today), min(end, today + timedelta(days=90))))
    warnings = []
    if a.deadline and any(t.due_date and t.due_date > a.deadline for t in a.tasks):
        warnings.append("Einzelne Aufgaben liegen nach der Projektdeadline.")
    if capacity and total > capacity * 0.7:
        warnings.append(f"Geschätzter Aufwand ({round(total / 60, 1)} h) beansprucht mehr als 70 % der freien Arbeitszeit bis {end.strftime('%d.%m.%Y')} ({round(capacity / 60, 1)} h).")
    return {"total_minutes": total, "free_minutes_until_end": capacity, "end": end.isoformat(), "warnings": warnings}


def _plan_preview(ctx: ToolContext, a: ProjectPlanArgs) -> dict:
    return {"project": a.project_name, "existing_project_id": a.existing_project_id, "goal": a.goal, "deadline": a.deadline.isoformat() if a.deadline else None,
            "tasks": [t.model_dump(mode="json") for t in a.tasks], "assumptions": a.assumptions, "check": _validate_plan(ctx, a)}


@tool(
    "propose_project_plan",
    "Schlägt einen vollständigen Projektplan vor (Teilaufgaben mit Aufwand, Deadlines, Abhängigkeiten). Wird erst nach Bestätigung durch den Benutzer gespeichert. Vorher ggf. get_free_slots/get_calendar_events prüfen.",
    ProjectPlanArgs,
    needs_confirmation=lambda ctx, a: True,
    describe=lambda ctx, a: f"Projektplan „{a.project_name}“ mit {len(a.tasks)} Aufgaben übernehmen",
    preview=_plan_preview,
)
def _apply_plan(ctx: ToolContext, a: ProjectPlanArgs) -> dict:
    _validate_plan(ctx, a)
    if a.existing_project_id:
        p = work.get_project(ctx.db, a.existing_project_id)
        if a.goal and not p.goal:
            p.goal = a.goal
        if a.deadline and not p.deadline:
            p.deadline = a.deadline
    else:
        p = work.create_project(ctx.db, ProjectIn(name=a.project_name, goal=a.goal, description=a.description, start_date=a.start_date, deadline=a.deadline, priority=a.priority), actor=ctx.actor)
    ids: dict[str, int] = {}
    ordered = sorted(a.tasks, key=lambda t: (t.parent_key is not None))
    for i, t in enumerate(ordered):
        task = work.create_task(ctx.db, TaskIn(title=t.title, description=t.description, priority=t.priority, project_id=p.id, due_date=t.due_date,
                                               estimated_minutes=t.estimated_minutes, parent_id=ids.get(t.parent_key) if t.parent_key else None), actor=ctx.actor, commit=False)
        task.sort_order = i
        ids[t.key] = task.id
    for t in a.tasks:
        if t.depends_on:
            ctx.db.get(Task, ids[t.key]).depends_on = [ids[d] for d in t.depends_on]
    audit(ctx.db, "project.plan_apply", f"Projektplan mit {len(a.tasks)} Aufgaben übernommen", actor=ctx.actor, entity_type="project", entity_id=p.id, project_id=p.id, commit=False)
    ctx.db.commit()
    return {"saved": True, "project_id": p.id, "created_tasks": len(ids)}


# ======================================================================= Wochenplan
class WeeklyPlanArgs(BaseModel):
    week_start: Date | None = Field(default=None, description="Montag der Woche; Standard: kommende Woche (bzw. aktuelle Woche, wenn heute Montag–Mittwoch)")


@tool("create_weekly_plan", "Erstellt einen Wochenplan-ENTWURF auf Basis von Kalendern, Aufgaben, Deadlines und Planungsregeln. Der Benutzer gibt ihn auf der Seite Wochenplan frei.", WeeklyPlanArgs)
def _weekly_plan(ctx: ToolContext, a: WeeklyPlanArgs) -> dict:
    today = ctx.today()
    ws = a.week_start or (planner.week_start_of(today) if today.weekday() <= 2 else planner.week_start_of(today) + timedelta(days=7))
    plan = planner.generate_plan(ctx.db, ctx.user, ws, generated_by="assistant")
    d = plan.data
    return {
        "plan_id": plan.id, "status": "draft (noch nicht im Kalender)", "week_start": ws.isoformat(), "link": "/wochenplan",
        "blocks": [{"title": i.title, "start": i.start_at.astimezone(ctx.tz).isoformat(timespec="minutes"), "minutes": int((i.end_at - i.start_at).total_seconds() // 60)} for i in plan.items],
        "goals": d["goals"], "deadlines": d["deadlines"], "warnings": d["warnings"], "unscheduled": d["unscheduled"], "recommendations": d["recommendations"], "stats": d["stats"],
    }


# ======================================================================= Gedächtnis
class SearchMemoryArgs(BaseModel):
    query: str = Field(default="", max_length=200)
    category: Literal["project", "decision", "planning_rule", "recurring", "goal", "note", "preference"] | None = None
    project_id: int | None = None


@tool("search_memory", "Durchsucht das persönliche Gedächtnis (Entscheidungen, Planungsregeln, Ziele, Notizen).", SearchMemoryArgs, read_only=True)
def _search_memory(ctx: ToolContext, a: SearchMemoryArgs) -> dict:
    if not st.get_section(ctx.db, "ai")["memory_enabled"]:
        return {"entries": [], "note": "Gedächtniszugriff ist in den Einstellungen deaktiviert."}
    rows = mem.search_memory(ctx.db, a.query, a.category, a.project_id, limit=20)
    return {"entries": [{"id": m.id, "content": m.content, "category": m.category, "project_id": m.project_id, "created": m.created_at.date().isoformat()} for m in rows]}


class SaveMemoryArgs(BaseModel):
    content: str = Field(min_length=3, max_length=2000)
    category: Literal["project", "decision", "planning_rule", "recurring", "goal", "note", "preference"] = "note"
    project_id: int | None = None


@tool("save_memory", "Speichert eine wichtige Information dauerhaft (nur auf Wunsch des Benutzers oder bei klar relevanten Entscheidungen/Regeln; keine sensiblen Daten).", SaveMemoryArgs)
def _save_memory(ctx: ToolContext, a: SaveMemoryArgs) -> dict:
    if not st.get_section(ctx.db, "ai")["memory_enabled"]:
        raise HTTPException(400, "Das Gedächtnis ist in den Einstellungen deaktiviert.")
    m = mem.create_memory(ctx.db, MemoryIn(**a.model_dump()), source="assistant", actor=ctx.actor)
    return {"saved": True, "memory_id": m.id}


# ======================================================================= Ausführung
def openai_tools() -> list[dict]:
    out = []
    for t in REGISTRY.values():
        schema = t.params.model_json_schema()
        schema.pop("title", None)
        out.append({"type": "function", "function": {"name": t.name, "description": t.description, "parameters": schema}})
    return out


def mcp_tools() -> list[dict]:
    out = []
    for t in REGISTRY.values():
        schema = t.params.model_json_schema()
        schema.pop("title", None)
        out.append({"name": t.name, "description": t.description, "inputSchema": schema,
                    "annotations": {"readOnlyHint": t.read_only, "destructiveHint": t.name.startswith("delete_")}})
    return out


def _err_text(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
    return str(exc)


def execute_tool(ctx: ToolContext, name: str, raw_args: dict | None, confirmed: bool = False) -> dict:
    t = REGISTRY.get(name)
    if not t:
        return {"ok": False, "error": f"Unbekanntes Werkzeug: {name}"}
    try:
        args = t.params.model_validate(raw_args or {})
    except ValidationError as exc:
        return {"ok": False, "error": "Ungültige Eingabe: " + _err_text(exc)}
    try:
        if not confirmed and t.needs_confirmation(ctx, args):
            desc = t.describe(ctx, args) if t.describe else f"Aktion {name} ausführen"
            preview = t.preview(ctx, args) if t.preview else {}
            pa = PendingAction(tool=name, args=args.model_dump(mode="json", exclude_unset=True), description=desc, preview=preview, conversation_id=ctx.conversation_id)
            ctx.db.add(pa)
            ctx.db.commit()
            audit(ctx.db, "assistant.pending", desc, actor=ctx.actor, entity_type="pending_action", entity_id=pa.id)
            return {"ok": True, "status": "confirmation_required", "pending_action_id": pa.id, "action": desc,
                    "message": "NICHT ausgeführt. Der Benutzer muss diese Aktion in der MOSI-Oberfläche bestätigen. Sage ihm das klar und stelle nichts als erledigt dar."}
        result = t.handler(ctx, args)
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001
        ctx.db.rollback()
        if not isinstance(exc, (HTTPException, ValidationError)):
            log.exception("Werkzeugfehler %s", name)
        return {"ok": False, "error": _err_text(exc)}


def confirm_pending(db: Session, user: User, action_id: int) -> PendingAction:
    pa = db.get(PendingAction, action_id)
    if not pa:
        raise HTTPException(404, "Aktion nicht gefunden.")
    if pa.status != "pending":
        raise HTTPException(400, "Diese Aktion wurde bereits bearbeitet.")
    if datetime.now(timezone.utc) - pa.created_at > timedelta(hours=24):
        pa.status = "expired"
        db.commit()
        raise HTTPException(400, "Die Aktion ist abgelaufen (älter als 24 Stunden). Bitte erneut anfragen.")
    ctx = ToolContext(db=db, user=user, conversation_id=pa.conversation_id, actor="assistant")
    result = execute_tool(ctx, pa.tool, pa.args, confirmed=True)
    pa = db.get(PendingAction, action_id)
    pa.status = "confirmed" if result.get("ok") else "failed"
    pa.result = result
    pa.resolved_at = datetime.now(timezone.utc)
    audit(db, "assistant.confirmed" if result.get("ok") else "assistant.failed", pa.description, actor="user", entity_type="pending_action", entity_id=pa.id, commit=False)
    db.commit()
    return pa


def reject_pending(db: Session, action_id: int) -> PendingAction:
    pa = db.get(PendingAction, action_id)
    if not pa:
        raise HTTPException(404, "Aktion nicht gefunden.")
    if pa.status != "pending":
        raise HTTPException(400, "Diese Aktion wurde bereits bearbeitet.")
    pa.status = "rejected"
    pa.resolved_at = datetime.now(timezone.utc)
    audit(db, "assistant.rejected", pa.description, entity_type="pending_action", entity_id=pa.id, commit=False)
    db.commit()
    return pa
