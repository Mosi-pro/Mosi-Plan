# KI: Hermes Agent & Modellanbieter

## Architektur
```
Browser ──> MOSI-Backend ──(OpenAI-kompatibel, /v1/chat/completions, Bearer)──> Hermes Agent (API-Server, Port 8642, intern)
                 ^                                                                     │
                 └──────────────── MCP (Streamable HTTP, /internal/mcp, Bearer) <──────┘
```
- MOSI ruft den **dokumentierten OpenAI-kompatiblen API-Server** des Hermes-Gateways auf (`API_SERVER_ENABLED`, `API_SERVER_KEY`, `API_SERVER_HOST`, Port 8642 laut Hermes-Doku „API Server“).
- Hermes erhält genau einen Werkzeugsatz: den MOSI-MCP-Server (`mcp_servers.mosi` mit `url` + `headers`, laut „MCP Config Reference“). `platform_toolsets.api_server: ["mosi"]` beschränkt den API-Server auf diese Werkzeuge; `agent.disabled_toolsets` schaltet Terminal, Datei, Code-Ausführung, Browser usw. zusätzlich überall ab.
- Alle Daten liegen in der MOSI-Datenbank. Hermes ist nur die Agentenebene.
- Ist Hermes nicht erreichbar, bleibt MOSI voll nutzbar; optional übernimmt ein **direkter OpenAI-kompatibler Anbieter** mit denselben Werkzeugen (Einstellungen → KI → Fallback).

Konfigurationsdateien: `data/hermes/config.yaml` (Modell, MCP, Toolsets) und `data/hermes/.env` (API-Server-Schlüssel, Anbieter-Schlüssel). Vorlage: `deployment/hermes/config.yaml.template`. Nach Änderungen: `docker compose restart hermes`.

Kompatibilität: Das offizielle Image `nousresearch/hermes-agent` basiert laut Repository auf Debian 13 (trixie) und läuft als Container auf amd64/arm64 – passend zum Zielsystem. Die verwendete Version wird über `HERMES_IMAGE` gesteuert (Standard: `stable`; für reproduzierbare Installationen eine feste Version oder einen Digest eintragen).

## Werkzeuge
`get_daily_overview`, `get_calendar_events`, `get_free_slots`, `create_calendar_event`, `update_calendar_event`, `delete_calendar_event`*, `get_projects`, `create_project`, `update_project`, `delete_project`*, `get_tasks`, `create_task`, `update_task`, `complete_task`, `bulk_update_tasks`*, `propose_project_plan`*, `create_weekly_plan`, `search_memory`, `save_memory`

\* immer bestätigungspflichtig; zusätzlich jedes Schreiben in Google Calendar. Bestätigungspflichtige Aufrufe erzeugen eine „ausstehende Aktion“, die erst nach Klick auf **Bestätigen** ausgeführt wird (24 h gültig). Jede Eingabe wird per Pydantic validiert; es gibt keinerlei Shell- oder Dateiwerkzeug.

## Modellanbieter & Kosten (ehrlich)
MOSI selbst ist kostenlos, das **Sprachmodell nicht unbedingt**:
- **OpenRouter**: viele Modelle, einige als kostenlose Varianten mit strengen Rate-Limits. Limits und Verfügbarkeit ändern sich – bitte aktuell unter openrouter.ai prüfen. Für zuverlässige Werkzeugnutzung ist ein Modell mit gutem Function-Calling nötig.
- **Eigener Server (Ollama, vLLM, LM Studio)**: kostenlos, aber braucht passende Hardware – **nicht** auf dem 30-GB-Server vorgesehen.
- **Kommerzielle Anbieter**: kostenpflichtig nach Verbrauch.

Kostenlose Nutzung wird hier ausdrücklich **nicht** zugesichert – Limits und Bedingungen bitte beim gewählten Anbieter nachlesen.

## Sprache
- **Spracheingabe**: Standard ist die Web Speech API des Browsers (kostenlos; Chrome/Edge/Safari; Audio wird vom Browser-Hersteller verarbeitet; Firefox nicht unterstützt). Alternativ ein OpenAI-kompatibler Whisper-Dienst (`…/audio/transcriptions`) – Einstellungen → Sprache.
- **Sprachausgabe**: Browser-Stimmen (automatische Wahl einer männlichen deutschen Stimme, z. B. „Microsoft Conrad Online (Natural)“ in Edge) oder ein OpenAI-kompatibler TTS-Dienst (`…/audio/speech`), z. B. ein selbst betriebener Piper-Server mit der Stimme „thorsten“.
