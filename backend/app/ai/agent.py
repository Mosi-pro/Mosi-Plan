"""Agentenebene: Hermes Agent (bevorzugt) oder direkter OpenAI-kompatibler Anbieter.

Hermes-Modus
  MOSI ruft den dokumentierten OpenAI-kompatiblen API-Server des Hermes-Gateways
  auf (POST {HERMES_URL}/v1/chat/completions, Bearer API_SERVER_KEY, Streaming per
  SSE). Hermes greift über den MOSI-MCP-Endpunkt (/internal/mcp) auf genau die
  freigegebenen Werkzeuge zu; alle anderen Hermes-Toolsets sind in der Hermes-
  Konfiguration deaktiviert (siehe deployment/hermes/config.yaml).

Direkter Modus / Fallback
  Ist Hermes nicht erreichbar, kann MOSI denselben Werkzeugsatz mit einem
  beliebigen OpenAI-kompatiblen Anbieter (OpenRouter, Ollama, vLLM, …) selbst
  ausführen. Ohne KI bleibt die restliche Anwendung voll funktionsfähig.
"""
import json
import logging
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Conversation, MemoryEntry, Message, PendingAction, User
from ..services import settings_store as st
from ..services.overview import WEEKDAYS, daily_overview, project_context, user_name
from .tools import ToolContext, execute_tool, openai_tools

log = logging.getLogger("mosi.agent")

HISTORY_MESSAGES = 24
SUMMARIZE_AFTER = 40
MAX_TOOL_ROUNDS = 10

_health_cache: dict[str, tuple[float, bool, str]] = {}

TOOL_LABEL = {
    "get_daily_overview": "Tagesübersicht abrufen",
    "get_calendar_events": "Kalender prüfen",
    "get_free_slots": "Freie Zeiten suchen",
    "create_calendar_event": "Termin anlegen",
    "update_calendar_event": "Termin ändern",
    "delete_calendar_event": "Termin löschen (Bestätigung)",
    "get_projects": "Projekte abrufen",
    "create_project": "Projekt anlegen",
    "update_project": "Projekt aktualisieren",
    "delete_project": "Projekt löschen (Bestätigung)",
    "get_tasks": "Aufgaben abrufen",
    "create_task": "Aufgabe anlegen",
    "update_task": "Aufgabe ändern",
    "complete_task": "Aufgabe abschließen",
    "bulk_update_tasks": "Mehrere Aufgaben ändern (Bestätigung)",
    "propose_project_plan": "Projektplan vorbereiten",
    "create_weekly_plan": "Wochenplan erstellen",
    "search_memory": "Gedächtnis durchsuchen",
    "save_memory": "Im Gedächtnis speichern",
}


class AIUnavailable(Exception):
    pass


# ----------------------------------------------------------------- Status
def hermes_status(force: bool = False) -> tuple[bool, str]:
    s = get_settings()
    if not s.hermes_enabled or not s.hermes_url:
        return False, "Hermes ist deaktiviert."
    cached = _health_cache.get("hermes")
    if cached and not force and time.time() - cached[0] < 30:
        return cached[1], cached[2]
    try:
        r = httpx.get(s.hermes_url.rstrip("/") + "/health", timeout=3)
        ok = r.status_code == 200
        msg = "verbunden" if ok else f"Antwort {r.status_code}"
    except httpx.HTTPError as exc:
        ok, msg = False, f"nicht erreichbar ({exc.__class__.__name__})"
    _health_cache["hermes"] = (time.time(), ok, msg)
    return ok, msg


def direct_config(db: Session) -> tuple[str, str, str] | None:
    cfg = st.get_section(db, "ai")
    base, model = cfg.get("direct_base_url", ""), cfg.get("direct_model", "")
    key = st.get_secret(db, "ai.direct_api_key")
    if base and model:
        return base.rstrip("/"), key, model
    return None


def choose_backend(db: Session) -> str:
    cfg = st.get_section(db, "ai")
    mode = cfg["mode"]
    if mode == "off":
        raise AIUnavailable("Der KI-Assistent ist in den Einstellungen deaktiviert.")
    if mode == "hermes":
        ok, msg = hermes_status()
        if ok:
            return "hermes"
        if cfg.get("fallback_direct") and direct_config(db):
            return "direct"
        raise AIUnavailable(f"Hermes Agent ist {msg}. Alle anderen Funktionen von MOSI PLAN bleiben nutzbar. Optional kann in den Einstellungen ein direkter KI-Anbieter als Fallback hinterlegt werden.")
    if direct_config(db):
        return "direct"
    raise AIUnavailable("Kein KI-Anbieter konfiguriert. Bitte unter Einstellungen → KI einrichten.")


