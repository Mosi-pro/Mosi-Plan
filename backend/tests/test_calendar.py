from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BER = ZoneInfo("Europe/Berlin")


def test_internal_event_crud_and_conflicts(client):
    r = client.post("/api/events", json={"title": "Meeting", "start": "2026-12-01T09:00:00+01:00", "end": "2026-12-01T10:00:00+01:00"})
    assert r.status_code == 201
    eid = r.json()["id"]
    r2 = client.post("/api/events", json={"title": "Überlappend", "start": "2026-12-01T09:30:00+01:00", "end": "2026-12-01T10:30:00+01:00"})
    assert r2.json()["conflicts"][0]["title"] == "Meeting"
    assert client.post("/api/events", json={"title": "Falsch", "start": "2026-12-01T10:00:00+01:00", "end": "2026-12-01T09:00:00+01:00"}).status_code == 400
    evs = client.get("/api/events", params={"start": "2026-12-01T00:00:00+01:00", "end": "2026-12-02T00:00:00+01:00"}).json()
    assert [e["title"] for e in evs] == ["Meeting", "Überlappend"]
    assert evs[0]["source"] == "internal"
    r = client.patch(f"/api/events/{eid}", json={"start": "2026-12-01T14:00:00+01:00"})
    assert r.status_code == 200
    ev = client.get(f"/api/events/{eid}").json()
    assert datetime.fromisoformat(ev["end"]) - datetime.fromisoformat(ev["start"]) == timedelta(hours=1)
    assert client.delete(f"/api/events/{eid}").status_code == 200
    assert client.get(f"/api/events/{eid}").status_code == 404


def test_all_day_event(client):
    r = client.post("/api/events", json={"title": "Urlaub", "all_day": True, "start_date": "2026-12-24", "end_date": "2026-12-26"})
    eid = r.json()["id"]
    ev = client.get(f"/api/events/{eid}").json()
    assert ev["start_date"] == "2026-12-24" and ev["end_date"] == "2026-12-26" and ev["busy"] is False


def test_recurring_event_respects_dst(client):
    # Wöchentlich montags 09:00 lokal, über die Zeitumstellung Ende Oktober hinweg
    r = client.post("/api/events", json={"title": "Jour fixe", "start": "2026-10-19T09:00:00+02:00", "end": "2026-10-19T09:30:00+02:00", "rrule": "FREQ=WEEKLY;BYDAY=MO"})
    eid = r.json()["id"]
    evs = client.get("/api/events", params={"start": "2026-10-18T00:00:00Z", "end": "2026-11-10T00:00:00Z"}).json()
    assert len(evs) == 4
    for e in evs:
        local = datetime.fromisoformat(e["start"]).astimezone(BER)
        assert (local.hour, local.minute) == (9, 0), e["start"]
    # Einzeltermin entfernen
    occ = evs[1]["occurrence"]
    assert client.delete(f"/api/events/{eid}", params={"occurrence": occ}).status_code == 200
    evs2 = client.get("/api/events", params={"start": "2026-10-18T00:00:00Z", "end": "2026-11-10T00:00:00Z"}).json()
    assert len(evs2) == 3


def test_invalid_rrule_rejected(client):
    r = client.post("/api/events", json={"title": "X", "start": "2026-12-01T09:00:00+01:00", "rrule": "FREQ=SECONDLY"})
    assert r.status_code == 400


def test_categories_and_filter(client):
    cid = client.post("/api/categories", json={"name": "Sport", "color": "#22AA66"}).json()["id"]
    client.post("/api/events", json={"title": "Training", "start": "2026-12-02T18:00:00+01:00", "category_id": cid})
    client.post("/api/events", json={"title": "Arzt", "start": "2026-12-02T08:00:00+01:00"})
    evs = client.get("/api/events", params={"start": "2026-12-02T00:00:00+01:00", "end": "2026-12-03T00:00:00+01:00", "categories": str(cid)}).json()
    assert [e["title"] for e in evs] == ["Training"] and evs[0]["color"] == "#22AA66"
    assert client.post("/api/categories", json={"name": "Bad", "color": "red"}).status_code == 422
