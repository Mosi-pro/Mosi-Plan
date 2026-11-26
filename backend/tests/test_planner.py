"""Wochenplaner: Regeln (keine Überschneidungen, Arbeitszeiten, Deadlines), Freigabe, Bearbeitung, Historie."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BER = ZoneInfo("Europe/Berlin")


def next_monday():
    t = datetime.now(BER).date()
    return t + timedelta(days=7 - t.weekday())


def setup_week(client):
    ws = next_monday()
    client.put("/api/settings/planner", json={"work_start": "09:00", "work_end": "17:00", "lunch_start": "12:00", "lunch_end": "13:00", "buffer_minutes": 15, "max_focus_minutes_per_day": 360, "work_days": [0, 1, 2, 3, 4]})
    # Montag 09:00–12:00 belegt
    client.post("/api/events", json={"title": "Workshop", "start": f"{ws}T09:00:00", "end": f"{ws}T12:00:00"})
    pid = client.post("/api/projects", json={"name": "LBS", "priority": "high"}).json()["id"]
    urgent = client.post("/api/tasks", json={"title": "Antrag", "project_id": pid, "priority": "critical", "estimated_minutes": 240, "due_date": (ws + timedelta(days=1)).isoformat()}).json()
    client.post("/api/tasks", json={"title": "Doku", "project_id": pid, "estimated_minutes": 300})
    client.post("/api/tasks", json={"title": "Ohne Schätzung", "project_id": pid, "priority": "high"})
    return ws, urgent


def test_generate_respects_rules(client):
    ws, urgent = setup_week(client)
    p = client.post("/api/planner/generate", json={"week_start": ws.isoformat()}).json()
    assert p["status"] == "draft"
    items = [i for i in p["items"] if i["status"] != "removed"]
    assert items
    ws_dt = datetime.combine(ws, datetime.min.time(), tzinfo=BER)
    for i in items:
        s, e = datetime.fromisoformat(i["start"]).astimezone(BER), datetime.fromisoformat(i["end"]).astimezone(BER)
        assert s.weekday() < 5, "nur Arbeitstage"
        assert s.time() >= datetime.strptime("09:00", "%H:%M").time() and e.time() <= datetime.strptime("17:00", "%H:%M").time()
        assert not (s.time() < datetime.strptime("13:00", "%H:%M").time() and e.time() > datetime.strptime("12:00", "%H:%M").time()), "Mittagspause"
        # Workshop + 15 min Puffer
        if s.date() == ws:
            assert s >= ws_dt.replace(hour=12, minute=15)
        assert i["minutes"] <= 120
    # keine Überschneidungen untereinander
    iv = sorted((i["start"], i["end"]) for i in items)
    for a, b in zip(iv, iv[1:]):
        assert a[1] <= b[0]
    antrag = [i for i in items if i["task_id"] == urgent["id"]]
    assert sum(i["minutes"] for i in antrag) == 240
    assert all(i["date"] <= (ws + timedelta(days=1)).isoformat() for i in antrag), "vor der Deadline"
    assert any("Zeitschätzung" in r for r in p["data"]["recommendations"])
    assert p["data"]["goals"] and p["data"]["goals"][0]["title"].startswith("LBS")
    assert len(p["data"]["days"]) == 7


def test_confirm_creates_internal_events_only(client):
    ws, _ = setup_week(client)
    p = client.post("/api/planner/generate", json={"week_start": ws.isoformat()}).json()
    n = len(p["items"])
    c = client.post(f"/api/planner/plans/{p['id']}/confirm", json={}).json()
    assert c["status"] == "confirmed"
    evs = client.get("/api/events", params={"start": f"{ws}T00:00:00+01:00", "end": f"{ws + timedelta(days=7)}T00:00:00+01:00"}).json()
    planned = [e for e in evs if e["origin"] == "weekly_plan"]
    assert len(planned) == n and all(e["source"] == "internal" for e in planned)
    # Neuer Plan für dieselbe Woche plant bereits terminierte Aufgaben nicht doppelt
    p2 = client.post("/api/planner/generate", json={"week_start": ws.isoformat()}).json()
    assert not {i["task_id"] for i in p2["items"]} & {i["task_id"] for i in c["items"]}
    assert client.post(f"/api/planner/plans/{p['id']}/discard").status_code == 400


def test_move_remove_regenerate_discard(client):
    ws, _ = setup_week(client)
    p = client.post("/api/planner/generate", json={"week_start": ws.isoformat()}).json()
    item = p["items"][0]
    target = datetime.combine(ws + timedelta(days=4), datetime.min.time(), tzinfo=BER).replace(hour=15)
    r = client.post(f"/api/planner/items/{item['id']}/move", json={"start": target.isoformat()})
    assert r.status_code == 200
    moved = next(i for i in r.json()["plan"]["items"] if i["id"] == item["id"])
    assert moved["status"] == "moved" and moved["original_start"]
    outside = client.post(f"/api/planner/items/{item['id']}/move", json={"start": (target + timedelta(days=10)).isoformat()})
    assert outside.status_code == 400
    r = client.delete(f"/api/planner/items/{p['items'][1]['id']}")
    assert r.json()["review"]["removed"] == 1
    p2 = client.post(f"/api/planner/plans/{p['id']}/regenerate").json()
    assert p2["id"] != p["id"]
    assert client.get(f"/api/planner/plans/{p['id']}").json()["status"] == "superseded"
    assert client.post(f"/api/planner/plans/{p2['id']}/discard").json()["status"] == "discarded"
    hist = client.get("/api/planner/plans").json()
    assert [h["status"] for h in hist] == ["discarded"]


def test_past_week_rejected(client):
    assert client.post("/api/planner/generate", json={"week_start": "2020-01-06"}).status_code == 400


def test_scheduled_job_generates_once(client, db, user, monkeypatch):
    from app import jobs
    from app.services import settings_store as st

    now = datetime.now(BER)
    st.update_section(db, "planner", {"weekday": now.weekday(), "time": "00:00"})
    assert "erstellt" in jobs.job_weekly_plan(db)
    assert jobs.job_weekly_plan(db) == "bereits erstellt"
    n = client.get("/api/notifications").json()
    assert any(i["type"] == "weekly_plan" for i in n["items"])
