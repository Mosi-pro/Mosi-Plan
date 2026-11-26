"""Gedächtnis, Benachrichtigungen, Sprache, Einstellungen, System."""
from datetime import date, datetime, timedelta, timezone

import httpx


# ----------------------------------------------------------------- Gedächtnis
def test_memory_crud_and_search(client):
    pid = client.post("/api/projects", json={"name": "TSVH Wassersport"}).json()["id"]
    m = client.post("/api/memory", json={"content": "Entscheidung: Die Regatta-Planung übernimmt der Verein.", "category": "decision", "project_id": pid})
    assert m.status_code == 201
    mid = m.json()["id"]
    assert m.json()["source"] == "user"
    client.post("/api/memory", json={"content": "Freitags nur bis 14 Uhr arbeiten", "category": "planning_rule"})
    # Deutsche Stammformen: "Entscheidungen" findet "Entscheidung"
    assert client.get("/api/memory", params={"q": "Entscheidungen"}).json()[0]["id"] == mid
    assert len(client.get("/api/memory", params={"project_id": pid}).json()) == 1
    assert client.patch(f"/api/memory/{mid}", json={"pinned": True}).json()["pinned"]
    assert client.post("/api/memory", json={"content": "IBAN DE89 3704 0044 0532 0130 00"}).status_code == 400
    assert client.delete(f"/api/memory/{mid}").status_code == 200
    assert client.get("/api/memory", params={"q": "Regatta"}).json() == []


# ----------------------------------------------------------------- Benachrichtigungen
def test_event_reminder_and_dedupe(client, db, user):
    from app.services.notifications import run_checks

    start = datetime.now(timezone.utc) + timedelta(minutes=10)
    client.post("/api/events", json={"title": "Call", "start": start.isoformat(), "reminders": [15]})
    assert run_checks(db, user) >= 1
    assert run_checks(db, user) == 0  # keine Doppelmeldung
    n = client.get("/api/notifications").json()
    assert n["unread"] >= 1 and any(i["title"] == "Call" for i in n["items"])
    client.post("/api/notifications/read-all")
    assert client.get("/api/notifications").json()["unread"] == 0


def test_overdue_digest_and_type_filter(client, db, user):
    from app.services import settings_store as st
    from app.services.notifications import run_checks

    st.update_section(db, "notifications", {"daily_digest_time": "00:00"})
    client.post("/api/tasks", json={"title": "Alt", "due_date": (date.today() - timedelta(days=2)).isoformat()})
    run_checks(db, user)
    assert any(i["type"] == "task_overdue" for i in client.get("/api/notifications").json()["items"])
    st.update_section(db, "notifications", {"types": {"project_deadline": False}})
    client.post("/api/projects", json={"name": "P", "deadline": date.today().isoformat()})
    run_checks(db, user)
    assert not any(i["type"] == "project_deadline" for i in client.get("/api/notifications").json()["items"])


def test_discord_webhook(client, monkeypatch):
    assert client.put("/api/settings/notifications", json={"discord_webhook": "https://evil.example/hook"}).status_code == 400
    assert client.put("/api/settings/notifications", json={"discord_webhook": "https://discord.com/api/webhooks/1/abc", "discord": True}).status_code == 200
    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent.update(url=url, json=json)
        return httpx.Response(204)

    monkeypatch.setattr("app.services.notifications.httpx.post", fake_post)
    assert client.post("/api/notifications/test", json={"channel": "discord"}).status_code == 200
    assert sent["url"].startswith("https://discord.com/api/webhooks/") and "MOSI PLAN" in sent["json"]["content"]
    assert sent["json"]["allowed_mentions"] == {"parse": []}


def test_push_subscription_and_vapid(client):
    key = client.get("/api/push/vapid-key").json()["public_key"]
    assert len(key) > 80
    assert client.get("/api/push/vapid-key").json()["public_key"] == key
    r = client.post("/api/push/subscribe", json={"endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}})
    assert r.status_code == 200
    assert client.post("/api/push/subscribe", json={"endpoint": "http://insecure", "keys": {"p256dh": "x", "auth": "y"}}).status_code == 422
    assert client.post("/api/push/unsubscribe", json={"endpoint": "https://push.example/abc"}).status_code == 200


# ----------------------------------------------------------------- Sprache
def test_voice_not_configured(client):
    r = client.post("/api/voice/transcribe", files={"file": ("a.webm", b"123", "audio/webm")})
    assert r.status_code == 400 and "konfiguriert" in r.json()["detail"]
    assert client.post("/api/voice/speak", json={"text": "Hallo"}).status_code == 400


def test_voice_server_providers(client, monkeypatch):
    client.put("/api/settings/voice", json={"stt_provider": "server", "stt_base_url": "http://stt.local/v1", "tts_provider": "server", "tts_base_url": "http://tts.local/v1"})
    assert client.post("/api/voice/transcribe", files={"file": ("a.txt", b"123", "text/plain")}).status_code == 400

    class FakeAsync:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, files=None, data=None):
            assert url == "http://stt.local/v1/audio/transcriptions" and data["language"] == "de"
            return httpx.Response(200, json={"text": " Plane meine kommende Woche. "})

    monkeypatch.setattr("app.routers.system.httpx.AsyncClient", FakeAsync)
    r = client.post("/api/voice/transcribe", files={"file": ("a.webm", b"audio", "audio/webm;codecs=opus")})
    assert r.json()["text"] == "Plane meine kommende Woche."

    def fake_post(url, headers=None, timeout=None, json=None):
        assert json["voice"] == "onyx" and json["input"] == "Hallo"
        return httpx.Response(200, content=b"ID3mp3", headers={"content-type": "audio/mpeg"})

    monkeypatch.setattr("app.routers.system.httpx.post", fake_post)
    r = client.post("/api/voice/speak", json={"text": "Hallo"})
    assert r.status_code == 200 and r.content == b"ID3mp3"


# ----------------------------------------------------------------- Einstellungen & System
def test_settings_validation(client):
    assert client.put("/api/settings/planner", json={"work_start": "25:00"}).status_code == 400
    assert client.put("/api/settings/planner", json={"buffer_minutes": 500}).status_code == 400
    assert client.put("/api/settings/voice", json={"tts_rate": 5}).status_code == 400
    assert client.put("/api/settings/unknown", json={}).status_code == 404
    r = client.put("/api/settings/dashboard", json={"greeting_name": "Mosi", "widgets": [{"id": "projects", "visible": False}]})
    assert r.json()["greeting_name"] == "Mosi"
    assert client.get("/api/overview").json()["name"] == "Mosi"


def test_system_status_and_export(client):
    client.post("/api/projects", json={"name": "Private Projekte"})
    s = client.get("/api/system/status").json()
    assert s["database"]["ok"] and s["counts"]["projects"] == 1
    assert s["storage"]["limit"] == 30 * 1024**3 and s["storage"]["level"] == "ok"
    r = client.get("/api/system/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["projects"][0]["name"] == "Private Projekte"
    assert "password_hash" not in r.text


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.json()["status"] == "ok"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
