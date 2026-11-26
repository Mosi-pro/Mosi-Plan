"""Authentifizierung, Sessions, CSRF, Rate-Limiting und Secret-Verschlüsselung."""
import base64
import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User, UserSession

SESSION_COOKIE = "mosi_session"
CSRF_COOKIE = "mosi_csrf"
CSRF_HEADER = "X-CSRF-Token"

# Argon2id mit OWASP-konformen Parametern (m=19 MiB, t=2, p=1)
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(400, "Das Passwort muss mindestens 10 Zeichen lang sein.")
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        raise HTTPException(400, "Das Passwort braucht Groß- und Kleinbuchstaben sowie mindestens eine Ziffer.")


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, user_agent: str, ip: str) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    sess = UserSession(
        id=_token_id(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(24),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=get_settings().session_days),
        user_agent=user_agent[:255],
        ip=ip[:64],
    )
    db.add(sess)
    db.commit()
    return token, sess


def destroy_session(db: Session, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.id == _token_id(token)))
    db.commit()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return fwd or (request.client.host if request.client else "")


def get_current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Nicht angemeldet.")
    sess = db.get(UserSession, _token_id(token))
    now = datetime.now(timezone.utc)
    if not sess or sess.expires_at < now:
        raise HTTPException(401, "Sitzung abgelaufen. Bitte erneut anmelden.")
    # CSRF-Schutz (Double-Submit mit serverseitig gespeichertem Token) für schreibende Methoden
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        header = request.headers.get(CSRF_HEADER, "")
        if not header or not secrets.compare_digest(header, sess.csrf_token):
            raise HTTPException(403, "Ungültiges CSRF-Token. Bitte Seite neu laden.")
    if (now - sess.last_seen_at).total_seconds() > 300:
        sess.last_seen_at = now
        db.commit()
    return sess


def get_current_user(sess: UserSession = Depends(get_current_session), db: Session = Depends(get_db)) -> User:
    user = db.get(User, sess.user_id)
    if not user:
        raise HTTPException(401, "Benutzer nicht gefunden.")
    return user


def get_owner(db: Session) -> User:
    """Der (einzige) Benutzer – für Hintergrundjobs und den Agenten."""
    user = db.scalars(select(User).order_by(User.id)).first()
    if not user:
        raise RuntimeError("Kein Benutzer eingerichtet. Bitte 'create-admin' ausführen.")
    return user


# ---------------------------------------------------------------- Rate-Limiting
class RateLimiter:
    """Einfacher In-Memory-Sliding-Window-Limiter (eine Backend-Instanz)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: int) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


limiter = RateLimiter()


def rate_limit(key: str, limit: int, window_s: int) -> None:
    if not limiter.check(key, limit, window_s):
        raise HTTPException(429, "Zu viele Anfragen. Bitte kurz warten.")


# ---------------------------------------------------------------- Secret-Verschlüsselung
def _fernet() -> Fernet:
    key = get_settings().secret_key
    if not key:
        raise RuntimeError("SECRET_KEY ist nicht gesetzt.")
    digest = hashlib.sha256(("mosi-secrets:" + key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ""
