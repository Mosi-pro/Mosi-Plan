"""Google-Calendar-Integration gegen einen simulierten Google-Server (httpx.MockTransport)."""
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services import google_calendar as g


class FakeGoogle:
    def __init__(self):
        self.events = {
            "evt1": {"id": "evt1", "etag": '"1"', "status": "confirmed", "summary": "Kundentermin", "start": {"dateTime": "2026-12-03T10:00:00+01:00", "timeZone": "Europe/Berlin"}, "end": {"dateTime": "2026-12-03T11:00:00+01:00"}},
            "evt2": {"id": "evt2", "etag": '"1"', "status": "confirmed", "summary": "Feiertag", "transparency": "transparent", "start": {"date": "2026-12-25"}, "end": {"date": "2026-12-26"}},
        }
        self.refresh_fails = False
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        url = str(request.url)
        if url.startswith(g.TOKEN_URL):
            body = parse_qs(request.content.decode())
            if body.get("grant_type") == ["authorization_code"]:
                return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
            if self.refresh_fails:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "at2", "expires_in": 3600})
        if url.startswith(g.REVOKE_URL):
            return httpx.Response(200)
        assert request.headers["Authorization"].startswith("Bearer ")
        path = request.url.path.replace("/calendar/v3", "")
        if path == "/users/me/calendarList":
            return httpx.Response(200, json={"items": [
                {"id": "me@example.com", "summary": "Privat", "primary": True, "accessRole": "owner", "backgroundColor": "#123456"},
                {"id": "feiertage", "summary": "Feiertage", "accessRole": "reader"}]})
        if path.startswith("/calendars/me%40example.com/events") or path.startswith("/calendars/me@example.com/events"):
            parts = path.split("/events")
            if request.method == "GET":
                return httpx.Response(200, json={"items": list(self.events.values())})
            if request.method == "POST":
                body = json.loads(request.content)
                body.update(id="new1", etag='"1"', status="confirmed")
                self.events["new1"] = body
                return httpx.Response(200, json=body)
            eid = parts[1].strip("/")
            if request.headers.get("If-Match") and request.headers["If-Match"] != self.events[eid]["etag"]:
                return httpx.Response(412)
            if request.method == "PATCH":
                body = json.loads(request.content)
                self.events[eid].update(body)
                self.events[eid]["etag"] = '"2"'
                return httpx.Response(200, json=self.events[eid])
            if request.method == "DELETE":
                self.events.pop(eid)
                return httpx.Response(204)
        return httpx.Response(404)


@pytest.fixture
def fake(monkeypatch):
    f = FakeGoogle()
    monkeypatch.setattr(g, "TRANSPORT", httpx.MockTransport(f.handler))
    return f


def connect(client):
    r = client.put("/api/google/credentials", json={"client_id": "abc.apps.googleusercontent.com", "client_secret": "geheim"})
    assert r.status_code == 200
    url = client.get("/api/google/auth-url").json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"] == ["https://mosi.test/api/google/callback"]
    assert q["access_type"] == ["offline"] and "calendar" in q["scope"][0]
    r = client.get("/api/google/callback", params={"code": "c", "state": q["state"][0]}, follow_redirects=False)
    assert r.status_code == 302 and "verbunden" in r.headers["location"], r.headers["location"]


def test_not_configured_message(client):
    r = client.get("/api/google/auth-url")
    assert r.status_code == 400 and "Client-ID" in r.json()["detail"]


def test_invalid_state_rejected(client, fake):
    client.put("/api/google/credentials", json={"client_id": "abc.apps.googleusercontent.com", "client_secret": "s"})
    client.get("/api/google/auth-url")
    r = client.get("/api/google/callback", params={"code": "c", "state": "falsch"}, follow_redirects=False)
    assert "fehler" in r.headers["location"]


def test_connect_sync_and_no_duplicates(client, fake):
    connect(client)
    st = client.get("/api/google/status").json()
    assert st["connected"] and st["email"] == "me@example.com"
    assert [c["selected"] for c in st["calendars"]] == [True, False]
    params = {"start": "2026-12-01T00:00:00Z", "end": "2026-12-31T00:00:00Z"}
    evs = client.get("/api/events", params=params).json()
    assert {e["title"] for e in evs} == {"Kundentermin", "Feiertag"}
    assert all(e["source"] == "google" for e in evs)
    feiertag = next(e for e in evs if e["title"] == "Feiertag")
    assert feiertag["all_day"] and feiertag["start_date"] == "2026-12-25" and feiertag["busy"] is False
    # Zweiter Sync erzeugt keine Duplikate
    client.post("/api/google/sync")
    assert len(client.get("/api/events", params=params).json()) == 2
    # In Google gelöscht -> lokal entfernt
    fake.events.pop("evt2")
    client.post("/api/google/sync")
    assert [e["title"] for e in client.get("/api/events", params=params).json()] == ["Kundentermin"]


def test_write_and_conflict(client, fake):
    connect(client)
    r = client.post("/api/events", json={"title": "Neu", "start": "2026-12-04T09:00:00+01:00", "target": "google"})
    assert r.status_code == 201
    params = {"start": "2026-12-01T00:00:00Z", "end": "2026-12-31T00:00:00Z"}
    evs = client.get("/api/events", params=params).json()
    k = next(e for e in evs if e["title"] == "Kundentermin")
    # Zwischenzeitlich in Google geändert -> 412 -> Konflikt statt Überschreiben
    fake.events["evt1"]["etag"] = '"99"'
    r = client.patch(f"/api/events/{k['event_id']}", json={"title": "Geändert"})
    assert r.status_code == 409 and "Konflikt" in r.json()["detail"]
    client.post("/api/google/sync")
    r = client.patch(f"/api/events/{k['event_id']}", json={"title": "Geändert"})
    assert r.status_code == 200 and fake.events["evt1"]["summary"] == "Geändert"
    assert client.delete(f"/api/events/{k['event_id']}").status_code == 200
    assert "evt1" not in fake.events


def test_reader_calendar_not_writable(client, fake):
    connect(client)
    r = client.post("/api/events", json={"title": "X", "start": "2026-12-04T09:00:00+01:00", "target": "google", "google_calendar_id": "feiertage"})
    assert r.status_code == 403


def test_expired_token_gives_clear_error(client, fake, db):
    connect(client)
    tokens = g.get_tokens(db)
    tokens["expires_at"] = 0
    g._save_tokens(db, tokens)
    fake.refresh_fails = True
    r = client.post("/api/google/sync")
    assert r.status_code == 502 and "abgelaufen" in r.json()["detail"]
    st = client.get("/api/google/status").json()
    assert "abgelaufen" in (st["last_error"] or "")


def test_disconnect_removes_mirror(client, fake):
    connect(client)
    assert client.post("/api/google/disconnect").status_code == 200
    st = client.get("/api/google/status").json()
    assert not st["connected"] and st["calendars"] == []
