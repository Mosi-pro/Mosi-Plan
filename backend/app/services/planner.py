"""Automatischer Wochenplaner.

Der Planer arbeitet deterministisch (kein Sprachmodell nötig) und hält sich an
harte Regeln: keine Überschneidungen, nur innerhalb der hinterlegten Arbeitszeiten
(unbekannte Verfügbarkeit = nicht frei), Pufferzeiten um Termine, Tageslimit für
Fokuszeit, Deadlines zuerst. Die KI kann den Entwurf anschließend kommentieren.
Ergebnis ist immer ein Entwurf; Kalendereinträge entstehen erst nach Freigabe.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CalendarEvent, Project, Task, User, WeeklyPlan, WeeklyPlanItem
from ..schemas import EventIn
from . import settings_store as st
from .audit import audit
from .calendar import create_internal_event, list_occurrences, local_midnight
from .overview import WEEKDAYS, fmt_date
from .work import PRIORITY_WEIGHT, project_out, list_projects

SLOT = 5  # Minutenraster


def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass
class Interval:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class DayState:
    day: date
    workday: bool
    free: list[Interval] = field(default_factory=list)
    planned_minutes: int = 0
    capacity: int = 0


def _subtract(free: list[Interval], busy: Interval) -> list[Interval]:
    out = []
    for f in free:
        if busy.end <= f.start or busy.start >= f.end:
            out.append(f)
            continue
        if busy.start > f.start:
            out.append(Interval(f.start, busy.start))
        if busy.end < f.end:
            out.append(Interval(busy.end, f.end))
    return [i for i in out if i.minutes >= 1]


def _ceil_slot(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    rem = dt.minute % SLOT
    return dt + timedelta(minutes=(SLOT - rem) % SLOT)


def _task_remaining(t: Task, default: int) -> tuple[int, bool]:
    if not t.estimated_minutes:
        return default, True
    rem = t.estimated_minutes - (t.actual_minutes or 0)
    return max(rem if rem > 0 else min(30, t.estimated_minutes), 15), False


def _score(t: Task, project_prio: str | None, week_start: date) -> float:
    s = PRIORITY_WEIGHT.get(t.priority, 2) * 10.0
    s += PRIORITY_WEIGHT.get(project_prio or "normal", 2) * 3
    if t.due_date:
        days_left = (t.due_date - week_start).days
        s += 40 if days_left < 0 else max(0, 30 - days_left * 2)
    if t.status == "in_progress":
        s += 5
    return s


def _scheduled_task_ids(db: Session, start: datetime, end: datetime) -> set[int]:
    rows = db.scalars(
        select(CalendarEvent.task_id).where(
            CalendarEvent.task_id.is_not(None), CalendarEvent.deleted.is_(False), CalendarEvent.start_at < end, CalendarEvent.end_at > start
        )
    )
    return {r for r in rows if r}


def _build_days(db: Session, user: User, cfg: dict, first: date, num_days: int, now: datetime) -> tuple[list[dict], list[DayState]]:
    """Freie Arbeitszeit pro Tag: Arbeitszeiten minus Termine (mit Puffer) und Pause."""
    tz = ZoneInfo(user.timezone)
    buffer = timedelta(minutes=int(cfg["buffer_minutes"]))
    min_block = int(cfg["min_block_minutes"])
    work_days = set(cfg["work_days"])
    start, end = local_midnight(first, tz), local_midnight(first + timedelta(days=num_days), tz)
    occurrences = list_occurrences(db, start, end, user.timezone)
    days: list[DayState] = []
    for i in range(num_days):
        d = first + timedelta(days=i)
        ds = DayState(day=d, workday=d.weekday() in work_days)
        if ds.workday:
            ws = datetime.combine(d, _hm(cfg["work_start"]), tzinfo=tz).astimezone(timezone.utc)
            we = datetime.combine(d, _hm(cfg["work_end"]), tzinfo=tz).astimezone(timezone.utc)
            ws = max(ws, _ceil_slot(now + timedelta(minutes=15)))
            ds.free = [Interval(ws, we)] if we > ws else []
            if cfg.get("lunch_start") and cfg.get("lunch_end"):
                ls = datetime.combine(d, _hm(cfg["lunch_start"]), tzinfo=tz).astimezone(timezone.utc)
                le = datetime.combine(d, _hm(cfg["lunch_end"]), tzinfo=tz).astimezone(timezone.utc)
                ds.free = _subtract(ds.free, Interval(ls, le))
        days.append(ds)
    for o in occurrences:
        if not o["busy"]:
            continue
        s_, e_ = datetime.fromisoformat(o["start"]), datetime.fromisoformat(o["end"])
        busy = Interval(s_, e_) if o["all_day"] else Interval(s_ - buffer, e_ + buffer)
        for ds in days:
            ds.free = _subtract(ds.free, busy)
    for ds in days:
        ds.free = [Interval(_ceil_slot(f.start), f.end) for f in ds.free]
        ds.free = [f for f in ds.free if f.minutes >= min_block]
        ds.capacity = min(sum(f.minutes for f in ds.free), int(cfg["max_focus_minutes_per_day"]))
    return occurrences, days


def free_slots(db: Session, user: User, first: date, last: date) -> list[Interval]:
    cfg = st.get_section(db, "planner")
    _, days = _build_days(db, user, cfg, first, (last - first).days + 1, datetime.now(timezone.utc))
    return [f for ds in days for f in ds.free]


def generate_plan(db: Session, user: User, week_start: date, generated_by: str = "user") -> WeeklyPlan:
    if week_start.weekday() != 0:
        week_start = week_start_of(week_start)
    cfg = st.get_section(db, "planner")
    tz = ZoneInfo(user.timezone)
    now = datetime.now(timezone.utc)
    w_start, w_end = local_midnight(week_start, tz), local_midnight(week_start + timedelta(days=7), tz)
    if w_end <= now:
        raise HTTPException(400, "Für vergangene Wochen kann kein Plan erstellt werden.")
    buffer = timedelta(minutes=int(cfg["buffer_minutes"]))
    max_block, min_block = int(cfg["max_block_minutes"]), int(cfg["min_block_minutes"])
    work_days = set(cfg["work_days"])

    occurrences, days = _build_days(db, user, cfg, week_start, 7, now)

    # ---------------- Aufgaben auswählen
    already = _scheduled_task_ids(db, w_start, w_end)
    candidates = list(db.scalars(select(Task).where(Task.status.in_(("open", "in_progress")))))
    parents_with_open_children = {t.parent_id for t in candidates if t.parent_id}
    projects = {p.id: p for p in db.scalars(select(Project))}
    status_by_id = {t.id: t.status for t in db.scalars(select(Task))}
    week_last = week_start + timedelta(days=6)
    pool, blocked, unscheduled, warnings = [], [], [], []
    for t in candidates:
        if t.id in already or t.id in parents_with_open_children:
            continue
        proj = projects.get(t.project_id) if t.project_id else None
        if proj and proj.status in ("paused", "archived", "completed"):
            continue
        open_deps = [d for d in (t.depends_on or []) if status_by_id.get(d) not in ("done", "archived", None)]
        # Aufgaben ohne Fälligkeit nur, wenn ihr Projekt aktiv ist oder sie hohe Priorität haben
        if not t.due_date and not (proj and proj.status == "active") and t.priority not in ("high", "critical"):
            continue
        if t.due_date and t.due_date > week_last + timedelta(days=21) and t.priority in ("low", "normal"):
            continue
        pool.append((t, open_deps, _score(t, proj.priority if proj else None, week_start), proj))
    pool.sort(key=lambda x: (-x[2], x[0].due_date or date(9999, 1, 1)))

    items: list[WeeklyPlanItem] = []
    planned_end: dict[int, datetime] = {}
    missing_estimates = []
    placed_ids: set[int] = set()

    def place(minutes: int, not_before: datetime | None, deadline: date | None, urgent: bool) -> Interval | None:
        order = sorted(days, key=lambda d: (d.day if urgent else (d.planned_minutes, d.day)))
        for ds in order:
            if deadline and ds.day > deadline:
                continue
            if ds.capacity - ds.planned_minutes < min(minutes, min_block):
                continue
            usable = min(minutes, ds.capacity - ds.planned_minutes)
            for idx, f in enumerate(ds.free):
                start = f.start
                if not_before and start < not_before:
                    start = _ceil_slot(not_before)
                if (f.end - start).total_seconds() / 60 < min(usable, min_block if minutes >= min_block else minutes):
                    continue
                length = min(usable, int((f.end - start).total_seconds() // 60))
                if length < minutes and length < min_block:
                    continue
                iv = Interval(start, start + timedelta(minutes=length))
                ds.free = _subtract(ds.free, Interval(iv.start, iv.end + buffer))
                ds.free = [x for x in ds.free if x.minutes >= min_block]
                ds.planned_minutes += length
                return iv
        return None

    for t, open_deps, score, proj in pool:
        if any(d not in placed_ids for d in open_deps):
            blocked.append({"task_id": t.id, "title": t.title, "reason": "Wartet auf abhängige Aufgaben"})
            continue
        remaining, missing = _task_remaining(t, int(cfg["default_task_minutes"]))
        if missing:
            missing_estimates.append(t.title)
        not_before = max((planned_end[d] for d in open_deps if d in planned_end), default=None)
        urgent = bool(t.due_date and t.due_date <= week_last)
        deadline = t.due_date if urgent and t.due_date >= week_start else None
        chunks_placed = 0
        while remaining > 0:
            chunk = min(remaining, max_block)
            iv = place(chunk, not_before, deadline, urgent)
            if iv is None and deadline:
                iv = place(chunk, not_before, None, urgent)
                if iv is not None:
                    warnings.append(f"„{t.title}“ kann erst nach der Deadline ({fmt_date(t.due_date)}) eingeplant werden.")
            if iv is None:
                break
            items.append(
                WeeklyPlanItem(task_id=t.id, project_id=t.project_id, title=t.title, priority=t.priority, start_at=iv.start, end_at=iv.end,
                               note="Teil " + str(chunks_placed + 1) if remaining > max_block or chunks_placed else "")
            )
            remaining -= iv.minutes
            chunks_placed += 1
            not_before = iv.end
            planned_end[t.id] = iv.end
        if chunks_placed:
            placed_ids.add(t.id)
        if remaining > 0:
            unscheduled.append({"task_id": t.id, "title": t.title, "minutes": remaining, "due_date": t.due_date.isoformat() if t.due_date else None,
                                "reason": "Nicht genug freie Arbeitszeit in dieser Woche" if chunks_placed == 0 else "Nur teilweise eingeplant"})
            if urgent:
                warnings.append(f"Deadline gefährdet: „{t.title}“ ({fmt_date(t.due_date)}) passt nicht vollständig in die verfügbare Zeit.")

    # ---------------- Zusatzinformationen
    today = now.astimezone(tz).date()
    prev_start = week_start - timedelta(days=7)
    carryover = [
        {"task_id": t.id, "title": t.title, "due_date": t.due_date.isoformat() if t.due_date else None, "priority": t.priority}
        for t in candidates if t.due_date and prev_start <= t.due_date < week_start
    ]
    prev_plan = db.scalars(select(WeeklyPlan).where(WeeklyPlan.week_start == prev_start, WeeklyPlan.status == "confirmed")).first()
    if prev_plan:
        for it in prev_plan.items:
            if it.task_id and status_by_id.get(it.task_id) in ("open", "in_progress") and not any(c["task_id"] == it.task_id for c in carryover):
                carryover.append({"task_id": it.task_id, "title": it.title, "due_date": None, "priority": it.priority})

    deadlines = sorted(
        [{"type": "task", "id": t.id, "title": t.title, "date": t.due_date.isoformat(), "priority": t.priority}
         for t in candidates if t.due_date and t.due_date <= week_last + timedelta(days=3) and (t.priority in ("high", "critical") or t.due_date <= week_last)]
        + [{"type": "project", "id": p.id, "title": p.name, "date": p.deadline.isoformat(), "priority": p.priority}
           for p in projects.values() if p.deadline and week_start <= p.deadline <= week_last + timedelta(days=7) and p.status in ("active", "planned")],
        key=lambda x: x["date"],
    )

    proj_minutes: dict[int | None, int] = {}
    proj_titles: dict[int | None, list[str]] = {}
    for it in items:
        proj_minutes[it.project_id] = proj_minutes.get(it.project_id, 0) + int((it.end_at - it.start_at).total_seconds() // 60)
        proj_titles.setdefault(it.project_id, [])
        if it.title not in proj_titles[it.project_id]:
            proj_titles[it.project_id].append(it.title)
    goals = []
    for pid, _ in sorted(proj_minutes.items(), key=lambda x: -x[1])[:3]:
        titles = proj_titles[pid][:2]
        name = projects[pid].name if pid in projects else "Allgemein"
        goals.append({"project_id": pid, "title": f"{name}: " + " und ".join(f"„{x}“" for x in titles) + " voranbringen"})

    total_capacity = sum(d.capacity for d in days)
    total_planned = sum(d.planned_minutes for d in days)
    recs = []
    if unscheduled:
        recs.append(f"{len(unscheduled)} Aufgabe(n) passen nicht in diese Woche. Prüfe Prioritäten oder verschiebe Deadlines.")
    if total_capacity and total_planned / total_capacity > 0.9:
        recs.append("Die Woche ist zu über 90 % verplant – plane bewusst Reserve für Unvorhergesehenes ein.")
    if missing_estimates:
        recs.append(f"Für {len(missing_estimates)} Aufgabe(n) fehlt eine Zeitschätzung; es wurden je {cfg['default_task_minutes']} Minuten angenommen.")
    if not work_days:
        recs.append("Es sind keine Arbeitstage hinterlegt. Bitte in den Planungsregeln festlegen.")
    stalled = [p for p in project_out(db, list_projects(db, status="active"), today) if p.task_open == 0 and p.status == "active"]
    for p in stalled[:3]:
        recs.append(f"Projekt „{p.name}“ ist aktiv, hat aber keine offenen Aufgaben – nächste Schritte definieren?")
    if carryover:
        recs.append(f"{len(carryover)} offene Aufgabe(n) aus der Vorwoche wurden berücksichtigt.")

    day_data = []
    for ds in days:
        evs = [
            {"title": o["title"], "start": o["start"], "end": o["end"], "all_day": o["all_day"], "source": o["source"]}
            for o in occurrences
            if datetime.fromisoformat(o["start"]).astimezone(tz).date() <= ds.day <= (datetime.fromisoformat(o["end"]) - timedelta(seconds=1)).astimezone(tz).date()
        ]
        day_data.append({
            "date": ds.day.isoformat(),
            "label": f"{WEEKDAYS[ds.day.weekday()]}, {ds.day.day}.{ds.day.month}.",
            "workday": ds.workday,
            "events": evs,
            "capacity_minutes": ds.capacity,
            "planned_minutes": ds.planned_minutes,
            "free_slots": [{"start": f.start.isoformat(), "end": f.end.isoformat()} for f in ds.free],
        })

    progress = [
        {"project_id": p.id, "name": p.name, "progress": p.progress, "open": p.task_open, "overdue": p.task_overdue, "color": p.color}
        for p in project_out(db, list_projects(db, status="active"), today)
    ]

    for old in db.scalars(select(WeeklyPlan).where(WeeklyPlan.week_start == week_start, WeeklyPlan.status == "draft")):
        old.status = "superseded"
    plan = WeeklyPlan(
        week_start=week_start,
        status="draft",
        generated_by=generated_by,
        data={
            "days": day_data,
            "goals": goals,
            "deadlines": deadlines,
            "carryover": carryover,
            "project_progress": progress,
            "recommendations": recs,
            "warnings": list(dict.fromkeys(warnings)),
            "unscheduled": unscheduled,
            "blocked": blocked,
            "stats": {"capacity_minutes": total_capacity, "planned_minutes": total_planned, "items": len(items)},
            "rules": {k: cfg[k] for k in ("work_start", "work_end", "buffer_minutes", "max_focus_minutes_per_day", "work_days")},
        },
    )
    plan.items = items
    db.add(plan)
    db.flush()
    audit(db, "weekly_plan.generate", f"Wochenplan-Entwurf für KW {week_start.isocalendar().week} erstellt ({len(items)} Blöcke)", actor="system" if generated_by == "schedule" else ("assistant" if generated_by == "assistant" else "user"), entity_type="weekly_plan", entity_id=plan.id, commit=False)
    db.commit()
    return plan


def get_plan(db: Session, plan_id: int) -> WeeklyPlan:
    p = db.get(WeeklyPlan, plan_id)
    if not p:
        raise HTTPException(404, "Wochenplan nicht gefunden.")
    return p


def serialize_plan(db: Session, plan: WeeklyPlan, user: User) -> dict:
    tz = ZoneInfo(user.timezone)
    projects = {p.id: p for p in db.scalars(select(Project))}
    tasks = {t.id: t for t in db.scalars(select(Task).where(Task.id.in_([i.task_id for i in plan.items if i.task_id])))} if plan.items else {}
    week_end = local_midnight(plan.week_start + timedelta(days=7), tz)
    items = []
    for it in plan.items:
        t = tasks.get(it.task_id) if it.task_id else None
        done = bool(t and t.status == "done" and t.completed_at and t.completed_at <= week_end + timedelta(days=1))
        items.append({
            "id": it.id, "task_id": it.task_id, "project_id": it.project_id,
            "project_name": projects[it.project_id].name if it.project_id in projects else None,
            "project_color": projects[it.project_id].color if it.project_id in projects else None,
            "title": it.title, "priority": it.priority, "start": it.start_at.isoformat(), "end": it.end_at.isoformat(),
            "date": it.start_at.astimezone(tz).date().isoformat(),
            "minutes": int((it.end_at - it.start_at).total_seconds() // 60),
            "status": it.status, "original_start": it.original_start_at.isoformat() if it.original_start_at else None,
            "event_id": it.event_id, "note": it.note, "task_status": t.status if t else None, "done": done,
        })
    # Auswertung: geplant / erledigt / verschoben / entfernt
    active = [i for i in items if i["status"] != "removed"]
    task_ids = {i["task_id"] for i in active if i["task_id"]}
    done_ids = {i["task_id"] for i in active if i["done"]}
    per_project: dict[str, dict] = {}
    for i in active:
        key = i["project_name"] or "Ohne Projekt"
        pp = per_project.setdefault(key, {"planned": 0, "done": 0})
        pp["planned"] += 1
        pp["done"] += 1 if i["done"] else 0
    review = {
        "planned_tasks": len(task_ids), "done_tasks": len(done_ids),
        "moved": sum(1 for i in items if i["status"] == "moved"), "removed": sum(1 for i in items if i["status"] == "removed"),
        "per_project": per_project,
    }
    return {
        "id": plan.id, "week_start": plan.week_start.isoformat(), "week_number": plan.week_start.isocalendar().week,
        "status": plan.status, "generated_by": plan.generated_by, "created_at": plan.created_at.isoformat(),
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
        "data": plan.data, "items": items, "review": review,
    }


def _require_editable(plan: WeeklyPlan) -> None:
    if plan.status not in ("draft", "confirmed"):
        raise HTTPException(400, "Dieser Wochenplan kann nicht mehr bearbeitet werden.")


def move_item(db: Session, user: User, item_id: int, new_start: datetime) -> tuple[WeeklyPlanItem, list[dict]]:
    it = db.get(WeeklyPlanItem, item_id)
    if not it:
        raise HTTPException(404, "Planeintrag nicht gefunden.")
    plan = it.plan
    _require_editable(plan)
    tz = ZoneInfo(user.timezone)
    if new_start.tzinfo is None:
        new_start = new_start.replace(tzinfo=tz)
    dur = it.end_at - it.start_at
    w_start, w_end = local_midnight(plan.week_start, tz), local_midnight(plan.week_start + timedelta(days=7), tz)
    if not (w_start <= new_start and new_start + dur <= w_end):
        raise HTTPException(400, "Der neue Zeitpunkt liegt außerhalb der Planwoche.")
    conflicts = [o for o in list_occurrences(db, new_start, new_start + dur, user.timezone) if o["busy"] and not o["all_day"] and o["event_id"] != it.event_id]
    others = [o for o in plan.items if o.id != it.id and o.status != "removed" and o.start_at < new_start + dur and o.end_at > new_start]
    if others:
        raise HTTPException(409, f"Überschneidung mit geplantem Block „{others[0].title}“.")
    if not it.original_start_at:
        it.original_start_at = it.start_at
    it.start_at, it.end_at, it.status = new_start.astimezone(timezone.utc), (new_start + dur).astimezone(timezone.utc), "moved"
    if it.event_id:
        ev = db.get(CalendarEvent, it.event_id)
        if ev and ev.source == "internal":
            ev.start_at, ev.end_at = it.start_at, it.end_at
    audit(db, "weekly_plan.move", f"Block „{it.title}“ verschoben", entity_type="weekly_plan", entity_id=plan.id, commit=False)
    db.commit()
    return it, conflicts


def remove_item(db: Session, item_id: int) -> None:
    it = db.get(WeeklyPlanItem, item_id)
    if not it:
        raise HTTPException(404, "Planeintrag nicht gefunden.")
    _require_editable(it.plan)
    it.status = "removed"
    if it.event_id:
        ev = db.get(CalendarEvent, it.event_id)
        if ev and ev.source == "internal":
            db.delete(ev)
        it.event_id = None
    db.commit()


def confirm_plan(db: Session, user: User, plan_id: int, push_to_google: bool = False) -> WeeklyPlan:
    plan = get_plan(db, plan_id)
    if plan.status != "draft":
        raise HTTPException(400, "Nur Entwürfe können freigegeben werden.")
    created = 0
    for it in plan.items:
        if it.status == "removed" or it.event_id:
            continue
        ev = create_internal_event(
            db,
            EventIn(title=it.title, start=it.start_at, end=it.end_at, task_id=it.task_id, project_id=it.project_id, notes="Aus dem Wochenplan", reminders=[]),
            user.timezone, actor="user", origin="weekly_plan", commit=False,
        )
        it.event_id = ev.id
        created += 1
    pushed = 0
    if push_to_google:
        from . import google_calendar as g

        if not g.is_connected(db):
            raise HTTPException(400, "Google Calendar ist nicht verbunden.")
        for it in plan.items:
            if it.status == "removed":
                continue
            g.create_remote_event(db, EventIn(title=it.title, start=it.start_at, end=it.end_at, notes="Geplant mit MOSI PLAN", target="google"), user.timezone)
            pushed += 1
    for other in db.scalars(select(WeeklyPlan).where(WeeklyPlan.week_start == plan.week_start, WeeklyPlan.status == "draft", WeeklyPlan.id != plan.id)):
        other.status = "superseded"
    plan.status = "confirmed"
    plan.confirmed_at = datetime.now(timezone.utc)
    audit(db, "weekly_plan.confirm", f"Wochenplan KW {plan.week_start.isocalendar().week} freigegeben: {created} Kalenderblöcke" + (f", {pushed} nach Google übertragen" if pushed else ""), entity_type="weekly_plan", entity_id=plan.id, commit=False)
    db.commit()
    return plan


def discard_plan(db: Session, plan_id: int) -> WeeklyPlan:
    plan = get_plan(db, plan_id)
    if plan.status != "draft":
        raise HTTPException(400, "Nur Entwürfe können verworfen werden.")
    plan.status = "discarded"
    audit(db, "weekly_plan.discard", f"Wochenplan-Entwurf KW {plan.week_start.isocalendar().week} verworfen", entity_type="weekly_plan", entity_id=plan.id, commit=False)
    db.commit()
    return plan
