"""Automatische Modellwahl, Ausweichmodelle und anbieterkompatible Werkzeug-Schemas."""
import json

import httpx

from app.ai import agent
from app.ai.tools import openai_tools


def setup_direct(client, **extra):
    client.put("/api/settings/ai", json={"mode": "direct", "direct_base_url": "https://llm.example/v1", "direct_model": "gemini-x-flash", "direct_api_key": "k", **extra})


def test_tool_schemas_have_no_refs():
    text = json.dumps(openai_tools())
    assert "$ref" not in text and "$defs" not in text
    task = next(t for t in openai_tools() if t["function"]["name"] == "create_task")["function"]["parameters"]
    assert task["properties"]["title"]["type"] == "string" and "title" in task["required"]
    assert all(not isinstance(v.get("title"), str) for v in task["properties"].values())
    plan = next(t for t in openai_tools() if t["function"]["name"] == "propose_project_plan")
    assert plan["function"]["parameters"]["properties"]["tasks"]["items"]["properties"]["key"]["type"] == "string"


def test_fallback_model_used_when_main_overloaded(client, monkeypatch):
    setup_direct(client, fallback_models=["gemini-y-lite"])
    calls = []

    def fake_post(base, key, body, timeout):
        calls.append(body["model"])
        if body["model"] == "gemini-x-flash":
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    monkeypatch.setattr(agent, "_post_chat", fake_post)
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)
    r = client.post("/api/settings/ai/test")
    assert r.status_code == 200 and r.json()["answer"] == "OK"
    assert calls == ["gemini-x-flash", "gemini-x-flash", "gemini-y-lite"]


def test_all_models_fail_gives_clear_message(client, monkeypatch):
    setup_direct(client)
    monkeypatch.setattr(agent, "_post_chat", lambda *a: httpx.Response(429, json={}))
    r = client.post("/api/settings/ai/test")
    assert r.status_code == 503 and "Limit" in r.json()["detail"] and "automatisch finden" in r.json()["detail"]


def test_list_and_autoselect(client, monkeypatch):
    setup_direct(client)
    monkeypatch.setattr(agent.httpx, "get", lambda url, headers=None, timeout=None: httpx.Response(200, json={"data": [
        {"id": "models/gemini-x-flash"}, {"id": "models/gemini-z-flash-lite"}, {"id": "models/text-embedding-9"}, {"id": "models/gemini-pro-big"}]}))
    assert client.get("/api/settings/ai/models").json()["models"] == ["gemini-pro-big", "gemini-x-flash", "gemini-z-flash-lite", "text-embedding-9"]
    tried = []

    def fake_post(base, key, body, timeout):
        tried.append(body["model"])
        ok = body["model"] in ("gemini-z-flash-lite", "gemini-pro-big")
        return httpx.Response(200 if ok else 503, json={"choices": [{"message": {"content": "OK"}}]} if ok else {})

    monkeypatch.setattr(agent, "_post_chat", fake_post)
    res = client.post("/api/settings/ai/autoselect").json()
    assert res["ok"] and res["model"] == "gemini-z-flash-lite" and res["fallbacks"] == ["gemini-pro-big"]
    assert "text-embedding-9" not in tried
    s = client.get("/api/settings").json()["ai"]
    assert s["direct_model"] == "gemini-z-flash-lite" and s["fallback_models"] == ["gemini-pro-big"]


def test_bad_key_message(client, monkeypatch):
    setup_direct(client)
    monkeypatch.setattr(agent.httpx, "get", lambda *a, **k: httpx.Response(401))
    r = client.get("/api/settings/ai/models")
    assert r.status_code == 503 and "Schlüssel" in r.json()["detail"]
