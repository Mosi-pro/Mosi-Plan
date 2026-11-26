"""KI-Werkzeuge, Bestätigungslogik und MCP-Endpunkt."""
from datetime import date, timedelta

import pytest

from app.ai.tools import REGISTRY, ToolContext, execute_tool


@pytest.fixture
def ctx(db, user):
    return ToolContext(db=db, user=user)


def test_all_required_tools_registered():
    required = {"get_calendar_events", "create_calendar_event", "update_calendar_event", "delete_calendar_event", "get_projects", "create_project",
                "update_project", "get_tasks", "create_task", "update_task", "complete_task", "create_weekly_plan", "search_memory", "save_memory", "get_daily_overview"}
    assert required <= set(REGISTRY)
    for t in REGISTRY.values():
        assert t.params.model_json_schema()["type"] == "object"
    assert not any(n in REGISTRY for n in ("shell", "run_command", "terminal", "read_file"))


def test_create_and_complete_task_via_tools(ctx):
    r = execute_tool(ctx, "create_project", {"name": "MOSI.MEDIA"})
    assert r["ok"] and r["saved"]
    r = execute_tool(ctx, "create_task", {"title": "Website überarbeiten", "project_name": "mosi.media", "due_date": "2026-12-07", "estimated_minutes": 180})
    assert r["ok"] and r["project_id"]
    tid = r["task_id"]
    r = execute_tool(ctx, "get_tasks", {"project_name": "MOSI.MEDIA"})
    assert r["count"] == 1
    assert execute_tool(ctx, "complete_task", {"task_id": tid})["status"] == "done"


def test_validation_errors_are_reported(ctx):
    r = execute_tool(ctx, "create_task", {"title": ""})
    assert not r["ok"] and "Ungültige Eingabe" in r["error"]
    r = execute_tool(ctx, "create_task", {"title": "X", "project_name": "Gibtsnicht"})
    assert not r["ok"] and "Gibtsnicht" in r["error"]
    assert not execute_tool(ctx, "unbekannt", {})["ok"]


def test_internal_event_created_directly(ctx):
    r = execute_tool(ctx, "create_calendar_event", {"title": "Bilder bearbeiten", "start": "2026-12-09T10:00", "end": "2026-12-09T12:00"})
    assert r["ok"] and r["saved"] and r["source"] == "internal"
    assert r["start"].startswith("2026-12-09T10:00")


def test_delete_requires_confirmation(client, db, user):
    ctx = ToolContext(db=db, user=user)
    eid = execute_tool(ctx, "create_calendar_event", {"title": "Löschmich", "start": "2026-12-09T10:00"})["event_id"]
    r = execute_tool(ctx, "delete_calendar_event", {"event_id": eid})
    assert r["status"] == "confirmation_required"
    aid = r["pending_action_id"]
    # Termin existiert noch
    assert client.get(f"/api/events/{eid}").status_code == 200
    pending = client.get("/api/actions").json()
    assert pending[0]["id"] == aid and "Löschmich" in pending[0]["description"]
    assert client.post(f"/api/actions/{aid}/confirm").status_code == 200
    assert client.get(f"/api/events/{eid}").status_code == 404
    assert client.post(f"/api/actions/{aid}/confirm").status_code == 400


def test_reject_pending(client, db, user):
    ctx = ToolContext(db=db, user=user)
    pid = execute_tool(ctx, "create_project", {"name": "Behalten"})["project_id"]
    aid = execute_tool(ctx, "delete_project", {"project_id": pid})["pending_action_id"]
    assert client.post(f"/api/actions/{aid}/reject").json()["status"] == "rejected"
    assert client.get(f"/api/projects/{pid}").status_code == 200


