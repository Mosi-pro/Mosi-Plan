import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import agent
from ..ai.tools import confirm_pending, reject_pending
from ..db import SessionLocal, get_db
from ..models import Conversation, Message, PendingAction, User
from ..schemas import ChatIn
from ..security import get_current_user, rate_limit
from ..services import work
from ..services.audit import audit

router = APIRouter(prefix="/api", tags=["assistant"])


@router.get("/assistant/status")
def status(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..services import settings_store as st

    cfg = st.get_section(db, "ai")
    ok, msg = agent.hermes_status(force=True)
    try:
        backend = agent.choose_backend(db)
        available, reason = True, None
    except agent.AIUnavailable as exc:
        backend, available, reason = None, False, str(exc)
    return {"mode": cfg["mode"], "hermes_ok": ok, "hermes_message": msg, "direct_configured": bool(agent.direct_config(db)),
            "available": available, "backend": backend, "reason": reason}


@router.get("/conversations")
def conversations(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Conversation).order_by(Conversation.updated_at.desc()).limit(100))
    return [{"id": c.id, "title": c.title, "updated_at": c.updated_at} for c in rows]


@router.post("/conversations", status_code=201)
def new_conversation(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = Conversation()
    db.add(c)
    db.commit()
    return {"id": c.id, "title": c.title, "updated_at": c.updated_at}


@router.get("/conversations/{cid}")
def conversation(cid: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404, "Gespräch nicht gefunden.")
    msgs = db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.id))
    actions = {p.id: p for p in db.scalars(select(PendingAction).where(PendingAction.conversation_id == cid))}
    out = []
    for m in msgs:
        meta = dict(m.meta or {})
        meta["actions"] = [
            {"id": a.id, "tool": a.tool, "description": a.description, "preview": a.preview, "status": a.status, "result": a.result}
            for a in (actions.get(i) for i in meta.get("pending_actions", [])) if a
        ]
        out.append({"id": m.id, "role": m.role, "content": m.content, "meta": meta, "created_at": m.created_at})
    return {"id": c.id, "title": c.title, "summary": c.summary, "messages": out}


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.patch("/conversations/{cid}")
def rename(cid: int, data: RenameIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404, "Gespräch nicht gefunden.")
    c.title = data.title
    db.commit()
    return {"ok": True}


@router.delete("/conversations/{cid}")
def delete_conversation(cid: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404, "Gespräch nicht gefunden.")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/conversations/{cid}/messages")
def send(cid: int, data: ChatIn, user: User = Depends(get_current_user)):
    rate_limit("chat", 30, 60)
    user_id = user.id

    def stream():
        db = SessionLocal()
        try:
            conv = db.get(Conversation, cid)
            if not conv:
                yield f"data: {json.dumps({'type': 'done', 'error': 'Gespräch nicht gefunden.'})}\n\n"
                return
            u = db.get(User, user_id)
            for ev in agent.run_turn(db, u, conv, data.content, data.via_voice):
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        finally:
            db.close()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ----------------------------------------------------------------- Bestätigungen
@router.get("/actions")
def actions(status: str = "pending", _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(PendingAction).where(PendingAction.status == status).order_by(PendingAction.created_at.desc()).limit(50))
    return [{"id": a.id, "tool": a.tool, "description": a.description, "preview": a.preview, "status": a.status, "created_at": a.created_at, "conversation_id": a.conversation_id} for a in rows]


@router.post("/actions/{aid}/confirm")
def confirm(aid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pa = confirm_pending(db, user, aid)
    if pa.status != "confirmed":
        raise HTTPException(400, (pa.result or {}).get("error") or "Die Aktion ist fehlgeschlagen.")
    return {"id": pa.id, "status": pa.status, "result": pa.result}


@router.post("/actions/{aid}/reject")
def reject(aid: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pa = reject_pending(db, aid)
    return {"id": pa.id, "status": pa.status}


# ----------------------------------------------------------------- Projekt-KI-Zusammenfassung
@router.post("/projects/{pid}/ai-summary")
def project_summary(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit("ai-summary", 10, 60)
    p = work.get_project(db, pid)
    today = datetime.now(timezone.utc).date()
    po = work.project_out(db, [p], today)[0]
    tasks = work.task_out(db, work.list_tasks(db, project_id=pid, status="open,in_progress,waiting,done"), today)
    facts = {
        "name": p.name, "ziel": p.goal, "status": p.status, "deadline": p.deadline, "fortschritt_prozent": po.progress,
        "offene_aufgaben": [{"titel": t.title, "status": t.status, "faellig": t.due_date, "prioritaet": t.priority, "ueberfaellig": t.overdue} for t in tasks if t.status != "done"][:40],
        "erledigt": [t.title for t in tasks if t.status == "done"][:20],
        "notizen": p.notes[:2000],
    }
    try:
        text = agent.complete_text(
            db,
            "Du bist MOSI, ein Projektassistent. Schreibe eine kurze Projekt-Zusammenfassung auf Deutsch (4–6 Sätze): Stand, Risiken, nächste sinnvolle Schritte. Nutze nur die gelieferten Fakten; benenne Unsicherheiten.",
            json.dumps(facts, ensure_ascii=False, default=str),
        )
    except agent.AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    if not text:
        raise HTTPException(502, "Die KI hat keine Zusammenfassung geliefert.")
    p.ai_summary, p.ai_summary_at = text, datetime.now(timezone.utc)
    db.commit()
    audit(db, "project.ai_summary", "KI-Zusammenfassung erstellt", actor="assistant", entity_type="project", entity_id=p.id, project_id=p.id)
    return {"summary": text, "at": p.ai_summary_at}