# ----------------------------------------------------------------- Prompting
STATIC_PROMPT = """Du bist MOSI, der persönliche Planungsassistent in der Anwendung MOSI PLAN.
Du sprichst Deutsch und duzt den Benutzer. Dein Ton ist sachlich, präzise und professionell – wie eine erfahrene persönliche Assistenz. Keine Floskeln, keine Ausrufezeichen, keine Emojis. Kurze, klare Sätze (geeignet für Sprachausgabe), Markdown nur sparsam für Listen.

Arbeitsweise:
- Nutze ausschließlich die MOSI-Werkzeuge, um Projekte, Aufgaben, Termine, Wochenpläne und das Gedächtnis zu lesen oder zu ändern. Erfinde keine Daten.
- Prüfe vor dem Planen den Kalender (get_calendar_events / get_free_slots) und offene Aufgaben. Lege nichts in die Nacht und respektiere belegte Zeiten.
- Stelle einen Termin, eine Aufgabe oder einen Plan NIE als gespeichert dar, bevor ein Werkzeug "saved": true zurückgegeben hat.
- Liefert ein Werkzeug "confirmation_required", ist die Aktion NICHT ausgeführt. Sage dem Benutzer, dass er sie in der Oberfläche bestätigen muss.
- Löschen, Massenänderungen, Übernahme ganzer Projektpläne und Schreiben in Google Calendar erfordern immer eine Bestätigung des Benutzers.
- Für größere Vorhaben ("plane mir …"): Ziel erkennen, bei wirklich fehlenden Informationen kurz nachfragen, sonst sinnvolle Annahmen treffen und benennen, Teilaufgaben mit Zeitaufwand, Deadlines und Abhängigkeiten bilden und mit propose_project_plan zur Bestätigung vorlegen.
- "Plane meine Woche" -> create_weekly_plan (erstellt einen Entwurf, den der Benutzer auf der Seite Wochenplan freigibt).
- Datumsangaben relativ zu heute auflösen ("nächste Woche Montag"). Zeiten im lokalen ISO-Format ohne Zeitzone übergeben.
- Nutze search_memory, wenn persönliche Regeln, Entscheidungen oder Ziele relevant sein könnten. Speichere mit save_memory nur, wenn der Benutzer es wünscht oder es eine klare dauerhafte Regel/Entscheidung ist; keine sensiblen Daten.
- Wenn Informationen unsicher, veraltet oder unvollständig sind, sage das ausdrücklich.
- Du hast keinen Zugriff auf Server, Dateien oder Shell und versendest keine externen Nachrichten."""


def dynamic_context(db: Session, user: User) -> str:
    tz = ZoneInfo(user.timezone)
    now = datetime.now(tz)
    ov = daily_overview(db, user)
    projects = project_context(db)
    rules = [m.content for m in db.scalars(select(MemoryEntry).where((MemoryEntry.pinned.is_(True)) | (MemoryEntry.category == "planning_rule")).order_by(MemoryEntry.updated_at.desc()).limit(12))]
    planner_rules = st.get_section(db, "planner")
    lines = [
        f"Aktueller Zeitpunkt: {WEEKDAYS[now.weekday()]}, {now.strftime('%d.%m.%Y %H:%M')} ({user.timezone}), Kalenderwoche {now.isocalendar().week}.",
        f"Name des Benutzers: {user_name(db, user)}.",
        f"Arbeitszeiten laut Planungsregeln: {planner_rules['work_start']}–{planner_rules['work_end']}, Arbeitstage: {', '.join(WEEKDAYS[d] for d in planner_rules['work_days'])}.",
        f"Heute: {len(ov['events_today'])} Termine, {len(ov['tasks_today'])} fällige Aufgaben, {len(ov['overdue'])} überfällige Aufgaben.",
        "Projekte: " + ("; ".join(f"#{p['id']} {p['name']} ({p['status']}" + (f", Deadline {p['deadline']}" if p["deadline"] else "") + ")" for p in projects) or "keine"),
    ]
    if planner_rules.get("rules_text"):
        lines.append("Persönliche Planungsregeln: " + planner_rules["rules_text"][:1500])
    if rules:
        lines.append("Wichtige gespeicherte Regeln/Notizen: " + " | ".join(r[:300] for r in rules))
    return "Kontext (aus der MOSI-Datenbank, aktuell):\n" + "\n".join(lines)


