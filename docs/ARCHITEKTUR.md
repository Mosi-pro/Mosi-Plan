# Architektur & Sicherheit

```
mosi-plan/
  backend/    FastAPI, SQLAlchemy, Alembic, Jobs, KI-Werkzeuge, MCP  (app/routers, app/services, app/ai)
  frontend/   React, TypeScript, Vite, Tailwind, Radix-Primitives, Lucide; Nginx-Konfiguration
  deployment/ Hermes-Konfigurationsvorlage
  scripts/    install, update, backup, restore, status, logs, uninstall
  docs/
```

**Trennung:** Frontend (statisch, Nginx) · Backend (API, Fachlogik) · KI-Agent (Hermes, eigener Container) · Datenbank (PostgreSQL) · Kalenderintegration (`services/google_calendar.py`) · Sprachverarbeitung (Browser bzw. austauschbare Server-Endpunkte) · Hintergrundjobs (`app/jobs.py`, ein Scheduler per Advisory-Lock).

**Datenbank:** Tabellen für Benutzer, Sitzungen, Einstellungen, Projekte, Aufgaben (Unteraufgaben, Abhängigkeiten), Kategorien, Termine (intern + Google-Spiegel), Google-Kalender, Gespräche/Nachrichten, ausstehende Aktionen, Gedächtnis (GIN-Index, deutsche Volltextsuche), Wochenpläne/-blöcke, Benachrichtigungen, Push-Abos, Audit-Log. pgvector wurde bewusst **nicht** eingesetzt: semantische Suche bräuchte ein zusätzliches Embedding-Modell bzw. einen weiteren kostenpflichtigen Dienst; die deutsche Volltextsuche deckt den Einzelnutzer-Bedarf ab.

**Sicherheit**
- Passwörter mit Argon2id; Sitzungen als zufällige Tokens (nur SHA-256-Hash in der DB), Cookie `HttpOnly; Secure; SameSite=Strict`, 14 Tage
- CSRF-Schutz: serverseitig gebundenes Token im Header `X-CSRF-Token` für alle schreibenden Aufrufe
- Rate-Limiting für Login, Chat, KI, Sprache, Export, Backup
- Keine Registrierung; Admin wird bei der Installation per CLI angelegt; keine Passwörter im Code
- API-Schlüssel (KI, Sprache, Discord, Google) werden mit Fernet (aus `SECRET_KEY` abgeleitet) verschlüsselt gespeichert und nie an das Frontend ausgeliefert
- Pydantic-Validierung aller Eingaben, ORM-Parameterbindung (kein SQL-Injection-Risiko), Upload-Prüfung per Magic Bytes und Größenlimit
- Sicherheitsheader (CSP, X-Frame-Options, HSTS, Permissions-Policy) in Nginx
- `/internal/mcp` ist von außen nicht erreichbar und zusätzlich tokengeschützt; Hermes hat keine Ports nach außen
- Agent ohne Shell-/Dateizugriff, explizite Werkzeugliste, Bestätigung für destruktive Aktionen
- Audit-Log für Anmeldungen, Änderungen, KI-Aktionen und Bestätigungen
- Tägliche Backups; Datenexport als JSON
