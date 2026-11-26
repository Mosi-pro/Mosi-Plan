"""Fachlogik für Projekte und Aufgaben (genutzt von API und KI-Werkzeugen)."""
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..models import CalendarEvent, MemoryEntry, Project, Task, WeeklyPlanItem
from ..schemas import ProjectIn, ProjectOut, ProjectPatch, TaskIn, TaskOut, TaskPatch
from .audit import audit

STATUS_LABEL = {"open": "Offen", "in_progress": "In Bearbeitung", "waiting": "Wartet", "done": "Erledigt", "archived": "Archiviert"}
PRIORITY_LABEL = {"low": "Niedrig", "normal": "Normal", "high": "Hoch", "critical": "Kritisch"}
PRIORITY_WEIGHT = {"low": 1, "normal": 2, "high": 3, "critical": 4}
PROJECT_STATUS_LABEL = {"planned": "Geplant", "active": "Aktiv", "paused": "Pausiert", "completed": "Abgeschlossen", "archived": "Archiviert"}
OPEN_STATES = ("open", "in_progress", "waiting")


# ----------------------------------------------------------------- Projekte
def _project_stats(db: Session, project_ids: list[int], today: date) -> dict[int, dict]:
    stats: dict[int, dict] = {pid: {"task_total": 0, "task_done": 0, "task_open": 0, "task_overdue": 0, "next_due": None} for pid in project_ids}
    if not project_ids:
        return stats
    rows = db.execute(
        select(Task.project_id, Task.status, Task.due_date).where(
            Task.project_id.in_(project_ids), Task.parent_id.is_(None), Task.status != "archived"
        )
    ).all()
    for pid, status, due in rows:
        s = stats[pid]
        s["task_total"] += 1
        if status == "done":
            s["task_done"] += 1
        else:
            s["task_open"] += 1
            if due and due < today:
                s["task_overdue"] += 1
            if due and due >= today and (s["next_due"] is None or due < s["next_due"]):
                s["next_due"] = due
    for s in stats.values():
        s["progress"] = round(100 * s["task_done"] / s["task_total"]) if s["task_total"] else 0
    return stats


def project_out(db: Session, projects: list[Project], today: date) -> list[ProjectOut]:
    stats = _project_stats(db, [p.id for p in projects], today)
    out = []
    for p in projects:
        po = ProjectOut.model_validate(p)
        for k, v in stats[p.id].items():
            setattr(po, k, v)
        if p.status == "completed":
            po.progress = 100 if po.task_total == 0 else po.progress
        out.append(po)
    return out


def list_projects(db: Session, status: str | None = None, q: str | None = None) -> list[Project]:
    stmt = select(Project)
    if status == "open":
        stmt = stmt.where(Project.status.in_(("planned", "active", "paused")))
    elif status:
        stmt = stmt.where(Project.status == status)
    if q:
        stmt = stmt.where(Project.name.ilike(f"%{q}%"))
    order = func.coalesce(Project.deadline, date(9999, 1, 1))
    return list(db.scalars(stmt.order_by(order, Project.name)))


def get_project(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, f"Projekt {project_id} nicht gefunden.")
    return p


def find_project_by_name(db: Session, name: str) -> Project | None:
    return db.scalars(select(Project).where(func.lower(Project.name) == name.strip().lower())).first() or db.scalars(
        select(Project).where(Project.name.ilike(f"%{name.strip()}%"))
    ).first()


def create_project(db: Session, data: ProjectIn, actor: str = "user") -> Project:
    if data.start_date and data.deadline and data.deadline < data.start_date:
        raise HTTPException(400, "Die Deadline liegt vor dem Startdatum.")
    p = Project(**data.model_dump())
    db.add(p)
    db.flush()
    audit(db, "project.create", f"Projekt „{p.name}“ angelegt", actor=actor, entity_type="project", entity_id=p.id, project_id=p.id, commit=False)
    db.commit()
    return p


def update_project(db: Session, project_id: int, patch: ProjectPatch, actor: str = "user") -> Project:
    p = get_project(db, project_id)
    changes = patch.model_dump(exclude_unset=True)
    before = {k: getattr(p, k) for k in changes}
    for k, v in changes.items():
        setattr(p, k, v)
    if p.start_date and p.deadline and p.deadline < p.start_date:
        raise HTTPException(400, "Die Deadline liegt vor dem Startdatum.")
    diff = {k: [str(before[k]), str(v)] for k, v in changes.items() if before[k] != v and k != "notes"}
    if "notes" in changes and before["notes"] != changes["notes"]:
        diff["notes"] = ["…", "aktualisiert"]
    if diff:
        audit(db, "project.update", f"Projekt „{p.name}“ geändert: {', '.join(diff)}", actor=actor, entity_type="project", entity_id=p.id, project_id=p.id, data=diff, commit=False)
    db.commit()
    return p


def delete_project(db: Session, project_id: int, actor: str = "user") -> None:
    p = get_project(db, project_id)
    name = p.name
    # Aufgaben des Projekts werden archiviert statt gelöscht (kein Datenverlust).
    for t in db.scalars(select(Task).where(Task.project_id == p.id)):
        t.project_id = None
        if t.status != "done":
            t.status = "archived"
    db.query(MemoryEntry).filter(MemoryEntry.project_id == p.id).update({MemoryEntry.project_id: None})
    db.query(CalendarEvent).filter(CalendarEvent.project_id == p.id).update({CalendarEvent.project_id: None})
    db.delete(p)
    audit(db, "project.delete", f"Projekt „{name}“ gelöscht (offene Aufgaben archiviert)", actor=actor, entity_type="project", entity_id=project_id, commit=False)
    db.commit()


