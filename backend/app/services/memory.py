"""Persönliches Gedächtnis mit deutscher Volltextsuche (PostgreSQL FTS).

Sensible Daten (Passwörter, Kartennummern, IBAN, API-Schlüssel) werden nicht
gespeichert – der Filter lehnt solche Inhalte ab.
"""
import re

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import MemoryEntry, Project
from ..schemas import MemoryIn, MemoryPatch
from .audit import audit

CATEGORY_LABEL = {
    "project": "Projektinformation",
    "decision": "Entscheidung",
    "planning_rule": "Planungsregel",
    "recurring": "Wiederkehrende Aufgabe",
    "goal": "Langfristiges Ziel",
    "note": "Notiz",
    "preference": "Vorliebe",
}

_SENSITIVE = [
    re.compile(r"\b(passwor(t|d)|kennwort|pin|tan|cvv|cvc)\b\s*[:=]?\s*\S{3,}", re.I),
    re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b"),  # IBAN
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),  # Kartennummer
    re.compile(r"\b(sk|pk|rk)[-_][A-Za-z0-9_-]{16,}\b"),  # API-Keys
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def check_sensitive(text: str) -> None:
    for pat in _SENSITIVE:
        if pat.search(text):
            raise HTTPException(400, "Der Inhalt sieht nach sensiblen Daten aus (z. B. Passwort, IBAN, Kartennummer, API-Schlüssel) und wird nicht gespeichert.")


def create_memory(db: Session, data: MemoryIn, source: str = "user", actor: str = "user") -> MemoryEntry:
    check_sensitive(data.content)
    if data.project_id is not None and not db.get(Project, data.project_id):
        raise HTTPException(400, "Projekt existiert nicht.")
    m = MemoryEntry(**data.model_dump(), source=source)
    db.add(m)
    db.flush()
    audit(db, "memory.create", f"Gedächtniseintrag gespeichert ({CATEGORY_LABEL.get(m.category, m.category)})", actor=actor, entity_type="memory", entity_id=m.id, project_id=m.project_id, commit=False)
    db.commit()
    return m


def update_memory(db: Session, memory_id: int, patch: MemoryPatch) -> MemoryEntry:
    m = db.get(MemoryEntry, memory_id)
    if not m:
        raise HTTPException(404, "Eintrag nicht gefunden.")
    changes = patch.model_dump(exclude_unset=True)
    if "content" in changes:
        check_sensitive(changes["content"])
    if changes.get("project_id") is not None and not db.get(Project, changes["project_id"]):
        raise HTTPException(400, "Projekt existiert nicht.")
    for k, v in changes.items():
        setattr(m, k, v)
    audit(db, "memory.update", "Gedächtniseintrag bearbeitet", entity_type="memory", entity_id=m.id, commit=False)
    db.commit()
    return m


def delete_memory(db: Session, memory_id: int) -> None:
    m = db.get(MemoryEntry, memory_id)
    if not m:
        raise HTTPException(404, "Eintrag nicht gefunden.")
    db.delete(m)
    audit(db, "memory.delete", "Gedächtniseintrag gelöscht", entity_type="memory", entity_id=memory_id, commit=False)
    db.commit()


def search_memory(db: Session, query: str | None = None, category: str | None = None, project_id: int | None = None, limit: int = 50) -> list[MemoryEntry]:
    stmt = select(MemoryEntry)
    if category:
        stmt = stmt.where(MemoryEntry.category == category)
    if project_id is not None:
        stmt = stmt.where(MemoryEntry.project_id == project_id)
    if query and query.strip():
        q = query.strip()
        tsq = func.websearch_to_tsquery("german", q)
        vec = func.to_tsvector("german", MemoryEntry.content)
        # Volltext ODER Teilwort-Treffer (für kurze Begriffe / Namen)
        words = [w for w in re.split(r"\s+", q) if len(w) >= 3][:6]
        conds = [vec.op("@@")(tsq)] + [MemoryEntry.content.ilike(f"%{w}%") for w in words]
        stmt = stmt.where(or_(*conds)).order_by(MemoryEntry.pinned.desc(), func.ts_rank(vec, tsq).desc(), MemoryEntry.updated_at.desc())
    else:
        stmt = stmt.order_by(MemoryEntry.pinned.desc(), MemoryEntry.updated_at.desc())
    return list(db.scalars(stmt.limit(limit)))
