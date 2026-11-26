import logging

from sqlalchemy.orm import Session

from ..models import AuditLog

log = logging.getLogger("mosi.audit")


def audit(
    db: Session,
    action: str,
    summary: str = "",
    *,
    actor: str = "user",
    entity_type: str = "",
    entity_id: int | None = None,
    project_id: int | None = None,
    data: dict | None = None,
    ip: str = "",
    commit: bool = True,
) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=project_id,
            summary=summary[:2000],
            data=data or {},
            ip=ip,
        )
    )
    log.info("%s %s %s#%s %s", actor, action, entity_type, entity_id, summary[:200])
    if commit:
        db.commit()
