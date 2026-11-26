import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User, UserSession
from ..schemas import LoginIn, PasswordChangeIn, ProfileIn, UserOut
from ..security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    client_ip,
    create_session,
    destroy_session,
    get_current_session,
    get_current_user,
    hash_password,
    limiter,
    rate_limit,
    validate_password_strength,
    verify_password,
)
from ..services.audit import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Konstanter Dummy-Hash gegen Timing-Angriffe auf Benutzernamen
_DUMMY = hash_password("mosi-dummy-password-0")


def _user_out(u: User) -> UserOut:
    out = UserOut.model_validate(u)
    out.has_avatar = bool(u.avatar_path)
    return out


def _set_cookies(resp: Response, token: str, csrf: str) -> None:
    s = get_settings()
    max_age = s.session_days * 86400
    resp.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=s.cookie_secure, samesite="strict", path="/")
    resp.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=s.cookie_secure, samesite="strict", path="/")


@router.post("/login")
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    rate_limit(f"login:ip:{ip}", 10, 300)
    rate_limit(f"login:user:{data.username.lower()}", 20, 3600)
    user = db.scalars(select(User).where(User.username == data.username.strip())).first()
    ok = verify_password(user.password_hash if user else _DUMMY, data.password) and user is not None
    if not ok:
        audit(db, "auth.login_failed", f"Fehlgeschlagene Anmeldung für „{data.username[:64]}“", actor="system", ip=ip)
        raise HTTPException(401, "Benutzername oder Passwort ist falsch.")
    limiter.reset(f"login:ip:{ip}")
    token, sess = create_session(db, user, request.headers.get("user-agent", ""), ip)
    _set_cookies(response, token, sess.csrf_token)
    audit(db, "auth.login", "Anmeldung erfolgreich", ip=ip)
    return {"user": _user_out(user), "csrf_token": sess.csrf_token}


@router.post("/logout")
def logout(request: Request, response: Response, _: UserSession = Depends(get_current_session), db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        destroy_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    audit(db, "auth.logout", "Abgemeldet", ip=client_ip(request))
    return {"ok": True}


@router.get("/me")
def me(sess: UserSession = Depends(get_current_session), db: Session = Depends(get_db)):
    user = db.get(User, sess.user_id)
    return {"user": _user_out(user), "csrf_token": sess.csrf_token}


@router.patch("/profile")
def update_profile(data: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(user, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    audit(db, "profile.update", "Profil aktualisiert")
    return _user_out(user)


@router.post("/password")
def change_password(data: PasswordChangeIn, request: Request, response: Response, sess: UserSession = Depends(get_current_session), db: Session = Depends(get_db)):
    rate_limit(f"pw:{sess.user_id}", 5, 900)
    user = db.get(User, sess.user_id)
    if not verify_password(user.password_hash, data.current_password):
        raise HTTPException(400, "Das aktuelle Passwort ist falsch.")
    validate_password_strength(data.new_password)
    user.password_hash = hash_password(data.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    # Alle anderen Sitzungen beenden
    db.execute(delete(UserSession).where(UserSession.user_id == user.id, UserSession.id != sess.id))
    db.commit()
    audit(db, "auth.password_changed", "Passwort geändert, andere Sitzungen beendet", ip=client_ip(request))
    return {"ok": True}


@router.get("/sessions")
def list_sessions(sess: UserSession = Depends(get_current_session), db: Session = Depends(get_db)):
    rows = db.scalars(select(UserSession).where(UserSession.user_id == sess.user_id).order_by(UserSession.last_seen_at.desc()))
    return [
        {"id": s.id[:12], "current": s.id == sess.id, "created_at": s.created_at, "last_seen_at": s.last_seen_at, "user_agent": s.user_agent, "ip": s.ip}
        for s in rows
    ]


@router.delete("/sessions/{sid}")
def revoke_session(sid: str, sess: UserSession = Depends(get_current_session), db: Session = Depends(get_db)):
    if len(sid) < 8:
        raise HTTPException(400, "Ungültige Sitzung.")
    for s in db.scalars(select(UserSession).where(UserSession.user_id == sess.user_id)):
        if s.id.startswith(sid) and s.id != sess.id:
            db.delete(s)
            db.commit()
            audit(db, "auth.session_revoked", "Sitzung beendet")
            return {"ok": True}
    raise HTTPException(404, "Sitzung nicht gefunden.")


ALLOWED_IMAGE = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg", b"RIFF": "webp"}


@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = await file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(413, "Profilbild darf höchstens 2 MB groß sein.")
    ext = next((e for magic, e in ALLOWED_IMAGE.items() if data.startswith(magic)), None)
    if ext == "webp" and data[8:12] != b"WEBP":
        ext = None
    if not ext:
        raise HTTPException(400, "Nur PNG, JPEG oder WebP sind erlaubt.")
    folder = os.path.join(get_settings().data_dir, "uploads")
    os.makedirs(folder, exist_ok=True)
    for old in os.listdir(folder):
        if old.startswith("avatar."):
            os.remove(os.path.join(folder, old))
    path = os.path.join(folder, f"avatar.{ext}")
    with open(path, "wb") as fh:
        fh.write(data)
    user.avatar_path = path
    db.commit()
    return _user_out(user)


@router.delete("/avatar")
def delete_avatar(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.avatar_path and os.path.exists(user.avatar_path):
        os.remove(user.avatar_path)
    user.avatar_path = None
    db.commit()
    return _user_out(user)


@router.get("/avatar")
def get_avatar(user: User = Depends(get_current_user)):
    if not user.avatar_path or not os.path.exists(user.avatar_path):
        raise HTTPException(404, "Kein Profilbild.")
    return FileResponse(user.avatar_path, headers={"Cache-Control": "private, max-age=300"})