def build_messages(db: Session, user: User, conv: Conversation) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": STATIC_PROMPT + f"\n(MOSI-Gespräch #{conv.id})"}]
    history = list(db.scalars(select(Message).where(Message.conversation_id == conv.id, Message.role.in_(("user", "assistant"))).order_by(Message.id.desc()).limit(HISTORY_MESSAGES)))[::-1]
    if conv.summary:
        msgs.append({"role": "system", "content": "Zusammenfassung des bisherigen Gesprächs: " + conv.summary})
    for m in history[:-1]:
        msgs.append({"role": m.role, "content": m.content or "…"})
    msgs.append({"role": "system", "content": dynamic_context(db, user)})
    if history:
        msgs.append({"role": history[-1].role, "content": history[-1].content})
    return msgs


# ----------------------------------------------------------------- Hermes
def _hermes_headers() -> dict:
    s = get_settings()
    return {"Authorization": f"Bearer {s.hermes_api_key}", "Content-Type": "application/json"}


def run_hermes(messages: list[dict]) -> Iterator[dict]:
    s = get_settings()
    url = s.hermes_url.rstrip("/") + "/v1/chat/completions"
    body = {"model": "hermes-agent", "messages": messages, "stream": True}
    event_name = None
    try:
        with httpx.stream("POST", url, json=body, headers=_hermes_headers(), timeout=httpx.Timeout(get_settings().ai_timeout_seconds, connect=5)) as r:
            if r.status_code == 401:
                raise AIUnavailable("Hermes lehnt den API-Schlüssel ab (HERMES_API_KEY prüfen).")
            if r.status_code != 200:
                r.read()
                raise AIUnavailable(f"Hermes antwortet mit Fehler {r.status_code}: {r.text[:200]}")
            for line in r.iter_lines():
                if not line or line.startswith(":"):
                    if not line:
                        event_name = None
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event_name == "hermes.tool.progress":
                    name = obj.get("tool") or obj.get("name") or obj.get("tool_name") or ""
                    name = name.split("__")[-1] if name else name
                    yield {"type": "tool", "name": name, "label": TOOL_LABEL.get(name, obj.get("label") or "Aktion wird ausgeführt")}
                    continue
                for ch in obj.get("choices", []):
                    delta = ch.get("delta", {})
                    if delta.get("content"):
                        yield {"type": "delta", "text": delta["content"]}
                    if ch.get("finish_reason") in ("error", "cancelled"):
                        raise AIUnavailable("Hermes konnte die Anfrage nicht abschließen.")
    except httpx.HTTPError as exc:
        _health_cache.pop("hermes", None)
        raise AIUnavailable(f"Verbindung zu Hermes fehlgeschlagen: {exc.__class__.__name__}") from exc


# ----------------------------------------------------------------- Direkter Anbieter
def _direct_call(db: Session, messages: list[dict], tools: list[dict] | None) -> dict:
    conf = direct_config(db)
    if not conf:
        raise AIUnavailable("Kein direkter KI-Anbieter konfiguriert.")
    base, key, model = conf
    body: dict = {"model": model, "messages": messages, "temperature": st.get_section(db, "ai").get("temperature", 0.3)}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        r = httpx.post(base + "/chat/completions", json=body, headers=headers, timeout=get_settings().ai_timeout_seconds)
    except httpx.HTTPError as exc:
        raise AIUnavailable(f"KI-Anbieter nicht erreichbar: {exc.__class__.__name__}") from exc
    if r.status_code == 429:
        raise AIUnavailable("Der KI-Anbieter meldet ein Limit (429). Bitte später erneut versuchen oder Tarif/Limits beim Anbieter prüfen.")
    if r.status_code != 200:
        text = r.text[:400]
        if "signal: killed" in text or "out of memory" in text.lower() or "requires more system memory" in text:
            raise AIUnavailable(
                "Das lokale KI-Modell wurde beendet, weil der Arbeitsspeicher des Servers nicht reicht. "
                "Bitte ein kleineres Modell wählen, z. B. auf dem Server: sudo ./scripts/ki-modell.sh qwen2.5:3b"
            )
        if "not found" in text and "model" in text:
            raise AIUnavailable(f"Das Modell „{model}“ ist nicht installiert. Auf dem Server: sudo ./scripts/ki-modell.sh {model}")
        raise AIUnavailable(f"KI-Anbieter meldet Fehler {r.status_code}: {text[:200]}")
    data = r.json()
    if not data.get("choices"):
        raise AIUnavailable("Leere Antwort vom KI-Anbieter.")
    return data["choices"][0]["message"]


def run_direct(db: Session, user: User, conv_id: int | None, messages: list[dict]) -> Iterator[dict]:
    ctx = ToolContext(db=db, user=user, conversation_id=conv_id)
    tools = openai_tools()
    msgs = list(messages)
    for _ in range(MAX_TOOL_ROUNDS):
        yield {"type": "status", "state": "thinking"}
        msg = _direct_call(db, msgs, tools)
        calls = msg.get("tool_calls") or []
        if not calls:
            yield {"type": "delta", "text": msg.get("content") or ""}
            return
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            fn = c.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool", "name": name, "label": TOOL_LABEL.get(name, name)}
            result = execute_tool(ctx, name, args)
            yield {"type": "tool_result", "name": name, "ok": result.get("ok"), "status": result.get("status"), "error": result.get("error")}
            msgs.append({"role": "tool", "tool_call_id": c.get("id", name), "content": json.dumps(result, ensure_ascii=False, default=str)[:12000]})
    yield {"type": "delta", "text": "Ich habe die maximale Anzahl an Arbeitsschritten erreicht. Bitte formuliere die Anfrage etwas enger."}


# ----------------------------------------------------------------- Ein Chat-Zug
def run_turn(db: Session, user: User, conv: Conversation, content: str, via_voice: bool = False) -> Iterator[dict]:
    started = datetime.now(timezone.utc)
    db.add(Message(conversation_id=conv.id, role="user", content=content, meta={"voice": via_voice}))
    if conv.title == "Neues Gespräch":
        conv.title = content.strip().split("\n")[0][:80]
    conv.updated_at = started
    db.commit()
    yield {"type": "status", "state": "thinking"}
    text, tools_used, backend, error = "", [], None, None
    try:
        backend = choose_backend(db)
        yield {"type": "backend", "name": backend}
        messages = build_messages(db, user, conv)
        stream = run_hermes(messages) if backend == "hermes" else run_direct(db, user, conv.id, messages)
        for ev in stream:
            if ev["type"] == "delta":
                text += ev["text"]
            elif ev["type"] == "tool":
                tools_used.append(ev["name"])
                yield {"type": "status", "state": "acting", "label": ev["label"]}
            yield ev
    except AIUnavailable as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("Agentenfehler")
        error = f"Unerwarteter Fehler im Assistenten: {exc.__class__.__name__}"
    db.rollback()
    # Während des Zuges entstandene Bestätigungsanfragen diesem Gespräch zuordnen
    pending = list(db.scalars(select(PendingAction).where(PendingAction.created_at >= started, PendingAction.status == "pending")))
    for p in pending:
        p.conversation_id = conv.id
    meta = {"backend": backend, "tools": tools_used, "pending_actions": [p.id for p in pending]}
    if error:
        meta["error"] = True
        msg = Message(conversation_id=conv.id, role="assistant", content=error, meta=meta)
    else:
        msg = Message(conversation_id=conv.id, role="assistant", content=text.strip() or "(keine Antwort)", meta=meta)
    db.add(msg)
    db.commit()
    yield {
        "type": "done", "message_id": msg.id, "content": msg.content, "error": error,
        "pending_actions": [{"id": p.id, "tool": p.tool, "description": p.description, "preview": p.preview, "status": p.status} for p in pending],
    }
    if not error:
        try:
            maybe_summarize(db, conv)
        except Exception:  # noqa: BLE001
            log.warning("Zusammenfassung fehlgeschlagen", exc_info=True)


# ----------------------------------------------------------------- Einfache Textgenerierung
def complete_text(db: Session, system: str, prompt: str) -> str:
    """Einfache Textgenerierung ohne Werkzeuge (Zusammenfassungen)."""
    backend = choose_backend(db)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    if backend == "hermes":
        return "".join(e["text"] for e in run_hermes(messages) if e["type"] == "delta").strip()
    return (_direct_call(db, messages, None).get("content") or "").strip()


def maybe_summarize(db: Session, conv: Conversation) -> None:
    """Lange Gespräche: ältere Nachrichten werden zu einer Zusammenfassung verdichtet."""
    ids = list(db.scalars(select(Message.id).where(Message.conversation_id == conv.id).order_by(Message.id)))
    if len(ids) < SUMMARIZE_AFTER:
        return
    cutoff = ids[-HISTORY_MESSAGES]
    if conv.summarized_until >= cutoff:
        return
    old = list(db.scalars(select(Message).where(Message.conversation_id == conv.id, Message.id < cutoff, Message.id > conv.summarized_until).order_by(Message.id)))
    if not old:
        return
    transcript = "\n".join(f"{m.role}: {m.content[:800]}" for m in old)
    prev = f"Bisherige Zusammenfassung: {conv.summary}\n\n" if conv.summary else ""
    summary = complete_text(db, "Fasse Gespräche für ein Gedächtnis knapp auf Deutsch zusammen (max. 12 Stichpunkte). Nur Fakten, Entscheidungen, offene Punkte.", prev + transcript)
    if summary:
        conv.summary = summary[:6000]
        conv.summarized_until = cutoff - 1
        db.commit()
