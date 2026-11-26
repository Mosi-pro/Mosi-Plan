from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, Category, Project, Task, User
from ..schemas import CategoryIn, MemoryIn, MemoryOut, MemoryPatch, ProjectIn, ProjectPatch, TaskIn, TaskPatch
from ..security import get_current_user
from ..services import memory as mem
from ..services import work
from ..services.calendar import list_occurrences, local_midnight
from ..services.overview import daily_overview

router = APIRouter(prefix="/api", tags=["core"])


def _today(user: User) -> date:
    return datetime.now(ZoneInfo(user.timezone)).date()


# ----------------------------------------------------------------- Dashboard
@router.get("/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return daily_overview(db, user)


# ----------------------------------------------------------------- Projekte
@router.get("/projects")
def projects(status: str | None = None, q: str | None = Query(None, max_length=100), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return work.project_out(db, work.list_projects(db, status, q), _today(user))


@router.post("/projects", status_code=201)
def create_project(data: ProjectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return work.project_out(db, [work.create_project(db, data)], _today(user))[0]


@router.get("/projects/{pid}")
def project_detail(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = _today(user)
    p = work.get_project(db, pid)
    tasks = work.task_out(db, work.list_tasks(db, project_id=pid, include_subtasks=True, status="open,in_progress,waiting,done"), today)
    history = db.scalars(select(AuditLog).where(AuditLog.project_id == pid).order_by(AuditLog.ts.desc()).limit(100))
    tz = ZoneInfo(user.timezone)
    events = list_occurrences(db, local_midnight(today, tz), local_midnight(today + timedelta(days=60), tz), user.timezone)
    events = [e for e in events if e["project_id"] == pid]
    problems = []
    for t in tasks:
        if t.overdue:
            problems.append({"type": "overdue", "text": f"Überfällig: „{t.title}“", "task_id": t.id})
        elif t.status == "waiting":
            problems.append({"type": "waiting", "text": f"Wartet: „{t.title}“", "task_id": t.id})
    if p.deadline and p.deadline < today and p.status not in ("completed", "archived"):
        problems.insert(0, {"type": "deadline", "text": "Die Projektdeadline ist überschritten."})
    open_tasks = [t for t in tasks if t.status != "done" and not t.parent_id]
    if p.status == "active" and not open_tasks:
        problems.append({"type": "empty", "text": "Keine offenen Aufgaben – nächste Schritte definieren."})
    if p.deadline and p.deadline >= today:
        est = sum((t.estimated_minutes or 0) for t in open_tasks)
        if not all(t.estimated_minutes for t in open_tasks):
            problems.append({"type": "estimate", "text": f"{sum(1 for t in open_tasks if not t.estimated_minutes)} offene Aufgabe(n) ohne Zeitschätzung."})
        days_left = (p.deadline - today).days
        if est and days_left <= 7 and est > days_left * 300:
            problems.append({"type": "risk", "text": f"Restaufwand ({round(est / 60)} h) ist bis zur Deadline kaum zu schaffen."})
    return {
        "project": work.project_out(db, [p], today)[0],
        "tasks": tasks,
        "events": events,
        "history": [{"ts": h.ts, "actor": h.actor, "action": h.action, "summary": h.summary} for h in history],
        "problems": problems,
    }


@router.patch("/projects/{pid}")
def patch_project(pid: int, data: ProjectPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return work.project_out(db, [work.update_project(db, pid, data)], _today(user))[0]


@router.delete("/projects/{pid}")
def remove_project(pid: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    work.delete_project(db, pid)
    return {"ok": True}


# ----------------------------------------------------------------- Aufgaben
@router.get("/tasks")
def tasks(
    status: str | None = Query(None, pattern=r"^[a-z_,]{1,80}$"),
    project_id: int | None = None,
    due_before: date | None = None,
    due_from: date | None = None,
    q: str | None = Query(None, max_length=100),
    parent_id: int | None = None,
    include_subtasks: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return work.task_out(db, work.list_tasks(db, status=status, project_id=project_id, due_before=due_before, due_from=due_from, q=q, parent_id=parent_id, include_subtasks=include_subtasks), _today(user))


@router.post("/tasks", status_code=201)
def create_task(data: TaskIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return work.task_out(db, [work.create_task(db, data)], _today(user))[0]


@router.get("/tasks/{tid}")
def task_detail(tid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = work.get_task(db, tid)
    today = _today(user)
    subtasks = work.task_out(db, list(db.scalars(select(Task).where(Task.parent_id == tid).order_by(Task.sort_order, Task.id))), today)
    return {"task": work.task_out(db, [t], today)[0], "subtasks": subtasks}


@router.patch("/tasks/{tid}")
def patch_task(tid: int, data: TaskPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return work.task_out(db, [work.update_task(db, tid, data)], _today(user))[0]


@router.post("/tasks/{tid}/complete")
def complete(tid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return work.task_out(db, [work.complete_task(db, tid)], _today(user))[0]


@router.delete("/tasks/{tid}")
def remove_task(tid: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    work.delete_task(db, tid)
    return {"ok": True}


# ----------------------------------------------------------------- Kategorien
@router.get("/categories")
def categories(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name, "color": c.color} for c in db.scalars(select(Category).order_by(Category.name))]


@router.post("/categories", status_code=201)
def create_category(data: CategoryIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.scalars(select(Category).where(Category.name == data.name)).first():
        raise HTTPException(400, "Kategorie existiert bereits.")
    c = Category(name=data.name.strip(), color=data.color)
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name, "color": c.color}


@router.patch("/categories/{cid}")
def update_category(cid: int, data: CategoryIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Kategorie nicht gefunden.")
    c.name, c.color = data.name.strip(), data.color
    db.commit()
    return {"id": c.id, "name": c.name, "color": c.color}


@router.delete("/categories/{cid}")
def delete_category(cid: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Kategorie nicht gefunden.")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------- Gedächtnis
@router.get("/memory", response_model=list[MemoryOut])
def memory_list(q: str | None = Query(None, max_length=200), category: str | None = None, project_id: int | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mem.search_memory(db, q, category, project_id, limit=300)


@router.post("/memory", response_model=MemoryOut, status_code=201)
def memory_create(data: MemoryIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mem.create_memory(db, data)


@router.patch("/memory/{mid}", response_model=MemoryOut)
def memory_patch(mid: int, data: MemoryPatch, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mem.update_memory(db, mid, data)


@router.delete("/memory/{mid}")
def memory_delete(mid: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    mem.delete_memory(db, mid)
    return {"ok": True}


# ----------------------------------------------------------------- Globale Suche
@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=100), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tz = ZoneInfo(user.timezone)
    now = datetime.now(timezone.utc)
    like = f"%{q}%"
    projects = db.scalars(select(Project).where(or_(Project.name.ilike(like), Project.description.ilike(like), Project.goal.ilike(like))).limit(8))
    tasks = db.scalars(select(Task).where(Task.status != "archived", or_(Task.title.ilike(like), Task.description.ilike(like))).order_by(Task.status == "done", Task.due_date).limit(10))
    events = list_occurrences(db, now - timedelta(days=90), now + timedelta(days=365), user.timezone, q=q)
    upcoming = [e for e in events if e["end"] >= now.isoformat()][:8] or events[-5:]
    memories = mem.search_memory(db, q, limit=5)
    return {
        "projects": [{"id": p.id, "name": p.name, "status": p.status, "color": p.color} for p in projects],
        "tasks": [{"id": t.id, "title": t.title, "status": t.status, "due_date": t.due_date, "project_id": t.project_id} for t in tasks],
        "events": [{"id": e["id"], "event_id": e["event_id"], "title": e["title"], "start": e["start"], "all_day": e["all_day"], "source": e["source"],
                    "date": datetime.fromisoformat(e["start"]).astimezone(tz).date().isoformat()} for e in upcoming],
        "memory": [{"id": m.id, "content": m.content[:140], "category": m.category} for m in memories],
    }


# ----------------------------------------------------------------- Aktivitäten
@router.get("/activity")
def activity(limit: int = Query(50, le=300), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.ts.desc()).limit(limit))
    return [{"id": r.id, "ts": r.ts, "actor": r.actor, "action": r.action, "summary": r.summary, "entity_type": r.entity_type, "entity_id": r.entity_id} for r in rows]
