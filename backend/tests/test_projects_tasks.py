from datetime import date, timedelta


def test_project_crud_and_progress(client):
    r = client.post("/api/projects", json={"name": "LBS", "goal": "Abschluss", "priority": "high", "deadline": (date.today() + timedelta(days=10)).isoformat()})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.post("/api/projects", json={"name": "X", "start_date": "2026-05-01", "deadline": "2026-04-01"}).status_code == 400
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    t1 = client.post("/api/tasks", json={"title": "Konzept", "project_id": pid, "estimated_minutes": 60}).json()
    client.post("/api/tasks", json={"title": "Umsetzung", "project_id": pid})
    assert client.post(f"/api/tasks/{t1['id']}/complete").json()["status"] == "done"
    p = client.get(f"/api/projects/{pid}").json()
    assert p["project"]["progress"] == 50
    assert p["project"]["task_open"] == 1
    assert any("Projekt „LBS“ angelegt" in h["summary"] for h in p["history"])
    r = client.patch(f"/api/projects/{pid}", json={"status": "paused", "notes": "Notiz"})
    assert r.json()["status"] == "paused"


def test_task_status_and_subtasks(client):
    parent = client.post("/api/tasks", json={"title": "Website", "priority": "critical", "due_date": (date.today() - timedelta(days=1)).isoformat()}).json()
    assert parent["overdue"] is True
    sub = client.post("/api/tasks", json={"title": "Texte", "parent_id": parent["id"]}).json()
    assert client.post("/api/tasks", json={"title": "Zu tief", "parent_id": sub["id"]}).status_code == 400
    d = client.get(f"/api/tasks/{parent['id']}").json()
    assert d["task"]["subtask_total"] == 1 and len(d["subtasks"]) == 1
    r = client.patch(f"/api/tasks/{sub['id']}", json={"status": "waiting"})
    assert r.json()["status"] == "waiting"
    r = client.patch(f"/api/tasks/{sub['id']}", json={"status": "kaputt"})
    assert r.status_code == 422
    done = client.patch(f"/api/tasks/{parent['id']}", json={"status": "done"}).json()
    assert done["completed_at"] is not None
    reopened = client.patch(f"/api/tasks/{parent['id']}", json={"status": "open"}).json()
    assert reopened["completed_at"] is None
    assert client.get("/api/tasks?status=active").status_code == 200
    assert client.get("/api/tasks?status=1;drop").status_code == 422


def test_delete_project_archives_tasks(client):
    pid = client.post("/api/projects", json={"name": "Alt"}).json()["id"]
    tid = client.post("/api/tasks", json={"title": "Rest", "project_id": pid}).json()["id"]
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    t = client.get(f"/api/tasks/{tid}").json()["task"]
    assert t["status"] == "archived" and t["project_id"] is None


def test_overview_summary_uses_real_data(client):
    pid = client.post("/api/projects", json={"name": "LBS", "deadline": (date.today() + timedelta(days=3)).isoformat()}).json()["id"]
    client.post("/api/tasks", json={"title": "Alte Aufgabe", "due_date": (date.today() - timedelta(days=3)).isoformat()})
    client.post("/api/tasks", json={"title": "Heute", "project_id": pid, "due_date": date.today().isoformat()})
    o = client.get("/api/overview").json()
    assert len(o["overdue"]) == 1 and len(o["tasks_today"]) == 1
    assert "überfällig" in o["summary"] and "LBS" in o["summary"]
    assert "keine Termine" in o["summary"]


def test_search(client):
    client.post("/api/projects", json={"name": "TM Sailing"})
    client.post("/api/tasks", json={"title": "Segel prüfen"})
    r = client.get("/api/search?q=Sail").json()
    assert r["projects"][0]["name"] == "TM Sailing"
    assert client.get("/api/search?q=Segel").json()["tasks"][0]["title"] == "Segel prüfen"
