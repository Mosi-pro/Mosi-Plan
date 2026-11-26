"""Persistente Anwendungseinstellungen (JSON in app_settings).

Secrets (API-Schlüssel, Tokens, Webhooks) werden mit dem Server-SECRET_KEY
verschlüsselt gespeichert und nie an das Frontend ausgeliefert.
"""
import copy
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AppSetting
from ..security import decrypt_secret, encrypt_secret

DEFAULTS: dict[str, dict[str, Any]] = {
    "ai": {
        "mode": "hermes",  # hermes | direct | off
        "fallback_direct": True,  # bei nicht erreichbarem Hermes direkten Anbieter nutzen
        "direct_base_url": "",
        "direct_model": "",
        "memory_enabled": True,
        "memory_auto_save": False,  # Assistent speichert nur nach Rückfrage/explizitem Auftrag
        "temperature": 0.3,
    },
    "voice": {
        "stt_enabled": True,
        "stt_provider": "browser",  # browser | server
        "stt_base_url": "",
        "stt_model": "whisper-1",
        "stt_language": "de",
        "tts_enabled": True,
        "tts_provider": "browser",  # browser | server
        "tts_voice_name": "",  # Name der Browser-Stimme (z. B. eine männliche deutsche Stimme)
        "tts_rate": 1.0,
        "tts_base_url": "",
        "tts_model": "tts-1",
        "tts_voice": "onyx",
        "auto_speak": True,
    },
    "calendar": {
        "default_reminders": [15],
        "google_sync_minutes": 10,
        "google_write_calendar_id": "",
        "default_view": "week",
        "week_starts_monday": True,
    },
    "planner": {
        "enabled": True,
        "weekday": 6,  # 0=Montag … 6=Sonntag
        "time": "18:00",
        "work_days": [0, 1, 2, 3, 4],
        "work_start": "09:00",
        "work_end": "17:30",
        "lunch_start": "12:30",
        "lunch_end": "13:15",
        "buffer_minutes": 15,
        "max_focus_minutes_per_day": 300,
        "max_block_minutes": 120,
        "min_block_minutes": 30,
        "default_task_minutes": 60,
        "push_to_google": False,
        "rules_text": "",
    },
    "notifications": {
        "in_app": True,
        "browser": True,
        "push": False,
        "discord": False,
        "event_reminder_minutes": 15,
        "daily_digest_time": "07:30",
        "deadline_days_before": 2,
        "types": {
            "event_upcoming": True,
            "task_overdue": True,
            "project_deadline": True,
            "weekly_plan": True,
            "ai_hint": True,
            "sync_error": True,
        },
    },
    "dashboard": {
        "greeting_name": "",
        "widgets": [
            {"id": "summary", "visible": True},
            {"id": "today_events", "visible": True},
            {"id": "today_tasks", "visible": True},
            {"id": "overdue", "visible": True},
            {"id": "deadlines", "visible": True},
            {"id": "projects", "visible": True},
            {"id": "upcoming", "visible": True},
        ],
    },
    "google": {"client_id": "", "connected_email": "", "last_sync_at": None, "last_error": None},
}

# Schlüssel, deren Werte verschlüsselt im Secret-Bereich liegen
SECRET_KEYS = {
    "ai.direct_api_key",
    "voice.stt_api_key",
    "voice.tts_api_key",
    "notifications.discord_webhook",
    "google.client_secret",
    "google.tokens",
}


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def get_section(db: Session, section: str) -> dict[str, Any]:
    row = db.get(AppSetting, section)
    value = row.value if row and isinstance(row.value, dict) else {}
    merged = _deep_merge(DEFAULTS.get(section, {}), value)
    if section == "ai":
        env = get_settings()
        if not merged["direct_base_url"] and env.ai_direct_base_url:
            merged["direct_base_url"] = env.ai_direct_base_url
        if not merged["direct_model"] and env.ai_direct_model:
            merged["direct_model"] = env.ai_direct_model
    if section == "google" and not merged.get("client_id"):
        merged["client_id"] = get_settings().google_client_id
    return merged


def update_section(db: Session, section: str, patch: dict[str, Any]) -> dict[str, Any]:
    if section not in DEFAULTS:
        raise KeyError(section)
    row = db.get(AppSetting, section)
    current = row.value if row and isinstance(row.value, dict) else {}
    allowed = {k: v for k, v in patch.items() if k in DEFAULTS[section]}
    new = _deep_merge(current, allowed)
    if row:
        row.value = new
    else:
        db.add(AppSetting(key=section, value=new))
    db.commit()
    return get_section(db, section)


def get_secret(db: Session, name: str) -> str:
    assert name in SECRET_KEYS, name
    row = db.get(AppSetting, f"secret:{name}")
    if row and isinstance(row.value, str) and row.value:
        return decrypt_secret(row.value)
    env = get_settings()
    fallback = {
        "ai.direct_api_key": env.ai_direct_api_key,
        "google.client_secret": env.google_client_secret,
    }
    return fallback.get(name, "")


def set_secret(db: Session, name: str, value: str | None) -> None:
    assert name in SECRET_KEYS, name
    key = f"secret:{name}"
    row = db.get(AppSetting, key)
    if not value:
        if row:
            db.delete(row)
    else:
        enc = encrypt_secret(value)
        if row:
            row.value = enc
        else:
            db.add(AppSetting(key=key, value=enc))
    db.commit()


def has_secret(db: Session, name: str) -> bool:
    return bool(get_secret(db, name))


def get_raw(db: Session, key: str) -> Any:
    row = db.get(AppSetting, key)
    return row.value if row else None


def set_raw(db: Session, key: str, value: Any) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()