def test_bulk_update_requires_confirmation(client, db, user):
    ctx = ToolContext(db=db, user=user)
    ids = [execute_tool(ctx, "create_task", {"title": f"T{i}"})["task_id"] for i in range(3)]
    r = execute_tool(ctx, "bulk_update_tasks", {"task_ids": ids, "priority": "high"})
    assert r["status"] == "confirmation_required"
    client.post(f"/api/actions/{r['pending_action_id']}/confirm")
    assert all(t["priority"] == "high" for t in client.get("/api/tasks").json())


def test_project_plan_proposal_and_apply(client, db, user):
    ctx = ToolContext(db=db, user=user)
    d = date.today() + timedelta(days=30)
    plan = {"project_name": "Website", "goal": "Neue Website", "deadline": d.isoformat(), "tasks": [
        {"key": "a", "title": "Konzept", "estimated_minutes": 120},
        {"key": "b", "title": "Design", "estimated_minutes": 240, "depends_on": ["a"]},
        {"key": "c", "title": "Umsetzung", "estimated_minutes": 480, "depends_on": ["b"], "due_date": d.isoformat()}]}
    cyc = dict(plan, tasks=[{"key": "a", "title": "A", "estimated_minutes": 30, "depends_on": ["b"]}, {"key": "b", "title": "B", "estimated_minutes": 30, "depends_on": ["a"]}])
    assert "Zyklus" in execute_tool(ctx, "propose_project_plan", cyc)["error"]
    r = execute_tool(ctx, "propose_project_plan", plan)
    assert r["status"] == "confirmation_required"
    assert client.get("/api/projects").json() == []
    act = client.get("/api/actions").json()[0]
    assert len(act["preview"]["tasks"]) == 3 and act["preview"]["check"]["total_minutes"] == 840
    res = client.post(f"/api/actions/{act['id']}/confirm").json()
    pid = res["result"]["project_id"]
    tasks = client.get(f"/api/tasks?project_id={pid}").json()
    by = {t["title"]: t for t in tasks}
    assert by["Design"]["depends_on"] == [by["Konzept"]["id"]]


def test_google_write_requires_confirmation(ctx):
    r = execute_tool(ctx, "create_calendar_event", {"title": "Extern", "start": "2026-12-09T10:00", "target": "google"})
    assert r["status"] == "confirmation_required"


def test_memory_tools(ctx):
    assert execute_tool(ctx, "save_memory", {"content": "Montags keine Termine vor 10 Uhr", "category": "planning_rule"})["saved"]
    r = execute_tool(ctx, "search_memory", {"query": "Termine Montag"})
    assert r["entries"][0]["category"] == "planning_rule"
    r = execute_tool(ctx, "save_memory", {"content": "Mein Passwort: Geheim123!"})
    assert not r["ok"] and "sensible" in r["error"]


def test_weekly_plan_tool_creates_draft(ctx):
    execute_tool(ctx, "create_project", {"name": "LBS"})
    execute_tool(ctx, "create_task", {"title": "Bericht", "project_name": "LBS", "priority": "high", "estimated_minutes": 90})
    nxt = date.today() + timedelta(days=7 - date.today().weekday())
    r = execute_tool(ctx, "create_weekly_plan", {"week_start": nxt.isoformat()})
    assert r["ok"] and "draft" in r["status"] and len(r["blocks"]) == 1


def test_mcp_endpoint(anon, user):
    assert anon.post("/internal/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
    h = {"Authorization": "Bearer test-mcp-token"}
    init = anon.post("/internal/mcp", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "hermes"}}}).json()
    assert init["result"]["protocolVersion"] == "2025-03-26" and init["result"]["capabilities"]["tools"]
    assert anon.post("/internal/mcp", headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    tools = anon.post("/internal/mcp", headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "create_task" in names and all("inputSchema" in t for t in tools)
    call = anon.post("/internal/mcp", headers=h, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "create_task", "arguments": {"title": "Per Hermes"}}}).json()
    assert call["result"]["isError"] is False and call["result"]["structuredContent"]["saved"]
    bad = anon.post("/internal/mcp", headers=h, json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "rm_rf", "arguments": {}}}).json()
    assert "error" in bad