# ----------------------------------------------------------------- Aufgaben
def task_out(db: Session, tasks: list[Task], today: date) -> list[TaskOut]:
    ids = [t.id for t in tasks]
    sub: dict[int, list[int]] = {}
    if ids:
        for pid, total, done in db.execute(
            select(Task.parent_id, func.count(), func.count().filter(Task.status == "done"))
            .where(Task.parent_id.in_(ids))
            .group_by(Task.parent_id)
        ):
            sub[pid] = [total, done]
    out = []
    for t in tasks:
        to = TaskOut.model_validate(t)
        if t.project:
            to.project_name, to.project_color = t.project.name, t.project.color
        to.subtask_total, to.subtask_done = sub.get(t.id, [0, 0])
        to.overdue = bool(t.due_date and t.due_date < today and t.status in OPEN_STATES)
        out.append(to)
    return out


def list_tasks(
    db: Session,
    *,
    status: str | None = None,
    project_id: int | None = None,
    due_before: date | None = None,
    due_from: date | None = None,
    q: str | None = None,
    parent_id: int | None = None,
    include_subtasks: bool = False,
    limit: int = 500,
) -> list[Task]:
    stmt = select(Task)
    if status == "active":
        stmt = stmt.where(Task.status.in_(OPEN_STATES))
    elif status:
        stmt = stmt.where(Task.status.in_(status.split(",")))
    else:
        stmt = stmt.where(Task.status != "archived")
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if parent_id is not None:
        stmt = stmt.where(Task.parent_id == parent_id)
    elif not include_subtasks:
        stmt = stmt.where(Task.parent_id.is_(None))
    if due_before:
        stmt = stmt.where(Task.due_date <= due_before)
    if due_from:
        stmt = stmt.where(Task.due_date >= due_from)
    if q:
        stmt = stmt.where(or_(Task.title.ilike(f"%{q}%"), Task.description.ilike(f"%{q}%")))
    prio_order = case({"critical": 0, "high": 1, "normal": 2, "low": 3}, value=Task.priority, else_=4)
    stmt = stmt.order_by(Task.status == "done", Task.due_date.is_(None), Task.due_date, prio_order, Task.sort_order, Task.id)
    return list(db.scalars(stmt.limit(limit)))


def get_task(db: Session, task_id: int) -> Task:
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404, f"Aufgabe {task_id} nicht gefunden.")
    return t


def _validate_refs(db: Session, project_id: int | None, parent_id: int | None, self_id: int | None = None) -> None:
    if project_id is not None and not db.get(Project, project_id):
        raise HTTPException(400, f"Projekt {project_id} existiert nicht.")
    if parent_id is not None:
        parent = db.get(Task, parent_id)
        if not parent:
            raise HTTPException(400, f"Übergeordnete Aufgabe {parent_id} existiert nicht.")
        if self_id is not None and parent_id == self_id:
            raise HTTPException(400, "Eine Aufgabe kann nicht ihre eigene Unteraufgabe sein.")
        if parent.parent_id is not None:
            raise HTTPException(400, "Unteraufgaben können keine weiteren Unteraufgaben haben.")


def create_task(db: Session, data: TaskIn, actor: str = "user", commit: bool = True) -> Task:
    _validate_refs(db, data.project_id, data.parent_id)
    if data.parent_id and data.project_id is None:
        data.project_id = db.get(Task, data.parent_id).project_id
    t = Task(**data.model_dump(), origin="assistant" if actor == "assistant" else "user")
    if t.status == "done":
        t.completed_at = datetime.now(timezone.utc)
    db.add(t)
    db.flush()
    audit(db, "task.create", f"Aufgabe „{t.title}“ erstellt", actor=actor, entity_type="task", entity_id=t.id, project_id=t.project_id, commit=False)
    if commit:
        db.commit()
    return t


def update_task(db: Session, task_id: int, patch: TaskPatch, actor: str = "user") -> Task:
    t = get_task(db, task_id)
    changes = patch.model_dump(exclude_unset=True)
    _validate_refs(db, changes.get("project_id"), changes.get("parent_id"), self_id=t.id)
    before = {k: getattr(t, k) for k in changes}
    for k, v in changes.items():
        setattr(t, k, v)
    if "status" in changes:
        if t.status == "done" and not t.completed_at:
            t.completed_at = datetime.now(timezone.utc)
        elif t.status != "done":
            t.completed_at = None
    diff = {k: [str(before[k]), str(v)] for k, v in changes.items() if before[k] != v}
    if diff:
        label = "erledigt" if changes.get("status") == "done" else "geändert"
        audit(db, "task.update", f"Aufgabe „{t.title}“ {label}", actor=actor, entity_type="task", entity_id=t.id, project_id=t.project_id, data=diff, commit=False)
    db.commit()
    return t


def complete_task(db: Session, task_id: int, actual_minutes: int | None = None, actor: str = "user") -> Task:
    patch = TaskPatch(status="done")
    if actual_minutes is not None:
        patch.actual_minutes = actual_minutes
    return update_task(db, task_id, patch, actor=actor)


def delete_task(db: Session, task_id: int, actor: str = "user") -> None:
    t = get_task(db, task_id)
    title, pid = t.title, t.project_id
    db.query(WeeklyPlanItem).filter(WeeklyPlanItem.task_id == t.id).update({WeeklyPlanItem.task_id: None})
    db.delete(t)
    audit(db, "task.delete", f"Aufgabe „{title}“ gelöscht", actor=actor, entity_type="task", entity_id=task_id, project_id=pid, commit=False)
    db.commit()
