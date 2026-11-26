from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import agent
from ..db import get_db
from ..models import User, WeeklyPlan
from ..security import get_current_user, rate_limit
from ..services import planner

router = APIRouter(prefix="/api/planner", tags=["planner"])


@router.get("/plans")
def plans(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(WeeklyPlan).where(WeeklyPlan.status != "superseded").order_by(WeeklyPlan.week_start.desc(), WeeklyPlan.created_at.desc()).limit(104))
    return [{"id": p.id, "week_start": p.week_start, "week_number": p.week_start.isocalendar().week, "status": p.status, "created_at": p.created_at,
             "items": len([i for i in p.items if i.status != "removed"]), "generated_by": p.generated_by} for p in rows]


@router.get("/current")
def current(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = datetime.now(ZoneInfo(user.timezone)).date()
    out = {}
    for key, ws in (("this_week", planner.week_start_of(today)), ("next_week", planner.week_start_of(today) + timedelta(days=7))):
        p = db.scalars(select(WeeklyPlan).where(WeeklyPlan.week_start == ws, WeeklyPlan.status.in_(("draft", "confirmed"))).order_by(WeeklyPlan.status == "draft", WeeklyPlan.created_at.desc())).first()
        out[key] = {"week_start": ws.isoformat(), "plan": planner.serialize_plan(db, p, user) if p else None}
    return out


class GenerateIn(BaseModel):
    week_start: date


@router.post("/generate")
def generate(data: GenerateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit("planner:generate", 10, 60)
    plan = planner.generate_plan(db, user, data.week_start, generated_by="user")
    return planner.serialize_plan(db, plan, user)


@router.get("/plans/{pid}")
def get_plan(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return planner.serialize_plan(db, planner.get_plan(db, pid), user)


class ConfirmIn(BaseModel):
    push_to_google: bool = False


@router.post("/plans/{pid}/confirm")
def confirm(pid: int, data: ConfirmIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return planner.serialize_plan(db, planner.confirm_plan(db, user, pid, data.push_to_google), user)


@router.post("/plans/{pid}/discard")
def discard(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return planner.serialize_plan(db, planner.discard_plan(db, pid), user)


@router.post("/plans/{pid}/regenerate")
def regenerate(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    old = planner.get_plan(db, pid)
    if old.status != "draft":
        raise HTTPException(400, "Nur Entwürfe können neu generiert werden.")
    plan = planner.generate_plan(db, user, old.week_start, generated_by="user")
    return planner.serialize_plan(db, plan, user)


class MoveIn(BaseModel):
    start: datetime


@router.post("/items/{item_id}/move")
def move(item_id: int, data: MoveIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    it, conflicts = planner.move_item(db, user, item_id, data.start)
    return {"plan": planner.serialize_plan(db, it.plan, user), "conflicts": conflicts}


@router.delete("/items/{item_id}")
def remove(item_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..models import WeeklyPlanItem

    it = db.get(WeeklyPlanItem, item_id)
    if not it:
        raise HTTPException(404, "Planeintrag nicht gefunden.")
    plan_id = it.plan_id
    planner.remove_item(db, item_id)
    return planner.serialize_plan(db, planner.get_plan(db, plan_id), user)


@router.post("/plans/{pid}/ai-notes")
def ai_notes(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit("planner:ai", 6, 60)
    plan = planner.get_plan(db, pid)
    data = planner.serialize_plan(db, plan, user)
    import json

    facts = {"woche": data["week_start"], "bloecke": [{"titel": i["title"], "tag": i["date"], "minuten": i["minutes"], "projekt": i["project_name"]} for i in data["items"] if i["status"] != "removed"],
             "deadlines": plan.data.get("deadlines"), "warnungen": plan.data.get("warnings"), "nicht_eingeplant": plan.data.get("unscheduled"), "statistik": plan.data.get("stats")}
    try:
        text = agent.complete_text(db, "Du bist MOSI. Gib 3–5 knappe, konkrete Empfehlungen auf Deutsch zu diesem Wochenplan-Entwurf (Stichpunkte). Nur auf Basis der Fakten; nichts erfinden.", json.dumps(facts, ensure_ascii=False, default=str))
    except agent.AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    d = dict(plan.data)
    d["ai_notes"] = text
    plan.data = d
    db.commit()
    return {"ai_notes": text}
