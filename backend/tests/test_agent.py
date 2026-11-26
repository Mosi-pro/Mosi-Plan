"""Agentenebene: Hermes-Streaming, direkter Anbieter mit Werkzeugaufrufen, Ausfallverhalten."""
import json
from contextlib import contextmanager


from app.ai import agent
from app.config import get_settings


def parse_sse(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def new_conv(client):
    return client.post("/api/conversations").json()["id"]


def test_ai_unavailable_keeps_app_working(client):
    cid = new_conv(client)
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "Was steht heute an?"})
    events = parse_sse(r.text)
    done = events[-1]
    assert done["type"] == "done" and done["error"] and "Hermes" in done["error"]
    # Restliche Anwendung funktioniert weiter
    assert client.get("/api/overview").status_code == 200
    conv = client.get(f"/api/conversations/{cid}").json()
    assert conv["messages"][-1]["meta"]["error"] is True
    assert conv["title"] == "Was steht heute an?"


def test_direct_provider_with_tool_calls(client, monkeypatch):
    client.put("/api/settings/ai", json={"mode": "direct", "direct_base_url": "http://llm.local/v1", "direct_model": "test-model", "direct_api_key": "k"})
    s = client.get("/api/settings").json()["ai"]
    assert s["has_direct_api_key"] and "direct_api_key" not in s
    calls = []

    def fake_call(db, messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            assert any(t["function"]["name"] == "create_task" for t in tools)
            assert "Kontext (aus der MOSI-Datenbank" in messages[-2]["content"]
            return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "create_task", "arguments": json.dumps({"title": "Website überarbeiten", "due_date": "2026-12-07"})}}]}
        tool_msg = messages[-1]
        assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["saved"] is True
        return {"content": "Erledigt: Die Aufgabe „Website überarbeiten“ ist angelegt."}

    monkeypatch.setattr(agent, "_direct_call", fake_call)
    cid = new_conv(client)
    events = parse_sse(client.post(f"/api/conversations/{cid}/messages", json={"content": "Leg eine Aufgabe an", "via_voice": True}).text)
    types = [e["type"] for e in events]
    assert "tool" in types and types[-1] == "done"
    assert events[-1]["error"] is None and "angelegt" in events[-1]["content"]
    assert client.get("/api/tasks").json()[0]["title"] == "Website überarbeiten"
    assert client.get("/api/tasks").json()[0]["origin"] == "assistant"


def test_pending_action_attached_to_message(client, monkeypatch):
    client.put("/api/settings/ai", json={"mode": "direct", "direct_base_url": "http://llm.local/v1", "direct_model": "m"})
    pid = client.post("/api/projects", json={"name": "Weg"}).json()["id"]
    step = {"n": 0}

    def fake_call(db, messages, tools):
        step["n"] += 1
        if step["n"] == 1:
            return {"content": "", "tool_calls": [{"id": "c1", "function": {"name": "delete_project", "arguments": json.dumps({"project_id": pid})}}]}
        assert json.loads(messages[-1]["content"])["status"] == "confirmation_required"
        return {"content": "Bitte bestätige das Löschen in der Oberfläche."}

    monkeypatch.setattr(agent, "_direct_call", fake_call)
    cid = new_conv(client)
    done = parse_sse(client.post(f"/api/conversations/{cid}/messages", json={"content": "Lösch Projekt Weg"}).text)[-1]
    assert len(done["pending_actions"]) == 1 and "Weg" in done["pending_actions"][0]["description"]
    assert client.get(f"/api/projects/{pid}").status_code == 200
    msgs = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert msgs[-1]["meta"]["actions"][0]["status"] == "pending"


class FakeStreamResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        yield from self._lines

    def read(self):
        return b""


def test_hermes_streaming(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "hermes_enabled", True)
    monkeypatch.setattr(agent, "hermes_status", lambda force=False: (True, "verbunden"))
    sent = {}
    lines = [
        ": keepalive",
        "event: hermes.tool.progress",
        'data: {"tool": "mcp__mosi__get_daily_overview"}',
        "",
        'data: {"choices":[{"delta":{"content":"Guten "}}]}',
        'data: {"choices":[{"delta":{"content":"Morgen!"},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]

    @contextmanager
    def fake_stream(method, url, json=None, headers=None, timeout=None):
        sent.update(url=url, body=json, headers=headers)
        yield FakeStreamResponse(lines)

    monkeypatch.setattr(agent.httpx, "stream", fake_stream)
    cid = new_conv(client)
    events = parse_sse(client.post(f"/api/conversations/{cid}/messages", json={"content": "Hallo"}).text)
    assert sent["url"].endswith("/v1/chat/completions") and sent["body"]["stream"] is True
    assert sent["headers"]["Authorization"].startswith("Bearer ")
    assert sent["body"]["messages"][0]["role"] == "system"
    tool_ev = next(e for e in events if e["type"] == "tool")
    assert tool_ev["name"] == "get_daily_overview" and tool_ev["label"] == "Tagesübersicht abrufen"
    assert events[-1]["content"] == "Guten Morgen!"
    assert events[-1]["error"] is None


def test_hermes_down_falls_back_to_direct(client, monkeypatch):
    monkeypatch.setattr(agent, "hermes_status", lambda force=False: (False, "nicht erreichbar"))
    client.put("/api/settings/ai", json={"mode": "hermes", "fallback_direct": True, "direct_base_url": "http://llm.local/v1", "direct_model": "m"})
    monkeypatch.setattr(agent, "_direct_call", lambda db, m, t: {"content": "Fallback aktiv."})
    cid = new_conv(client)
    events = parse_sse(client.post(f"/api/conversations/{cid}/messages", json={"content": "Hallo"}).text)
    assert {"type": "backend", "name": "direct"} in events and events[-1]["content"] == "Fallback aktiv."


def test_assistant_status(client):
    s = client.get("/api/assistant/status").json()
    assert s["available"] is False and s["hermes_ok"] is False
